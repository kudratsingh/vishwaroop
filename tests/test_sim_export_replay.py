"""Export, replay and negative tests against a FABRICATED fake environment.

These test the logic only. No simulator runs here, so no result here is evidence for any exit test.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from fake_env import FakeArmEnv, plan_policy, scripted_plan
from validate import ContractError, validate_episode
from vishwaroop.outcome.pickplace import PickPlaceJudge, PlaceRubric
from vishwaroop.sim.env import SimEnv, SimulatorUnavailableError
from vishwaroop.sim.export import EpisodeSpec, record_episode
from vishwaroop.sim.negative_tests import CASES, run_negative_tests
from vishwaroop.sim.negative_tests import main as negative_main
from vishwaroop.sim.replay import (
    FORCED_INTERMEDIATE_STATES,
    ReplayInvalidError,
    ReplayTolerance,
    load_frozen,
    replay_episode,
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
TOLERANCE = ReplayTolerance(["joint_position", "object_position"], 0.001, 3)


def _spec(episode_id: str = "ep-1", seed: int = 3) -> EpisodeSpec:
    return EpisodeSpec(
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


def _episode(tmp_path: Path, **plan_options: object) -> Path:
    plan = scripted_plan(3, **plan_options)  # type: ignore[arg-type]
    return record_episode(FakeArmEnv(), plan_policy(plan), _spec(), tmp_path / "ep-1")


def test_fake_env_implements_the_interface() -> None:
    assert isinstance(FakeArmEnv(), SimEnv)


def test_exported_episode_is_contract_valid(tmp_path: Path) -> None:
    episode = _episode(tmp_path)
    assert validate_episode(episode / "episode.json")["status"] == "contract_valid"
    manifest = json.loads((episode / "episode.json").read_text(encoding="utf-8"))
    assert manifest["producer"] == "vishwaroop"
    assert manifest["environment_kind"] == "physics_sim"
    assert manifest["simulator"]["restore_mode"] == "initial_state_only"
    assert manifest["outcome"]["assessment_method"] == "independent_sim_state"
    assert manifest["outcome"]["training_reward_artifact"] is None


def test_unreported_action_stages_stay_null(tmp_path: Path) -> None:
    episode = _episode(tmp_path)
    record = json.loads((episode / "transitions.jsonl").read_text(encoding="utf-8").splitlines()[0])
    action = record["action"]
    assert action["requested"] is not None
    for key in ("filtered", "transmitted", "applied", "sent_t_ns", "applied_t_ns"):
        assert action[key] is None


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
    spec = EpisodeSpec(**{**_spec().__dict__, "max_steps": 5})
    episode = record_episode(FakeArmEnv(), lambda _p, _s: [0.0] * 4, spec, tmp_path / "short")
    manifest = json.loads((episode / "episode.json").read_text(encoding="utf-8"))
    assert manifest["data"]["record_count"] == 5
    assert manifest["outcome"]["truncated"] is True
    assert manifest["outcome"]["terminated"] is False
    assert manifest["outcome"]["success"] is None


@pytest.mark.parametrize(
    ("options", "success", "label"),
    [
        ({}, True, "success"),
        ({"release": False}, False, "still_grasped"),
        ({"target_miss": 0.05}, False, "outside_target"),
    ],
)
def test_recorded_outcome_matches_the_judge_on_the_exported_files(
    tmp_path: Path, options: dict[str, object], success: bool, label: str
) -> None:
    episode = _episode(tmp_path, **options)
    manifest = json.loads((episode / "episode.json").read_text(encoding="utf-8"))
    assert manifest["outcome"]["success"] is success
    assert manifest["outcome"]["reason"].startswith(label)
    verdict, note = PickPlaceJudge(RUBRIC).judge(str(episode))
    assert verdict is success
    assert note.startswith(label)


def test_replay_of_a_reproducing_simulator_holds(tmp_path: Path) -> None:
    report = replay_episode(_episode(tmp_path), FakeArmEnv(), TOLERANCE, RUBRIC)
    assert report.claim_valid, report.reason
    assert report.recorded_label == "success"
    assert [r.repeat for r in report.repeats] == [0, 1, 2]
    assert all(r.max_deviation == 0.0 and r.outcome_label == "success" for r in report.repeats)


def test_replay_fails_when_deviation_exceeds_the_tolerance(tmp_path: Path) -> None:
    report = replay_episode(_episode(tmp_path), FakeArmEnv(drift=0.01), TOLERANCE, RUBRIC)
    assert not report.claim_valid
    assert "deviated" in report.reason


def test_replay_passes_at_the_tolerance_and_fails_just_past_it(tmp_path: Path) -> None:
    episode = _episode(tmp_path)
    worst = max(
        r.max_deviation
        for r in replay_episode(episode, FakeArmEnv(drift=0.0002), TOLERANCE, RUBRIC).repeats
    )
    at_limit = ReplayTolerance(TOLERANCE.compare_streams, worst, 3)
    assert replay_episode(episode, FakeArmEnv(drift=0.0002), at_limit, RUBRIC).claim_valid
    under = ReplayTolerance(TOLERANCE.compare_streams, worst * 0.999, 3)
    assert not replay_episode(episode, FakeArmEnv(drift=0.0002), under, RUBRIC).claim_valid


def test_replay_notices_an_environment_that_forces_state_during_steps(tmp_path: Path) -> None:
    report = replay_episode(_episode(tmp_path), FakeArmEnv(forces_state=True), TOLERANCE, RUBRIC)
    assert not report.claim_valid
    assert "restored" in report.reason


def test_replay_refuses_a_different_simulator_version(tmp_path: Path) -> None:
    other = FakeArmEnv()
    other.version = "fixture-2"
    with pytest.raises(ReplayInvalidError, match="recorded on"):
        replay_episode(_episode(tmp_path), other, TOLERANCE, RUBRIC)


def test_forcing_mode_never_supports_the_claim(tmp_path: Path) -> None:
    report = replay_episode(
        _episode(tmp_path), FakeArmEnv(), TOLERANCE, RUBRIC, mode=FORCED_INTERMEDIATE_STATES
    )
    assert not report.claim_valid
    assert report.repeats == []


def test_all_five_negative_tests_reject_for_distinct_reasons(tmp_path: Path) -> None:
    episode = _episode(tmp_path)
    results = run_negative_tests(episode, FakeArmEnv(), TOLERANCE, RUBRIC)
    assert [r.name for r in results] == [name for name, _, _ in CASES]
    assert len(results) == 5
    assert all(r.rejected for r in results), results
    assert len({r.reason for r in results}) == 5
    reasons = {r.name: r.reason for r in results}
    assert "action labels differ" in reasons["corrupted_action_semantics"]
    assert "checksum mismatch" in reasons["broken_artifact_hash"]
    assert "missing" in reasons["missing_asset"]
    assert "decision" in reasons["wrong_timebase"]
    assert "forces state" in reasons["intermediate_state_forcing"]


def test_negative_tests_leave_the_episode_untouched(tmp_path: Path) -> None:
    episode = _episode(tmp_path)

    def digest() -> dict[str, str]:
        return {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(episode.iterdir())
        }

    before = digest()
    run_negative_tests(episode, FakeArmEnv(), TOLERANCE, RUBRIC)
    assert digest() == before


def test_frozen_tolerance_loads() -> None:
    tolerance, rubric = load_frozen(FROZEN)
    assert tolerance.max_state_deviation == 0.001
    assert tolerance.repeats == 3
    assert tolerance.compare_streams == ["joint_position", "object_position"]
    assert rubric.rubric_version == "m0-place-1"


def test_replay_command_refuses_a_repeat_count_other_than_the_frozen_one(tmp_path: Path) -> None:
    code = replay_main(
        ["--episode", str(tmp_path), "--tolerance-file", str(FROZEN), "--repeats", "1"]
    )
    assert code == 2


def test_commands_report_not_run_when_there_is_no_adapter(tmp_path: Path) -> None:
    episode = _episode(tmp_path)
    args = ["--episode", str(episode), "--tolerance-file", str(FROZEN)]
    assert replay_main([*args, "--repeats", "3"]) == 3
    assert negative_main(args) == 3


def test_missing_simulator_is_a_clear_error() -> None:
    from vishwaroop.sim.env import ManiSkillPickCube

    try:
        import mani_skill  # noqa: F401
    except ImportError:
        with pytest.raises(SimulatorUnavailableError, match="robotics environment missing"):
            ManiSkillPickCube()
    else:
        pytest.skip("the simulator is installed here")
