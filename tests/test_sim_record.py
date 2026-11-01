"""The recording commands and the inspection facts, with no simulator. Fixtures are FABRICATED."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from fake_env import FakeArmEnv, plan_policy, scripted_plan
from vishwaroop.outcome.pickplace import PlaceRubric
from vishwaroop.sim import inspect_episode, record
from vishwaroop.sim.baseline import VARIANTS
from vishwaroop.sim.env import Packet
from vishwaroop.sim.export import EpisodeSpec, record_episode
from vishwaroop.sim.inspect_episode import frame_steps, raw_facts
from vishwaroop.sim.record import episode_spec, partition_for_seed
from vishwaroop.sim.replay import load_frozen

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "evals" / "M0-exit-tests.json"
RUBRIC = PlaceRubric("test", 0.015625, 0.0125, 0.005, 0.02, 0.001, 10)


def _fixture_spec(episode_id: str, seed: int = 3) -> EpisodeSpec:
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


class _OrderLoggingEnv(FakeArmEnv):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def reset(self, seed: int) -> Packet:
        self.calls.append("reset")
        return super().reset(seed)

    def save_state(self) -> bytes:
        self.calls.append("save")
        return super().save_state()

    def restore_state(self, state: bytes) -> Packet:
        self.calls.append("restore")
        return super().restore_state(state)

    def step(self, action: list[float]) -> Packet:
        self.calls.append("step")
        return super().step(action)


def test_a_recording_runs_from_the_saved_state_as_a_replay_does(tmp_path: Path) -> None:
    env = _OrderLoggingEnv()
    record_episode(env, plan_policy(scripted_plan(3)), _fixture_spec("order"), tmp_path / "order")
    assert env.calls[:4] == ["reset", "save", "restore", "step"]
    assert env.calls.count("restore") == 1
    assert env.calls.count("reset") == 1


@pytest.mark.parametrize(
    ("seed", "partition"),
    [(0, "train"), (7999, "train"), (8000, "dev"), (9999, "dev")],
)
def test_partition_follows_the_frozen_seed_blocks(seed: int, partition: str) -> None:
    assert partition_for_seed(seed) == partition


@pytest.mark.parametrize("seed", [-1, 10000, 123456])
def test_seeds_outside_the_frozen_blocks_are_refused(seed: int) -> None:
    with pytest.raises(ValueError, match="outside"):
        partition_for_seed(seed)


def _frozen() -> tuple[dict[str, Any], PlaceRubric]:
    return json.loads(FROZEN.read_text(encoding="utf-8")), load_frozen(FROZEN)[1]


def test_the_spec_takes_its_groups_and_task_from_the_frozen_protocol() -> None:
    frozen, rubric = _frozen()
    spec = episode_spec(8123, "no-release", "run-7", frozen, rubric)
    assert spec.episode_id == "m0-scripted-no-release-seed-008123"
    assert spec.policy_family == "m0-scripted-no-release"
    assert spec.partition == "dev"
    assert spec.purpose == "evaluation"
    assert spec.scene_group_id == "m0-seed-block-8"
    assert spec.session_group_id == "run-7"
    assert spec.task_id == frozen["task"]["env_id"]
    assert spec.task_version == frozen["task"]["version"]
    assert spec.protocol_version == frozen["protocol_version"]
    assert spec.max_steps == frozen["task"]["max_episode_steps"]
    assert spec.rubric == rubric
    assert "not the owner's SO-101" in spec.notes


def test_train_seeds_are_training_episodes() -> None:
    frozen, rubric = _frozen()
    assert episode_spec(12, "nominal", "r", frozen, rubric).purpose == "training"


def test_unknown_variant_is_refused() -> None:
    frozen, rubric = _frozen()
    with pytest.raises(ValueError, match="unknown variant"):
        episode_spec(12, "lucky", "r", frozen, rubric)


def test_each_failure_family_differs_from_nominal() -> None:
    nominal = VARIANTS["nominal"]
    assert len(VARIANTS) >= 4
    for name, settings in VARIANTS.items():
        assert (settings == nominal) == (name == "nominal")


def test_record_refuses_a_file_that_is_not_the_frozen_one(tmp_path: Path) -> None:
    edited = tmp_path / "M0-exit-tests.json"
    edited.write_text(FROZEN.read_text(encoding="utf-8") + " ", encoding="utf-8")
    code = record.main(
        [
            "--seed", "12", "--variant", "nominal", "--run-id", "r",
            "--tolerance-file", str(edited), "--out", str(tmp_path / "out"),
        ]
    )  # fmt: skip
    assert code == 2
    assert not (tmp_path / "out").exists()


def test_record_says_not_run_without_the_simulator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("jsonschema")

    def unavailable() -> None:
        raise record.SimulatorUnavailableError("no stack")

    monkeypatch.setattr(record, "ManiSkillPickCube", unavailable)
    code = record.main(
        [
            "--seed", "12", "--variant", "nominal", "--run-id", "r",
            "--tolerance-file", str(FROZEN), "--out", str(tmp_path / "out"),
        ]
    )  # fmt: skip
    assert code == 3


def _records(tmp_path: Path, **plan: Any) -> tuple[Path, list[dict[str, Any]]]:
    target = tmp_path / "episode"
    record_episode(FakeArmEnv(), plan_policy(scripted_plan(3, **plan)), _fixture_spec("e"), target)
    lines = (target / "transitions.jsonl").read_text(encoding="utf-8").splitlines()
    return target, [json.loads(line) for line in lines]


def test_raw_facts_report_a_fixture_success(tmp_path: Path) -> None:
    _, records = _records(tmp_path)
    facts = raw_facts(records)
    assert facts["records"] == len(records)
    assert facts["cube_peak_height_m"] > 0.0325
    assert facts["grasped_at_end"] is False
    assert facts["end_distance_to_target_xy_m"] <= 0.015625
    assert facts["largest_step_motion_in_last_10_steps_m"] == 0.0


def test_raw_facts_show_a_fixture_miss(tmp_path: Path) -> None:
    _, records = _records(tmp_path, target_miss=0.05)
    assert raw_facts(records)["end_distance_to_target_xy_m"] == pytest.approx(0.05, abs=1e-6)


def test_raw_facts_show_a_grasp_that_was_never_released(tmp_path: Path) -> None:
    _, records = _records(tmp_path, release=False)
    facts = raw_facts(records)
    assert facts["grasped_at_end"] is True
    assert facts["samples_grasped"] > 0


def test_raw_facts_refuse_an_empty_episode() -> None:
    with pytest.raises(ValueError, match="no records"):
        raw_facts([])


def test_frames_include_the_first_and_last_state() -> None:
    steps = frame_steps(185)
    assert steps[0] == 0
    assert steps[-1] == 185
    assert steps == sorted(set(steps))


@pytest.mark.parametrize(("count", "frames"), [(0, 12), (10, 1)])
def test_frame_steps_refuses_nonsense(count: int, frames: int) -> None:
    with pytest.raises(ValueError):
        frame_steps(count, frames)


def test_inspection_writes_once_and_uses_no_outcome_code(tmp_path: Path) -> None:
    episode, _ = _records(tmp_path)
    out = tmp_path / "inspected"
    assert inspect_episode.main(["--episode", str(episode), "--out", str(out)]) == 0
    report = json.loads((out / "inspection.json").read_text(encoding="utf-8"))
    assert report["episode_id"] == "e"
    assert math.isfinite(report["raw_facts"]["end_distance_to_target_xy_m"])
    assert inspect_episode.main(["--episode", str(episode), "--out", str(out)]) == 2
    source = Path(inspect_episode.__file__).read_text(encoding="utf-8")
    assert "outcome.pickplace" not in source and "assess" not in source
