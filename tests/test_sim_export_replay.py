"""Export, replay and negative tests against a FABRICATED fake environment.

These test the logic only. No simulator runs here, so no result here is evidence for any exit test.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest
from ironclad.contracts.v1 import audit_splits
from ironclad.contracts.v1.validate import ContractError, validate_episode

from fake_env import FakeArmEnv, plan_policy, scripted_plan
from vishwaroop.outcome.pickplace import PickPlaceJudge, PlaceRubric, assess, samples_from_episode
from vishwaroop.sim import negative_tests, replay
from vishwaroop.sim.contract import contract_judge
from vishwaroop.sim.env import Packet, SimEnv, SimulatorUnavailableError
from vishwaroop.sim.export import EpisodeSpec, record_episode
from vishwaroop.sim.negative_tests import CASES, PositiveControlError, run_negative_tests
from vishwaroop.sim.negative_tests import main as negative_main
from vishwaroop.sim.replay import (
    FORCED_INTERMEDIATE_STATES,
    ReplayInvalidError,
    ReplayTolerance,
    load_frozen,
    replay_episode,
    require_frozen_file,
)
from vishwaroop.sim.replay import main as replay_main

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "evals" / "M0-exit-tests.json"
RUBRIC = PlaceRubric(
    rubric_version="test",
    target_radius_m=0.015625,
    rest_height_m=0.0125,
    rest_height_tolerance_m=0.005,
    min_lift_above_rest_m=0.02,
    max_step_motion_m=0.001,
    dwell_steps=10,
)
STREAMS = ["joint_position", "object_position", "target_position"]
TOLERANCE = ReplayTolerance(STREAMS, 0.001, 3, 200)


def _spec(episode_id: str = "ep-1", seed: int = 3, **changes: Any) -> EpisodeSpec:
    base = EpisodeSpec(
        episode_id=episode_id,
        seed=seed,
        purpose="schema_fixture",
        task_id="fake_place",
        task_version="1",
        instruction="FABRICATED test task",
        embodiment_id="fabricated_tool_point",
        rubric=RUBRIC,
        protocol_version="test",
        policy_family="fixture-scripted",
        partition="dev",
        suite_id="fixtures-not-evidence",
        scene_group_id="fixture-scene",
        session_group_id="fixture-session",
        max_steps=200,
        notes="FABRICATED by a test. No simulator ran.",
        created_at="2026-10-31T00:00:00+00:00",
    )
    return replace(base, **changes)


def _episode(tmp_path: Path, **plan_options: Any) -> Path:
    plan = scripted_plan(3, **plan_options)
    return record_episode(FakeArmEnv(), plan_policy(plan), _spec(), tmp_path / "ep-1")


def _manifest(episode: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((episode / "episode.json").read_text(encoding="utf-8"))
    return loaded


def _write_manifest(episode: Path, manifest: dict[str, Any]) -> None:
    (episode / "episode.json").write_text(json.dumps(manifest), encoding="utf-8")


def _records(episode: Path) -> list[dict[str, Any]]:
    text = (episode / "transitions.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def _rewrite_records(episode: Path, records: list[dict[str, Any]]) -> None:
    text = "".join(json.dumps(r, sort_keys=True) + "\n" for r in records)
    (episode / "transitions.jsonl").write_text(text, encoding="utf-8")
    manifest = _manifest(episode)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    manifest["data"]["transitions_artifact"]["sha256"] = digest
    _write_manifest(episode, manifest)


def _rewrite_artifact(episode: Path, name: str, value: Any, *where: str) -> None:
    """Replace a JSON artifact and fix its hash, so only the semantic check can object."""
    data = json.dumps(value).encode("utf-8")
    (episode / name).write_bytes(data)
    manifest = _manifest(episode)
    node = manifest
    for key in where:
        node = node[key]
    node["sha256"] = hashlib.sha256(data).hexdigest()
    _write_manifest(episode, manifest)


class TamperEnv(FakeArmEnv):
    """The fake with a function applied to each packet; the step is 0 right after a restore."""

    def __init__(self, tamper: Callable[[Packet, int], Packet]) -> None:
        super().__init__()
        self._tamper = tamper
        self._step = 0

    def restore_state(self, state: bytes) -> Packet:
        self._step = 0
        return self._tamper(super().restore_state(state), 0)

    def step(self, action: list[float]) -> Packet:
        self._step += 1
        return self._tamper(super().step(action), self._step)


def _set(packet: Packet, stream: str, coordinate: int, value: float) -> Packet:
    changed = {name: list(values) for name, values in packet.items()}
    changed[stream][coordinate] = value
    return changed


def _offset(packet: Packet, stream: str, coordinate: int, size: float) -> Packet:
    return _set(packet, stream, coordinate, packet[stream][coordinate] + size)


# ---------------------------------------------------------------------------- export


def test_fake_env_implements_the_interface() -> None:
    assert isinstance(FakeArmEnv(), SimEnv)


def test_exported_episode_is_contract_valid(tmp_path: Path) -> None:
    episode = _episode(tmp_path)
    assert validate_episode(episode / "episode.json")["status"] == "contract_valid"
    manifest = _manifest(episode)
    assert manifest["producer"] == "vishwaroop"
    assert manifest["environment_kind"] == "physics_sim"
    assert manifest["simulator"]["restore_mode"] == "initial_state_only"
    assert manifest["outcome"]["assessment_method"] == "independent_sim_state"
    assert manifest["outcome"]["training_reward_artifact"] is None


def test_unreported_action_stages_stay_null(tmp_path: Path) -> None:
    action = _records(_episode(tmp_path))[0]["action"]
    assert action["requested"] is not None
    for key in ("filtered", "transmitted", "applied", "sent_t_ns", "applied_t_ns"):
        assert action[key] is None


def test_time_advances_by_one_control_step(tmp_path: Path) -> None:
    records = _records(_episode(tmp_path))
    dt = FakeArmEnv.dt_ns
    assert [r["t_ns"] for r in records[:3]] == [0, dt, 2 * dt]
    second = records[1]
    assert second["observations"][0]["capture_t_ns"] == dt
    assert second["next_observations"][0]["received_t_ns"] == 2 * dt
    assert second["action"]["decision_t_ns"] == dt
    assert second["action"]["valid_until_t_ns"] == 2 * dt


def test_initial_state_is_saved_before_any_action(tmp_path: Path) -> None:
    episode = _episode(tmp_path)
    saved = json.loads((episode / "initial-state.json").read_text(encoding="utf-8"))
    fresh = FakeArmEnv()
    fresh.reset(3)
    assert saved == json.loads(fresh.save_state().decode("utf-8"))


def test_export_is_write_once(tmp_path: Path) -> None:
    episode = _episode(tmp_path)
    before = (episode / "episode.json").read_bytes()
    with pytest.raises(ContractError, match="write-once"):
        record_episode(FakeArmEnv(), plan_policy(scripted_plan(3)), _spec(), episode)
    assert (episode / "episode.json").read_bytes() == before


def test_step_limit_truncates(tmp_path: Path) -> None:
    episode = record_episode(
        FakeArmEnv(), lambda _p, _s: [0.0] * 4, _spec(max_steps=5), tmp_path / "short"
    )
    manifest = _manifest(episode)
    assert manifest["data"]["record_count"] == 5
    assert manifest["outcome"]["truncated"] is True
    assert manifest["outcome"]["terminated"] is False
    assert manifest["outcome"]["success"] is None


def test_a_policy_that_stops_terminates(tmp_path: Path) -> None:
    outcome = _manifest(_episode(tmp_path))["outcome"]
    assert outcome["terminated"] is True
    assert outcome["truncated"] is False


def test_an_empty_episode_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ContractError, match="at least one"):
        record_episode(FakeArmEnv(), lambda _p, _s: None, _spec(), tmp_path / "none")


class MissingStreamEnv(FakeArmEnv):
    def _packet(self) -> Packet:
        packet = super()._packet()
        del packet["object_position"]
        return packet


def test_a_missing_stream_is_recorded_as_invalid_and_does_not_decide(tmp_path: Path) -> None:
    episode = record_episode(
        MissingStreamEnv(), plan_policy(scripted_plan(3)), _spec(), tmp_path / "ep"
    )
    packet = next(
        p for p in _records(episode)[0]["observations"] if p["stream"] == "object_position"
    )
    assert packet["valid"] is False
    assert packet["value"] is None
    outcome = _manifest(episode)["outcome"]
    assert outcome["success"] is None
    assert outcome["reason"].startswith("insufficient_evidence")


class NanEnv(FakeArmEnv):
    def _packet(self) -> Packet:
        return _set(super()._packet(), "object_position", 1, math.nan)


def test_a_non_finite_stream_is_recorded_as_invalid_and_does_not_decide(tmp_path: Path) -> None:
    episode = record_episode(NanEnv(), plan_policy(scripted_plan(3)), _spec(), tmp_path / "ep")
    assert validate_episode(episode / "episode.json")["status"] == "contract_valid"
    packet = next(
        p for p in _records(episode)[0]["observations"] if p["stream"] == "object_position"
    )
    assert packet["valid"] is False
    assert _manifest(episode)["outcome"]["success"] is None


def test_the_policy_sees_only_input_streams(tmp_path: Path) -> None:
    seen: list[set[str]] = []

    def policy(packet: Packet, step: int) -> list[float] | None:
        seen.append(set(packet))
        return None if step else [0.0] * 4

    record_episode(FakeArmEnv(), policy, _spec(), tmp_path / "ep")
    assert seen[0] == {"joint_position", "object_position", "target_position"}


@pytest.mark.parametrize(
    ("options", "success", "label"),
    [
        ({}, True, "success"),
        ({"release": False}, False, "still_grasped"),
        ({"target_miss": 0.05}, False, "outside_target"),
    ],
)
def test_recorded_outcome_matches_the_judge_on_the_exported_files(
    tmp_path: Path, options: dict[str, Any], success: bool, label: str
) -> None:
    episode = _episode(tmp_path, **options)
    manifest = _manifest(episode)
    assert manifest["outcome"]["success"] is success
    assert manifest["outcome"]["reason"].startswith(label)
    verdict, note = PickPlaceJudge(RUBRIC).judge(str(episode))
    assert verdict is success
    assert note.startswith(label)
    final = json.loads((episode / "final-assessment.json").read_text(encoding="utf-8"))
    assert final == asdict(assess(samples_from_episode(episode), RUBRIC))
    assert final["success"] is success


def test_rubric_artifact_is_the_rubric_used(tmp_path: Path) -> None:
    episode = _episode(tmp_path)
    assert json.loads((episode / "rubric.json").read_text(encoding="utf-8")) == asdict(RUBRIC)


# ---------------------------------------------------------------------------- replay: holds


def test_replay_of_a_reproducing_simulator_holds(tmp_path: Path) -> None:
    report = replay_episode(_episode(tmp_path), FakeArmEnv(), TOLERANCE, RUBRIC)
    assert report.claim_valid, report.reason
    assert report.recorded_label == "success"
    assert report.record_count == len(scripted_plan(3))
    assert [r.repeat for r in report.repeats] == [0, 1, 2]
    assert all(r.max_deviation == 0.0 and r.outcome_label == "success" for r in report.repeats)


def test_report_has_per_step_deviations_for_each_compared_stream(tmp_path: Path) -> None:
    report = replay_episode(_episode(tmp_path), FakeArmEnv(), TOLERANCE, RUBRIC)
    per_step = report.repeats[0].per_step
    assert len(per_step) == report.record_count + 1
    assert set(per_step[0]) == set(STREAMS)


def test_a_failed_episode_can_be_confirmed_as_failed(tmp_path: Path) -> None:
    report = replay_episode(_episode(tmp_path, release=False), FakeArmEnv(), TOLERANCE, RUBRIC)
    assert report.claim_valid
    assert report.recorded_label == "still_grasped"


# ---------------------------------------------------------------------------- replay: deviations


def test_replay_fails_when_deviation_exceeds_the_tolerance(tmp_path: Path) -> None:
    report = replay_episode(_episode(tmp_path), FakeArmEnv(drift=0.01), TOLERANCE, RUBRIC)
    assert not report.claim_valid
    assert "deviated" in report.reason


def test_replay_passes_at_the_tolerance_and_fails_just_past_it(tmp_path: Path) -> None:
    episode = _episode(tmp_path)

    def env() -> TamperEnv:
        return TamperEnv(lambda p, s: _offset(p, "joint_position", 0, 0.0005) if s == 4 else p)

    worst = replay_episode(episode, env(), TOLERANCE, RUBRIC).repeats[0].max_deviation
    assert worst == pytest.approx(0.0005)
    at_limit = ReplayTolerance(STREAMS, worst, 3)
    assert replay_episode(episode, env(), at_limit, RUBRIC).claim_valid
    under = ReplayTolerance(STREAMS, worst * 0.999, 3)
    assert not replay_episode(episode, env(), under, RUBRIC).claim_valid


@pytest.mark.parametrize(
    ("stream", "coordinate"),
    [
        ("joint_position", 0),
        ("joint_position", 3),
        ("object_position", 2),
        ("target_position", 1),
    ],
)
def test_an_error_in_any_compared_coordinate_is_caught(
    tmp_path: Path, stream: str, coordinate: int
) -> None:
    env = TamperEnv(lambda p, s: _offset(p, stream, coordinate, 0.002) if s == 5 else p)
    report = replay_episode(_episode(tmp_path), env, TOLERANCE, RUBRIC)
    assert not report.claim_valid
    assert stream in report.reason
    assert report.repeats[0].worst_stream == stream
    assert report.repeats[0].worst_step == 5


def test_a_spike_mid_episode_is_caught_even_when_the_end_is_clean(tmp_path: Path) -> None:
    env = TamperEnv(lambda p, s: _offset(p, "joint_position", 0, 0.5) if s == 5 else p)
    assert not replay_episode(_episode(tmp_path), env, TOLERANCE, RUBRIC).claim_valid


def test_a_wrong_restore_is_caught_at_step_zero(tmp_path: Path) -> None:
    env = TamperEnv(lambda p, s: _offset(p, "object_position", 0, 0.5) if s == 0 else p)
    report = replay_episode(_episode(tmp_path), env, TOLERANCE, RUBRIC)
    assert not report.claim_valid
    assert report.repeats[0].worst_step == 0


@pytest.mark.parametrize(("value",), [(math.nan,), (math.inf,)])
@pytest.mark.parametrize("coordinate", [0, 3])
def test_a_non_finite_value_during_replay_fails(
    tmp_path: Path, value: float, coordinate: int
) -> None:
    """A physics blow-up must never read as a perfect replay."""
    env = TamperEnv(lambda p, s: _set(p, "joint_position", coordinate, value) if s >= 1 else p)
    report = replay_episode(_episode(tmp_path), env, TOLERANCE, RUBRIC)
    assert not report.claim_valid
    assert report.repeats[0].max_deviation == math.inf


def test_all_streams_non_finite_during_replay_fails(tmp_path: Path) -> None:
    def blow_up(packet: Packet, step: int) -> Packet:
        if step == 0:
            return packet
        return {name: [math.nan] * len(values) for name, values in packet.items()}

    report = replay_episode(_episode(tmp_path), TamperEnv(blow_up), TOLERANCE, RUBRIC)
    assert not report.claim_valid


def test_a_different_outcome_under_the_tolerance_fails(tmp_path: Path) -> None:
    """Grasp is not a compared stream, so only the identical-label rule can catch this."""
    env = TamperEnv(lambda p, s: _set(p, "object_grasped", 0, 1.0) if s > 25 else p)
    report = replay_episode(_episode(tmp_path), env, TOLERANCE, RUBRIC)
    assert not report.claim_valid
    assert "gave outcome still_grasped" in report.reason
    assert report.repeats[0].max_deviation == 0.0


def test_a_missing_compared_stream_is_refused(tmp_path: Path) -> None:
    def drop(packet: Packet, _: int) -> Packet:
        return {k: v for k, v in packet.items() if k != "joint_position"}

    with pytest.raises((ReplayInvalidError, KeyError)):
        replay_episode(_episode(tmp_path), TamperEnv(drop), TOLERANCE, RUBRIC)


def test_a_compared_stream_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    tolerance = ReplayTolerance(["no_such_stream"], 0.001, 3)
    with pytest.raises(ReplayInvalidError, match="cannot be compared"):
        replay_episode(_episode(tmp_path), FakeArmEnv(), tolerance, RUBRIC)


# ---------------------------------------------------------------------------- replay: inputs


@pytest.mark.parametrize(
    ("tolerance", "message"),
    [
        (ReplayTolerance(STREAMS, 0.001, 0), "repeats"),
        (ReplayTolerance(STREAMS, 0.001, -1), "repeats"),
        (ReplayTolerance([], 0.001, 3), "compare_streams"),
        (ReplayTolerance(STREAMS, math.inf, 3), "max_state_deviation"),
        (ReplayTolerance(STREAMS, math.nan, 3), "max_state_deviation"),
        (ReplayTolerance(STREAMS, -0.1, 3), "max_state_deviation"),
    ],
)
def test_an_unusable_tolerance_is_refused(
    tmp_path: Path, tolerance: ReplayTolerance, message: str
) -> None:
    with pytest.raises(ReplayInvalidError, match=message):
        replay_episode(_episode(tmp_path), FakeArmEnv(), tolerance, RUBRIC)


def test_an_episode_past_the_frozen_step_limit_is_refused(tmp_path: Path) -> None:
    tolerance = ReplayTolerance(STREAMS, 0.001, 3, 5)
    with pytest.raises(ReplayInvalidError, match="frozen limit"):
        replay_episode(_episode(tmp_path), FakeArmEnv(), tolerance, RUBRIC)


def test_an_undecided_episode_gives_no_claim(tmp_path: Path) -> None:
    episode = record_episode(
        FakeArmEnv(), lambda _p, _s: [0.0] * 4, _spec(max_steps=3), tmp_path / "short"
    )
    report = replay_episode(episode, FakeArmEnv(), TOLERANCE, RUBRIC)
    assert not report.claim_valid
    assert "undecided" in report.reason


def test_replay_refuses_a_different_simulator_version(tmp_path: Path) -> None:
    other = FakeArmEnv()
    other.version = "fixture-2"
    with pytest.raises(ReplayInvalidError, match="engine and version"):
        replay_episode(_episode(tmp_path), other, TOLERANCE, RUBRIC)


@pytest.mark.parametrize(
    "change",
    [
        lambda m: m["action_spec"].update(units=["deg"] * 4),
        lambda m: m["action_spec"].update(representation="joint_velocity"),
        lambda m: m["action_spec"].update(frame_id="world"),
        lambda m: m["action_spec"].update(lower=[-2.0, -1.0, -1.0, 0.0]),
        lambda m: m["action_spec"].update(upper=[2.0, 1.0, 1.0, 1.0]),
        lambda m: m["action_spec"].update(semantics="forged"),
        lambda m: m["streams"][1].update(units=["mm"] * 3),
        lambda m: m["streams"][0].update(units=["mm"] * 4),
    ],
)
def test_changed_action_or_stream_meaning_is_refused(
    tmp_path: Path, change: Callable[[dict[str, Any]], None]
) -> None:
    episode = _episode(tmp_path)
    manifest = _manifest(episode)
    change(manifest)
    _write_manifest(episode, manifest)
    with pytest.raises(ReplayInvalidError, match="differ"):
        replay_episode(episode, FakeArmEnv(), TOLERANCE, RUBRIC)


@pytest.mark.parametrize(
    ("name", "where", "message"),
    [
        ("assets.json", ("simulator", "asset_manifest_artifact"), "assets"),
        ("stack.json", ("configuration", "stack_artifact"), "stacks"),
    ],
)
def test_changed_assets_or_stack_are_refused(
    tmp_path: Path, name: str, where: tuple[str, ...], message: str
) -> None:
    episode = _episode(tmp_path)
    _rewrite_artifact(episode, name, {"changed": True}, *where)
    with pytest.raises(ReplayInvalidError, match=message):
        replay_episode(episode, FakeArmEnv(), TOLERANCE, RUBRIC)


def test_a_simulator_with_other_assets_is_refused(tmp_path: Path) -> None:
    class OtherAssets(FakeArmEnv):
        def asset_manifest(self) -> dict[str, Any]:
            return {"robot.urdf": "another-hash"}

    with pytest.raises(ReplayInvalidError, match="assets"):
        replay_episode(_episode(tmp_path), OtherAssets(), TOLERANCE, RUBRIC)


def test_a_simulator_with_another_stack_is_refused(tmp_path: Path) -> None:
    class OtherStack(FakeArmEnv):
        def stack_identity(self) -> dict[str, Any]:
            return {"sapien": "9.9.9"}

    with pytest.raises(ReplayInvalidError, match="stacks"):
        replay_episode(_episode(tmp_path), OtherStack(), TOLERANCE, RUBRIC)


def test_a_simulator_with_another_configuration_is_refused(tmp_path: Path) -> None:
    class OtherConfiguration(FakeArmEnv):
        def configuration(self) -> dict[str, Any]:
            return {"env_id": "OtherTask-v1"}

    with pytest.raises(ReplayInvalidError, match="configurations"):
        replay_episode(_episode(tmp_path), OtherConfiguration(), TOLERANCE, RUBRIC)


def _scale_times(records: list[dict[str, Any]], factor: int) -> None:
    for record in records:
        record["t_ns"] *= factor
        record["dt_ns"] *= factor
        record["action"]["decision_t_ns"] *= factor
        record["action"]["valid_until_t_ns"] *= factor
        for packet in (*record["observations"], *record["next_observations"]):
            packet["capture_t_ns"] *= factor
            packet["received_t_ns"] *= factor


def test_a_coherent_wrong_timebase_is_refused(tmp_path: Path) -> None:
    episode = _episode(tmp_path)
    records = _records(episode)
    _scale_times(records, 1000)
    _rewrite_records(episode, records)
    assert validate_episode(episode / "episode.json")["status"] == "contract_valid"
    with pytest.raises(ReplayInvalidError, match="timebase differs"):
        replay_episode(episode, FakeArmEnv(), TOLERANCE, RUBRIC)


def test_a_simulator_with_another_control_rate_is_refused(tmp_path: Path) -> None:
    other = FakeArmEnv()
    other.dt_ns = 1
    with pytest.raises(ReplayInvalidError, match="timebase differs"):
        replay_episode(_episode(tmp_path), other, TOLERANCE, RUBRIC)


def test_another_clock_domain_is_refused(tmp_path: Path) -> None:
    episode = _episode(tmp_path)
    manifest = _manifest(episode)
    manifest["timebase"]["clock_domain"] = "wall_clock"
    _write_manifest(episode, manifest)
    with pytest.raises(ReplayInvalidError, match="clock domains"):
        replay_episode(episode, FakeArmEnv(), TOLERANCE, RUBRIC)


def test_observations_that_do_not_follow_from_the_previous_step_are_refused(tmp_path: Path) -> None:
    episode = _episode(tmp_path)
    records = _records(episode)
    for record in records[1:]:
        for packet in record["observations"]:
            packet["value"] = [123.0] * len(packet["value"])
    _rewrite_records(episode, records)
    assert validate_episode(episode / "episode.json")["status"] == "contract_valid"
    with pytest.raises(ReplayInvalidError, match="differ from the state"):
        replay_episode(episode, FakeArmEnv(), TOLERANCE, RUBRIC)


# ---------------------------------------------------------------------------- replay: outcome


def test_a_forged_recorded_success_is_refused(tmp_path: Path) -> None:
    episode = _episode(tmp_path, release=False)
    manifest = _manifest(episode)
    manifest["outcome"]["success"] = True
    manifest["outcome"]["reason"] = "success: forged"
    _write_manifest(episode, manifest)
    assert validate_episode(episode / "episode.json")["status"] == "contract_valid"
    with pytest.raises(ReplayInvalidError, match="success values"):
        replay_episode(episode, FakeArmEnv(), TOLERANCE, RUBRIC)


def test_a_forged_recorded_reason_is_refused(tmp_path: Path) -> None:
    episode = _episode(tmp_path, release=False)
    manifest = _manifest(episode)
    manifest["outcome"]["reason"] = "outside_target: forged"
    _write_manifest(episode, manifest)
    with pytest.raises(ReplayInvalidError, match="does not match outcome"):
        replay_episode(episode, FakeArmEnv(), TOLERANCE, RUBRIC)


def test_a_forged_final_assessment_is_refused(tmp_path: Path) -> None:
    episode = _episode(tmp_path, release=False)
    final = json.loads((episode / "final-assessment.json").read_text(encoding="utf-8"))
    final["success"] = True
    _rewrite_artifact(
        episode, "final-assessment.json", final, "outcome", "final_assessment_artifact"
    )
    with pytest.raises(ReplayInvalidError, match="final assessments"):
        replay_episode(episode, FakeArmEnv(), TOLERANCE, RUBRIC)


def test_another_rubric_is_refused(tmp_path: Path) -> None:
    other = replace(RUBRIC, target_radius_m=0.5)
    with pytest.raises(ReplayInvalidError, match="rubrics"):
        replay_episode(_episode(tmp_path), FakeArmEnv(), TOLERANCE, other)


def test_another_rubric_version_is_refused(tmp_path: Path) -> None:
    other = replace(RUBRIC, rubric_version="other")
    with pytest.raises(ReplayInvalidError, match="rubric versions"):
        replay_episode(_episode(tmp_path), FakeArmEnv(), TOLERANCE, other)


def test_a_forged_target_that_flips_the_label_is_refused(tmp_path: Path) -> None:
    episode = _episode(tmp_path, target_miss=0.05)
    records = _records(episode)
    for record in records:
        for packets in (record["observations"], record["next_observations"]):
            for packet in packets:
                if packet["stream"] == "target_position":
                    packet["value"][0] += 0.05
    _rewrite_records(episode, records)
    with pytest.raises(ReplayInvalidError):
        replay_episode(episode, FakeArmEnv(), TOLERANCE, RUBRIC)


# ---------------------------------------------------------------------------- forcing


def test_replay_notices_an_environment_that_forces_state_during_steps(tmp_path: Path) -> None:
    report = replay_episode(_episode(tmp_path), FakeArmEnv(forces_state=True), TOLERANCE, RUBRIC)
    assert not report.claim_valid
    assert "restored" in report.reason


def test_forcing_mode_really_forces_state_and_is_rejected_by_the_counter(tmp_path: Path) -> None:
    env = FakeArmEnv()
    episode = _episode(tmp_path)
    report = replay_episode(episode, env, TOLERANCE, RUBRIC, mode=FORCED_INTERMEDIATE_STATES)
    assert not report.claim_valid
    assert "state was restored" in report.reason
    assert report.repeats
    assert env.state_restores == 3 * (1 + report.record_count)


def test_an_unknown_mode_is_an_error_not_a_rejection(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown replay mode"):
        replay_episode(_episode(tmp_path), FakeArmEnv(), TOLERANCE, RUBRIC, mode="anything")


# ---------------------------------------------------------------------------- negative tests


def test_all_five_negative_tests_reject_for_their_named_reasons(tmp_path: Path) -> None:
    results = run_negative_tests(_episode(tmp_path), FakeArmEnv(), TOLERANCE, RUBRIC)
    assert [r.name for r in results] == [case[0] for case in CASES]
    assert len(results) == 5
    assert all(r.rejected for r in results), results
    assert len({r.reason for r in results}) == 5
    reasons = {r.name: r.reason for r in results}
    assert "action spec" in reasons["corrupted_action_semantics"]
    assert "checksum mismatch" in reasons["broken_artifact_hash"]
    assert "missing or escaped artifact" in reasons["missing_asset"]
    assert "timebase differs" in reasons["wrong_timebase"]
    assert "state was restored" in reasons["intermediate_state_forcing"]


def test_a_shifted_time_field_alone_fails_contract_validation(tmp_path: Path) -> None:
    episode = _episode(tmp_path)
    records = _records(episode)
    for record in records:
        record["t_ns"] += 1
    _rewrite_records(episode, records)
    with pytest.raises(ContractError, match="decision"):
        validate_episode(episode / "episode.json")


def test_negative_tests_refuse_an_episode_that_is_already_broken(tmp_path: Path) -> None:
    episode = _episode(tmp_path)
    with (episode / "final-assessment.json").open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(ContractError):
        run_negative_tests(episode, FakeArmEnv(), TOLERANCE, RUBRIC)


def test_negative_tests_refuse_an_episode_that_does_not_replay(tmp_path: Path) -> None:
    with pytest.raises(PositiveControlError, match="undamaged"):
        run_negative_tests(_episode(tmp_path), FakeArmEnv(drift=0.01), TOLERANCE, RUBRIC)


def test_a_case_rejected_for_another_reason_does_not_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name, damage, mode, _ = CASES[0]
    monkeypatch.setattr(negative_tests, "CASES", [(name, damage, mode, "a reason never given")])
    results = run_negative_tests(_episode(tmp_path), FakeArmEnv(), TOLERANCE, RUBRIC)
    assert [r.rejected for r in results] == [False]


def test_a_case_that_is_accepted_does_not_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = [("no_damage", negative_tests._no_damage, replay.INITIAL_STATE_ONLY, "anything")]
    monkeypatch.setattr(negative_tests, "CASES", cases)
    results = run_negative_tests(_episode(tmp_path), FakeArmEnv(), TOLERANCE, RUBRIC)
    assert [r.rejected for r in results] == [False]


def test_negative_tests_leave_the_episode_untouched(tmp_path: Path) -> None:
    episode = _episode(tmp_path)

    def digest() -> dict[str, str]:
        return {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(episode.iterdir())
        }

    before = digest()
    run_negative_tests(episode, FakeArmEnv(), TOLERANCE, RUBRIC)
    assert digest() == before


# ---------------------------------------------------------------------------- frozen file, commands


def test_frozen_tolerance_loads() -> None:
    tolerance, rubric = load_frozen(FROZEN)
    assert tolerance.max_state_deviation == 0.001
    assert tolerance.repeats == 3
    assert tolerance.max_episode_steps == 200
    assert tolerance.compare_streams == STREAMS
    assert rubric.rubric_version == "m0-place-1"
    assert tolerance.env_id == "PickCubeSO100-v1"
    assert tolerance.task_version == "m0-1"
    assert tolerance.protocol_version == "m0-protocol-2"


def _ledger(tmp_path: Path, *lines: dict[str, Any]) -> Path:
    path = tmp_path / "ledger.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return path


def _frozen_file(tmp_path: Path, name: str, extra: str = "") -> tuple[Path, str]:
    path = tmp_path / name
    path.write_text(json.dumps({"phase": "M0", "extra": extra}), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_real_frozen_file_is_current() -> None:
    require_frozen_file(FROZEN)


def test_an_unrecorded_file_is_refused(tmp_path: Path) -> None:
    copy = tmp_path / "copy.json"
    copy.write_text(FROZEN.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ReplayInvalidError, match="not the current"):
        require_frozen_file(copy)


def test_a_superseded_file_is_refused(tmp_path: Path) -> None:
    old, old_digest = _frozen_file(tmp_path, "old.json", "old")
    new, new_digest = _frozen_file(tmp_path, "new.json", "new")
    ledger = _ledger(
        tmp_path,
        {"et": "ET-M0-1", "event": "frozen", "note": f"sha256 {old_digest}"},
        {"et": "ET-M0-1", "event": "frozen", "note": f"sha256 {new_digest}"},
    )
    require_frozen_file(new, ledger)
    with pytest.raises(ReplayInvalidError, match="not the current"):
        require_frozen_file(old, ledger)


def test_every_exit_test_of_the_phase_must_record_the_file(tmp_path: Path) -> None:
    path, digest = _frozen_file(tmp_path, "file.json")
    ledger = _ledger(
        tmp_path,
        {"et": "ET-M0-1", "event": "frozen", "note": f"sha256 {digest}"},
        {"et": "ET-M0-2", "event": "frozen", "note": "sha256 another"},
    )
    with pytest.raises(ReplayInvalidError):
        require_frozen_file(path, ledger)


def test_a_line_that_is_not_a_frozen_event_counts_for_nothing(tmp_path: Path) -> None:
    path, digest = _frozen_file(tmp_path, "file.json")
    ledger = _ledger(tmp_path, {"et": "ET-M0-1", "event": "passed", "note": f"sha256 {digest}"})
    with pytest.raises(ReplayInvalidError):
        require_frozen_file(path, ledger)


def test_another_phases_frozen_event_counts_for_nothing(tmp_path: Path) -> None:
    path, digest = _frozen_file(tmp_path, "file.json")
    ledger = _ledger(tmp_path, {"et": "ET-M1-1", "event": "frozen", "note": f"sha256 {digest}"})
    with pytest.raises(ReplayInvalidError):
        require_frozen_file(path, ledger)


class FrozenTaskFake(FakeArmEnv):
    """The fake, declaring the frozen task's identity so the commands' frozen checks apply."""

    def configuration(self) -> dict[str, Any]:
        return {**super().configuration(), "env_id": "PickCubeSO100-v1"}


def _frozen_episode(tmp_path: Path, **changes: Any) -> Path:
    """A fake episode under the frozen rubric, so the commands' frozen checks apply to it."""
    tolerance, rubric = load_frozen(FROZEN)
    spec = _spec(
        rubric=rubric,
        episode_id="frozen-ep",
        task_id="PickCubeSO100-v1",
        task_version=tolerance.task_version,
        protocol_version=tolerance.protocol_version,
        **changes,
    )
    return record_episode(
        FrozenTaskFake(), plan_policy(scripted_plan(3)), spec, tmp_path / "frozen-ep"
    )


def _replay_args(episode: Path, repeats: str = "3") -> list[str]:
    return ["--episode", str(episode), "--tolerance-file", str(FROZEN), "--repeats", repeats]


def test_replay_command_refuses_a_repeat_count_other_than_the_frozen_one(tmp_path: Path) -> None:
    assert replay_main(_replay_args(tmp_path, "1")) == 2


def test_replay_command_refuses_a_tolerance_file_that_was_not_frozen(tmp_path: Path) -> None:
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    frozen["replay"]["repeats"] = 0
    forged = tmp_path / "forged.json"
    forged.write_text(json.dumps(frozen), encoding="utf-8")
    args = ["--episode", str(tmp_path), "--tolerance-file", str(forged), "--repeats", "0"]
    assert replay_main(args) == 2


def test_commands_report_not_run_when_there_is_no_adapter(tmp_path: Path) -> None:
    episode = _frozen_episode(tmp_path)
    assert replay_main(_replay_args(episode)) == 3
    assert negative_main(["--episode", str(episode), "--tolerance-file", str(FROZEN)]) == 3


def _use_fake(monkeypatch: pytest.MonkeyPatch, env: FakeArmEnv) -> None:
    factory = lambda _d, _m: env  # noqa: E731
    monkeypatch.setattr(replay, "env_for_manifest", factory)
    monkeypatch.setattr(negative_tests, "env_for_manifest", factory)


def test_replay_command_writes_its_report_once_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    episode = _frozen_episode(tmp_path)
    _use_fake(monkeypatch, FrozenTaskFake())
    out = tmp_path / "report.json"
    assert replay_main([*_replay_args(episode), "--out", str(out)]) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["claim_valid"] is True
    assert json.loads(capsys.readouterr().out) == written
    before = out.read_bytes()
    assert replay_main([*_replay_args(episode), "--out", str(out)]) == 2
    assert out.read_bytes() == before


def test_replay_command_exits_one_on_an_invalid_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode = _frozen_episode(tmp_path)
    _use_fake(monkeypatch, FrozenTaskFake(drift=0.01))
    assert replay_main(_replay_args(episode)) == 1


def test_replay_command_exits_two_on_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode = _frozen_episode(tmp_path)
    other = FrozenTaskFake()
    other.version = "fixture-2"
    _use_fake(monkeypatch, other)
    assert replay_main(_replay_args(episode)) == 2


def _negative_args(episode: Path) -> list[str]:
    return ["--episode", str(episode), "--tolerance-file", str(FROZEN)]


def test_negative_command_exits_zero_when_all_five_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    episode = _frozen_episode(tmp_path)
    _use_fake(monkeypatch, FrozenTaskFake())
    assert negative_main(_negative_args(episode)) == 0
    assert all(r["rejected"] for r in json.loads(capsys.readouterr().out))


def test_negative_command_exits_four_when_the_control_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode = _frozen_episode(tmp_path)
    _use_fake(monkeypatch, FrozenTaskFake(drift=0.01))
    assert negative_main(_negative_args(episode)) == 4


def test_negative_command_exits_one_when_a_case_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode = _frozen_episode(tmp_path)
    _use_fake(monkeypatch, FrozenTaskFake())
    cases = [("no_damage", negative_tests._no_damage, replay.INITIAL_STATE_ONLY, "anything")]
    monkeypatch.setattr(negative_tests, "CASES", cases)
    assert negative_main(_negative_args(episode)) == 1


def test_negative_command_exits_one_when_reasons_are_not_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode = _frozen_episode(tmp_path)
    _use_fake(monkeypatch, FrozenTaskFake())
    case = CASES[1]
    monkeypatch.setattr(negative_tests, "CASES", [case, case])
    assert negative_main(_negative_args(episode)) == 1


# ---------------------------------------------------------------------------- pinned gaps


class BadRepeatEnv(FakeArmEnv):
    """Reproduces, except on one repeat, where it applies ``tamper`` to every packet."""

    def __init__(self, repeat: int, tamper: Callable[[Packet], Packet]) -> None:
        super().__init__()
        self._bad_repeat = repeat
        self._tamper = tamper

    def _packet(self) -> Packet:
        packet = super()._packet()
        return self._tamper(packet) if self._restores - 1 == self._bad_repeat else packet


@pytest.mark.parametrize("repeat", [0, 1, 2])
def test_a_bad_deviation_on_any_repeat_is_caught(tmp_path: Path, repeat: int) -> None:
    env = BadRepeatEnv(repeat, lambda p: _offset(p, "joint_position", 0, 0.01))
    report = replay_episode(_episode(tmp_path), env, TOLERANCE, RUBRIC)
    assert not report.claim_valid
    assert f"repeat {repeat} deviated" in report.reason


@pytest.mark.parametrize("repeat", [0, 1, 2])
def test_a_bad_label_on_any_repeat_is_caught(tmp_path: Path, repeat: int) -> None:
    env = BadRepeatEnv(repeat, lambda p: _set(p, "object_grasped", 0, 1.0))
    report = replay_episode(_episode(tmp_path), env, TOLERANCE, RUBRIC)
    assert not report.claim_valid
    assert f"repeat {repeat} gave outcome" in report.reason


def _forge_observation(records: list[dict[str, Any]], step: int, stream: str, value: Any) -> None:
    for packet in records[step]["observations"]:
        if packet["stream"] == stream:
            packet["value"] = value


@pytest.mark.parametrize(
    ("step", "stream", "value"),
    [
        (7, "joint_position", [9.0, 9.0, 9.0, 9.0]),
        (1, "object_position", [9.0, 9.0, 9.0]),
        (20, "object_grasped", [1.0]),
    ],
)
def test_one_forged_later_observation_is_refused(
    tmp_path: Path, step: int, stream: str, value: list[float]
) -> None:
    episode = _episode(tmp_path)
    records = _records(episode)
    original = next(p for p in records[step]["observations"] if p["stream"] == stream)["value"]
    assert original != value
    _forge_observation(records, step, stream, value)
    _rewrite_records(episode, records)
    with pytest.raises(ReplayInvalidError, match="differ from the state"):
        replay_episode(episode, FakeArmEnv(), TOLERANCE, RUBRIC)


def test_a_timebase_stretched_from_a_later_step_is_refused(tmp_path: Path) -> None:
    episode = _episode(tmp_path)
    records = _records(episode)
    for record in records[5:]:
        record["t_ns"] += 7
        record["action"]["decision_t_ns"] += 7
        record["action"]["valid_until_t_ns"] += 7
        for packet in (*record["observations"], *record["next_observations"]):
            packet["capture_t_ns"] += 7
            packet["received_t_ns"] += 7
    records[4]["dt_ns"] += 7
    _rewrite_records(episode, records)
    with pytest.raises(ReplayInvalidError, match="timebase differs at step 4"):
        replay_episode(episode, FakeArmEnv(), TOLERANCE, RUBRIC)


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r["action"].update(valid_until_t_ns=r["action"]["valid_until_t_ns"] + 10**12),
        lambda r: r["next_observations"][0].update(capture_t_ns=r["t_ns"], received_t_ns=r["t_ns"]),
        lambda r: r["observations"][3].update(received_t_ns=r["t_ns"] + 10**12),
        lambda r: r["observations"][0].update(capture_t_ns=0, received_t_ns=r["t_ns"]),
    ],
)
def test_changed_action_or_packet_times_are_refused(
    tmp_path: Path, change: Callable[[dict[str, Any]], None]
) -> None:
    episode = _episode(tmp_path)
    records = _records(episode)
    change(records[6])
    _rewrite_records(episode, records)
    with pytest.raises((ReplayInvalidError, ContractError)):
        replay_episode(episode, FakeArmEnv(), TOLERANCE, RUBRIC)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda a: a.update(applied=[0.0, 0.0, 0.0, 0.0]), "has applied"),
        (lambda a: a.update(filtered=[0.0, 0.0, 0.0, 0.0]), "has filtered"),
        (lambda a: a.update(transmitted=[0.0, 0.0, 0.0, 0.0]), "has transmitted"),
    ],
)
def test_forged_action_stages_are_refused(
    tmp_path: Path, change: Callable[[dict[str, Any]], None], message: str
) -> None:
    episode = _episode(tmp_path)
    records = _records(episode)
    change(records[6]["action"])
    _rewrite_records(episode, records)
    with pytest.raises(ReplayInvalidError, match=message):
        replay_episode(episode, FakeArmEnv(), TOLERANCE, RUBRIC)


def test_a_changed_context_is_refused(tmp_path: Path) -> None:
    episode = _episode(tmp_path)
    records = _records(episode)
    records[6]["context"]["mode"] = "human_teleop"
    _rewrite_records(episode, records)
    with pytest.raises(ReplayInvalidError, match="record contexts"):
        replay_episode(episode, FakeArmEnv(), TOLERANCE, RUBRIC)


def test_an_adapter_that_under_counts_restores_is_caught(tmp_path: Path) -> None:
    class UnderCounting(FakeArmEnv):
        def restore_state(self, state: bytes) -> Packet:
            packet = super().restore_state(state)
            self._restores = min(self._restores, 1)
            return packet

    report = replay_episode(_episode(tmp_path), UnderCounting(), TOLERANCE, RUBRIC)
    assert not report.claim_valid
    assert "restored 1 times" in report.reason


def test_another_engine_with_the_same_version_is_refused(tmp_path: Path) -> None:
    other = FakeArmEnv()
    other.engine = "another_engine"
    with pytest.raises(ReplayInvalidError, match="engine and version"):
        replay_episode(_episode(tmp_path), other, TOLERANCE, RUBRIC)


def test_exactly_the_frozen_step_limit_passes(tmp_path: Path) -> None:
    episode = _episode(tmp_path)
    count = len(_records(episode))
    assert replay_episode(
        episode, FakeArmEnv(), replace(TOLERANCE, max_episode_steps=count), RUBRIC
    ).claim_valid
    with pytest.raises(ReplayInvalidError, match="frozen limit"):
        replay_episode(
            episode, FakeArmEnv(), replace(TOLERANCE, max_episode_steps=count - 1), RUBRIC
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("env_id", "PickCube-v1", "frozen task ids"),
        ("task_version", "other", "frozen task versions"),
        ("protocol_version", "other", "protocol versions"),
    ],
)
def test_an_episode_from_outside_the_frozen_task_is_refused(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    frozen, rubric = load_frozen(FROZEN)
    episode = _frozen_episode(tmp_path)
    assert replay_episode(episode, FrozenTaskFake(), frozen, rubric).claim_valid
    with pytest.raises(ReplayInvalidError, match=message):
        replay_episode(episode, FrozenTaskFake(), replace(frozen, **{field: value}), rubric)


@pytest.mark.parametrize(
    ("section", "field", "value", "message"),
    [
        ("task", "id", "other", "task ids"),
        ("configuration", "embodiment_id", "other", "embodiment ids"),
        ("task", "version", "other", "frozen task versions"),
        ("outcome", "protocol_version", "other", "protocol versions"),
    ],
)
def test_an_edited_identity_field_is_refused(
    tmp_path: Path, section: str, field: str, value: str, message: str
) -> None:
    frozen, rubric = load_frozen(FROZEN)
    episode = _frozen_episode(tmp_path)
    manifest = _manifest(episode)
    manifest[section][field] = value
    _write_manifest(episode, manifest)
    with pytest.raises(ReplayInvalidError, match=message):
        replay_episode(episode, FrozenTaskFake(), frozen, rubric)


def test_the_real_adapter_is_built_from_the_recording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, int]] = []

    class StubAdapter:
        engine = "stub_engine"

        def __init__(self, env_id: str, max_episode_steps: int) -> None:
            calls.append((env_id, max_episode_steps))

    validated: list[Path] = []

    class StubValidator:
        @staticmethod
        def validate_episode(path: Path) -> None:
            validated.append(path)

    monkeypatch.setattr(replay, "ManiSkillPickCube", StubAdapter)
    monkeypatch.setattr(replay, "validator", lambda: StubValidator)
    episode = tmp_path / "ep"
    episode.mkdir()
    (episode / "configuration.json").write_text(
        json.dumps({"env_id": "Recorded-v1", "max_episode_steps": 150}), encoding="utf-8"
    )
    manifest = {
        "simulator": {"engine": "stub_engine"},
        "configuration": {"embodiment_artifact": {"path": "configuration.json", "sha256": ""}},
    }
    assert isinstance(replay.env_for_manifest(episode, manifest), StubAdapter)
    assert calls == [("Recorded-v1", 150)]
    assert validated == [episode / "episode.json"]
    manifest["simulator"]["engine"] = "another"
    with pytest.raises(SimulatorUnavailableError, match="no adapter"):
        replay.env_for_manifest(episode, manifest)


def test_a_real_episode_is_validated_before_its_files_choose_a_simulator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Any] = []

    class StubAdapter:
        engine = "fake_fixture_no_simulator"

        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(replay, "ManiSkillPickCube", StubAdapter)
    episode = record_episode(
        FakeArmEnv(), plan_policy(scripted_plan(3)), _spec("edited"), tmp_path / "edited"
    )
    manifest = json.loads((episode / "episode.json").read_text(encoding="utf-8"))
    (episode / "configuration.json").write_text(
        json.dumps({"env_id": "this:Nope-v0", "max_episode_steps": 1}), encoding="utf-8"
    )
    with pytest.raises(ContractError):
        replay.env_for_manifest(episode, manifest)
    assert calls == []


def test_negative_command_exits_one_when_one_case_of_five_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode = _frozen_episode(tmp_path)
    _use_fake(monkeypatch, FrozenTaskFake())
    accepted = ("no_damage", negative_tests._no_damage, replay.INITIAL_STATE_ONLY, "anything")
    monkeypatch.setattr(negative_tests, "CASES", [*CASES[:4], accepted])
    assert negative_main(_negative_args(episode)) == 1


def test_negative_command_exits_two_on_a_broken_episode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode = _frozen_episode(tmp_path)
    with (episode / "final-assessment.json").open("ab") as stream:
        stream.write(b" ")
    _use_fake(monkeypatch, FrozenTaskFake())
    assert negative_main(_negative_args(episode)) == 2


def test_negative_command_refuses_a_loose_tolerance_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unfrozen file must not turn a simulator that does not reproduce into a pass."""
    episode = _frozen_episode(tmp_path)
    _use_fake(monkeypatch, FrozenTaskFake(drift=0.01))
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    frozen["replay"]["max_state_deviation"] = 1e9
    loose = tmp_path / "loose.json"
    loose.write_text(json.dumps(frozen), encoding="utf-8")
    args = ["--episode", str(episode), "--tolerance-file", str(loose)]
    assert negative_main(args) == 2


def test_the_replay_command_has_no_way_to_name_another_ledger(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        replay_main([*_replay_args(tmp_path), "--status-ledger", "x"])


@pytest.mark.parametrize(
    "tolerance_file",
    ["evals/M1-exit-tests.json", "evals/M0-protocol.md", "evals/no-such-file.json"],
)
def test_a_wrong_tolerance_file_is_a_refusal(tmp_path: Path, tolerance_file: str) -> None:
    args = ["--episode", str(tmp_path), "--tolerance-file", str(ROOT / tolerance_file)]
    assert replay_main([*args, "--repeats", "3"]) == 2
    assert negative_main(args) == 2


def test_refusals_exit_two_not_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = tmp_path / "missing"
    assert replay_main(_replay_args(missing)) == 2
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "episode.json").write_text("not json", encoding="utf-8")
    assert replay_main(_replay_args(bad)) == 2
    episode = _frozen_episode(tmp_path)

    class Crashes(FrozenTaskFake):
        def step(self, action: list[float]) -> Packet:
            raise RuntimeError("the simulator crashed")

    _use_fake(monkeypatch, Crashes())
    assert replay_main(_replay_args(episode)) == 2


def test_an_out_path_in_a_missing_directory_is_refused_before_replaying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode = _frozen_episode(tmp_path)
    env = FrozenTaskFake()
    _use_fake(monkeypatch, env)
    out = tmp_path / "missing" / "report.json"
    assert replay_main([*_replay_args(episode), "--out", str(out)]) == 2
    assert env.state_restores == 0


def test_a_blow_up_report_is_still_strict_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode = _frozen_episode(tmp_path)

    class BlowsUp(FrozenTaskFake):
        def step(self, action: list[float]) -> Packet:
            return _set(super().step(action), "joint_position", 0, math.nan)

    _use_fake(monkeypatch, BlowsUp())
    out = tmp_path / "report.json"
    assert replay_main([*_replay_args(episode), "--out", str(out)]) == 1
    text = out.read_text(encoding="utf-8")
    assert "Infinity" not in text.replace('"inf"', "")

    def reject(value: str) -> None:
        raise AssertionError(value)

    report = json.loads(text, parse_constant=reject)
    assert report["repeats"][0]["max_deviation"] == "inf"


@pytest.mark.parametrize("module", ["replay", "negative_tests"])
def test_the_modules_run_as_commands_and_report_not_run(tmp_path: Path, module: str) -> None:
    episode = _frozen_episode(tmp_path)
    args = [sys.executable, "-m", f"vishwaroop.sim.{module}", "--episode", str(episode)]
    args += ["--tolerance-file", str(FROZEN)]
    if module == "replay":
        args += ["--repeats", "3"]
    done = subprocess.run(
        args,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 3, done.stdout + done.stderr
    assert "NOT RUN" in done.stdout


def test_contract_judge_does_not_decide_on_an_invalid_episode(tmp_path: Path) -> None:
    episode = _episode(tmp_path)
    judge = contract_judge(RUBRIC)
    assert judge.judge(str(episode))[0] is True
    with (episode / "final-assessment.json").open("ab") as stream:
        stream.write(b" ")
    verdict, note = judge.judge(str(episode))
    assert verdict is None
    assert "checksum mismatch" in note


@pytest.mark.parametrize("data", [None, {}, {"transitions_artifact": None}])
def test_judge_does_not_crash_on_a_broken_manifest(tmp_path: Path, data: Any) -> None:
    (tmp_path / "episode.json").write_text(json.dumps({"data": data}), encoding="utf-8")
    verdict, note = PickPlaceJudge(RUBRIC).judge(str(tmp_path))
    assert verdict is None
    assert note.startswith("insufficient_evidence")


def test_an_infinite_stream_is_recorded_as_invalid(tmp_path: Path) -> None:
    class InfEnv(FakeArmEnv):
        def _packet(self) -> Packet:
            return _set(super()._packet(), "object_position", 0, math.inf)

    episode = record_episode(InfEnv(), plan_policy(scripted_plan(3)), _spec(), tmp_path / "ep")
    assert validate_episode(episode / "episode.json")["status"] == "contract_valid"
    assert _manifest(episode)["outcome"]["success"] is None


# ---------------------------------------------------------------------------- the frozen split rule


def _family_episode(tmp_path: Path, name: str, family: str, partition: str, block: int) -> Path:
    spec = _spec(
        episode_id=name,
        seed=block * 1000,
        policy_family=family,
        partition=partition,
        scene_group_id=f"m0-seed-block-{block}",
        session_group_id=f"session-{name}",
    )
    plan = scripted_plan(block * 1000)
    return record_episode(FakeArmEnv(), plan_policy(plan), spec, tmp_path / name) / "episode.json"


def test_a_set_that_follows_the_protocol_passes_the_split_audit(tmp_path: Path) -> None:
    episodes = [
        _family_episode(tmp_path, "a", "m0-scripted-nominal", "train", 0),
        _family_episode(tmp_path, "b", "m0-scripted-perturbed", "dev", 8),
    ]
    assert audit_splits.audit(episodes)["episodes"] == 2


def test_a_family_across_partitions_fails_the_split_audit(tmp_path: Path) -> None:
    episodes = [
        _family_episode(tmp_path, "a", "m0-scripted-nominal", "train", 0),
        _family_episode(tmp_path, "b", "m0-scripted-nominal", "dev", 8),
    ]
    with pytest.raises(ContractError):
        audit_splits.audit(episodes)


# ---------------------------------------------------------------------------- environment


def test_missing_simulator_is_a_clear_error() -> None:
    from vishwaroop.sim.env import ManiSkillPickCube

    try:
        import mani_skill  # noqa: F401
    except ImportError:
        with pytest.raises(SimulatorUnavailableError, match="robotics environment missing"):
            ManiSkillPickCube()
    else:
        pytest.skip("the simulator is installed here")


@pytest.mark.parametrize("package", ["outcome", "sim"])
def test_simulator_code_parses_on_python_3_11(package: str) -> None:
    """The robotics environment is proposed on Python 3.11, and CI only runs 3.12 and 3.13."""
    for path in (ROOT / "src" / "vishwaroop" / package).glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 11))
