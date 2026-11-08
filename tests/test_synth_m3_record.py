"""The M3 recorder and the reproducibility gate end to end, on FABRICATED rendering environments
(tests/fake_m3.py, tests/fake_scene.py). No simulator ran; nothing here is evidence about one."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from fake_m3 import FakeM3Env  # noqa: E402
from vishwaroop.sim.baseline import VARIANTS  # noqa: E402
from vishwaroop.synth import et_m3_6_record as rec  # noqa: E402
from vishwaroop.synth.m3_gate import gate_tolerance, run_gate  # noqa: E402
from vishwaroop.synth.m3_record import (  # noqa: E402
    EVAL_FAMILY,
    LATERAL_FAMILY,
    NOMINAL_FAMILY,
    SNAPSHOTS,
    SceneMismatchError,
    Task,
    record,
)
from vishwaroop.synth.operators import lateral_miss  # noqa: E402
from vishwaroop.synth.protocol import PROTOCOL_VERSION, ProtocolRefusalError  # noqa: E402
from vishwaroop.synth.snapshot import read_snapshot  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
M0 = ROOT / "evals" / "M0-exit-tests.json"
TASK = Task.from_frozen(json.loads(M0.read_text()))
TOLERANCE, RUBRIC = gate_tolerance(M0)


def _record(env: object, tmp_path: Path, family: str = EVAL_FAMILY, seed: int = 16000) -> object:
    settings = VARIANTS["missed-grasp"] if family == EVAL_FAMILY else VARIANTS["nominal"]
    return record(env, family, seed, settings, "run-x", tmp_path, TASK, RUBRIC, "fixture")  # type: ignore[arg-type]


def test_a_recording_is_snapshotted_first_and_starts_from_the_snapshot(tmp_path: Path) -> None:
    recorded = _record(FakeM3Env(), tmp_path)
    snapshot = read_snapshot(tmp_path / SNAPSHOTS / "seed-016000")
    assert snapshot.manifest["scene_group_id"] == "m3-seed-block-16"
    assert recorded.snapshot_state_sha256 == snapshot.manifest["initial_state"]["sha256"]
    manifest = json.loads((recorded.path / "episode.json").read_text())
    assert manifest["episode_id"] == "m3-eval-missed-grasp-seed-016000"
    assert manifest["split"]["partition"] == "dev"
    assert manifest["split"]["scene_group_id"] == "m3-seed-block-16"
    assert manifest["outcome"]["protocol_version"] == PROTOCOL_VERSION
    assert manifest["policy"]["family_id"] == EVAL_FAMILY
    assert manifest["environment_kind"] == "physics_sim"
    assert "planning_failed" in manifest["notes"]  # the fake cube is out of reach: kept anyway
    assert recorded.label == "never_lifted" and recorded.planning_error is not None


def test_a_second_episode_on_a_scene_reuses_and_checks_its_snapshot(tmp_path: Path) -> None:
    env = FakeM3Env()
    first = record(
        env, LATERAL_FAMILY, 11000, lateral_miss(11000, 1), "r", tmp_path, TASK, RUBRIC, "op"
    )
    second = _record(env, tmp_path, NOMINAL_FAMILY, 11000)
    assert first.snapshot_state_sha256 == second.snapshot_state_sha256
    assert second.render_matches_snapshot


def test_a_scene_that_changed_since_its_snapshot_is_refused(tmp_path: Path) -> None:
    _record(FakeM3Env(), tmp_path, NOMINAL_FAMILY, 11000)

    class Moved(FakeM3Env):
        def reset(self, seed: int):  # type: ignore[no-untyped-def]
            packet = super().reset(seed)
            self._target = [-0.1, -0.2, 0.05]
            return {**packet, "target_position": list(self._target)}

    with pytest.raises(SceneMismatchError, match="differs from its snapshot"):
        _record(Moved(), tmp_path, NOMINAL_FAMILY, 11000)


@pytest.mark.parametrize("seed", [10265, 10001, 18000, 16000, 8000])
def test_refused_seeds_are_never_simulated(tmp_path: Path, seed: int) -> None:
    class Untouchable(FakeM3Env):
        def reset(self, seed: int):  # type: ignore[no-untyped-def]
            raise AssertionError("simulated a refused seed")

    with pytest.raises(ProtocolRefusalError):
        _record(Untouchable(), tmp_path, NOMINAL_FAMILY, seed)
    assert not (tmp_path / SNAPSHOTS).exists()


def test_the_gate_passes_a_reproducible_episode(tmp_path: Path) -> None:
    env = FakeM3Env(lift=True)
    recorded = _record(env, tmp_path)
    result = run_gate(recorded.path, env, TOLERANCE, RUBRIC)
    assert recorded.label == "outside_target"
    assert result.passed and result.labels == ["outside_target"] * 3
    assert result.max_deviations == [0.0, 0.0, 0.0]


def test_the_gate_rejects_a_replay_past_the_tolerance(tmp_path: Path) -> None:
    env = FakeM3Env(drift=0.0006)  # 0.0006, 0.0012, 0.0018 rad on repeats 1 to 3
    recorded = _record(env, tmp_path)
    result = run_gate(recorded.path, env, TOLERANCE, RUBRIC)
    assert not result.passed and "repeat 1 deviated" in result.reason


def test_the_gate_rejects_a_label_that_changes_between_repeats(tmp_path: Path) -> None:
    # restores: 1 snapshot, 2 recording, 3 to 5 the gate's repeats; the second repeat flips
    env = FakeM3Env(lift=True, flip_on_restore=4)
    recorded = _record(env, tmp_path)
    result = run_gate(recorded.path, env, TOLERANCE, RUBRIC)
    assert result.labels == ["outside_target", "still_grasped", "outside_target"]
    assert result.max_deviations == [0.0, 0.0, 0.0]
    assert not result.passed and "still_grasped" in result.reason


def test_an_undecided_episode_repeated_identically_passes(tmp_path: Path) -> None:
    env = FakeM3Env(grasp_stream=False)  # the rubric cannot decide
    recorded = _record(env, tmp_path)
    result = run_gate(recorded.path, env, TOLERANCE, RUBRIC)
    assert recorded.label == "insufficient_evidence"
    assert result.undecided and result.passed  # sim.replay's reason text is still the one matched


def test_the_eval_sequence_records_and_gates_with_the_real_recorder(tmp_path: Path) -> None:
    env = FakeM3Env(lift=True)
    sequence = rec.Recording(
        "eval", range(16000, 16003), rec.eval_choice, lambda kept: len(kept) >= 2
    )
    progress = tmp_path / "p.jsonl"
    outcome = rec.run_sequence(sequence, env, tmp_path, "run", TASK, RUBRIC, TOLERANCE, progress)
    assert outcome["complete"] and [line["seed"] for line in outcome["kept"]] == [16000, 16001]
    assert not (tmp_path / "m3-eval-missed-grasp-seed-016002").exists()


def test_an_episode_recorded_before_a_stop_is_gated_not_recorded_again(tmp_path: Path) -> None:
    env = FakeM3Env(lift=True)
    sequence = rec.Recording("eval", [16000], rec.eval_choice, lambda kept: len(kept) >= 1)
    _, settings, info = rec.eval_choice(16000, [])
    note = rec._settings_note(settings, info)
    record(env, EVAL_FAMILY, 16000, settings, "run", tmp_path, TASK, RUBRIC, note)

    def no_recording(*_: object) -> None:
        raise AssertionError("recorded again")

    outcome = rec.run_sequence(
        sequence, env, tmp_path, "run", TASK, RUBRIC, TOLERANCE, tmp_path / "p.jsonl", no_recording
    )
    assert outcome["complete"] and outcome["kept"][0]["recorded"]["steps"] == 15
