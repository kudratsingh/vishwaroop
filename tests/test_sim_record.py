"""The record, inspect and sensitivity commands, with no simulator. Fixtures are FABRICATED."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from fake_env import FakeArmEnv, plan_policy, scripted_plan
from vishwaroop.outcome.pickplace import PlaceRubric
from vishwaroop.sim import inspect_episode, record, sensitivity
from vishwaroop.sim.env import ManiSkillPickCube, Packet
from vishwaroop.sim.export import EpisodeSpec, record_episode
from vishwaroop.sim.inspect_episode import frame_steps, raw_facts
from vishwaroop.sim.record import episode_spec, parse_episode, partition_for_seed
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


def test_the_policy_sees_only_input_streams(tmp_path: Path) -> None:
    env = FakeArmEnv()
    seen: set[str] = set()
    inner = plan_policy(scripted_plan(3))

    def spy(packet: Packet, step: int) -> list[float] | None:
        seen.update(packet)
        return inner(packet, step)

    record_episode(env, spy, _fixture_spec("spy"), tmp_path / "spy")
    assert seen == {stream.name for stream in env.stream_specs if stream.role == "input"}


@pytest.mark.parametrize(
    ("note", "expected"),
    [(None, False), ("planning_failed: no joint solution", True)],
)
def test_a_closing_note_reaches_the_manifest(
    tmp_path: Path, note: str | None, expected: bool
) -> None:
    path = record_episode(
        FakeArmEnv(),
        plan_policy(scripted_plan(3)),
        _fixture_spec("n"),
        tmp_path / "n",
        lambda: note,
    )
    manifest = json.loads((path / "episode.json").read_text(encoding="utf-8"))
    assert ("planning_failed" in manifest["notes"]) is expected
    assert manifest["notes"].startswith("FABRICATED")


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
    spec = episode_spec(1123, "no-release", "run-7", frozen, rubric, "Code commit abc.")
    assert spec.episode_id == "m0-scripted-no-release-seed-001123"
    assert spec.policy_family == "m0-scripted-no-release"
    assert spec.partition == "train"
    assert spec.purpose == "training"
    assert spec.scene_group_id == "m0-seed-block-1"
    assert spec.session_group_id == "run-7"
    assert spec.task_id == frozen["task"]["env_id"]
    assert spec.task_version == frozen["task"]["version"]
    assert spec.protocol_version == frozen["protocol_version"]
    assert spec.max_steps == frozen["task"]["max_episode_steps"]
    assert spec.rubric == rubric
    assert "not the owner's SO-101" in spec.notes
    assert spec.notes.endswith("Code commit abc.")


@pytest.mark.parametrize("variant", sorted(record.FAMILY_PARTITION))
def test_a_family_cannot_cross_into_the_dev_holdout(variant: str) -> None:
    frozen, rubric = _frozen()
    with pytest.raises(ValueError, match="wholly in one partition"):
        episode_spec(8123, variant, "r", frozen, rubric)


def test_unknown_variant_is_refused() -> None:
    frozen, rubric = _frozen()
    with pytest.raises(ValueError, match="unknown variant"):
        episode_spec(12, "lucky", "r", frozen, rubric)


@pytest.mark.parametrize("text", ["12", "12:lucky", "x:nominal", ":nominal"])
def test_bad_episode_requests_are_refused(text: str) -> None:
    with pytest.raises(ValueError):
        parse_episode(text)


def test_good_episode_requests_parse() -> None:
    assert parse_episode("12:wrong-place") == (12, "wrong-place")


@pytest.mark.parametrize("env_id", ["this:Nope-v0", "PickCube-v1", ""])
def test_the_adapter_refuses_an_unknown_environment_before_importing_anything(env_id: str) -> None:
    with pytest.raises(ValueError, match="unknown environment id"):
        ManiSkillPickCube(env_id=env_id)


class _FakeStack(FakeArmEnv):
    """A FABRICATED stand-in for the adapter, which the command builds by name."""

    def __init__(self, env_id: str, max_episode_steps: int) -> None:
        super().__init__()
        self.built_from = (env_id, max_episode_steps)


class _Policy:
    planning_error: str | None = None

    def __init__(self, _settings: Any = None) -> None:
        self._inner = plan_policy(scripted_plan(3))

    def __call__(self, packet: Packet, step: int) -> list[float] | None:
        return self._inner(packet, step)


class _UnplannedPolicy(_Policy):
    planning_error = "no joint solution for tool point"


def _repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, policy: type = _Policy) -> Path:
    (tmp_path / "ledgers").mkdir()
    (tmp_path / "runs").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "stack-lock.resolved.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(record, "ManiSkillPickCube", _FakeStack)
    monkeypatch.setattr(record, "ScriptedPickPlace", policy)
    return tmp_path


def _record_args(out: Path, *episodes: str) -> list[str]:
    pairs = [item for episode in episodes for item in ("--episode", episode)]
    return [*pairs, "--tolerance-file", str(FROZEN), "--out", str(out)]


def _ledger(repo: Path) -> list[dict[str, Any]]:
    lines = (repo / "ledgers" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_a_recording_is_one_ledgered_run_and_names_its_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch)
    out = repo / "episodes"
    assert record.main(_record_args(out, "12:nominal", "13:wrong-place")) == 0
    ledger = _ledger(repo)
    assert [line["status"] for line in ledger] == ["started", "completed"]
    assert ledger[0]["run_id"] == ledger[1]["run_id"]
    run_id = ledger[0]["run_id"]
    assert not Path(ledger[0]["run_dir"]).is_absolute()
    assert (repo / "runs" / run_id / "git.json").is_file()
    assert json.loads((repo / "runs" / run_id / "seeds.json").read_text()) == {
        "12:nominal": 12,
        "13:wrong-place": 13,
    }
    for name in ("m0-scripted-nominal-seed-000012", "m0-scripted-wrong-place-seed-000013"):
        manifest = json.loads((out / name / "episode.json").read_text(encoding="utf-8"))
        assert manifest["split"]["session_group_id"] == run_id
        assert "Code commit" in manifest["notes"]
        assert "dirty" in manifest["notes"]
        assert "planning_failed" not in manifest["notes"]


def test_a_planning_failure_shows_in_the_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch, _UnplannedPolicy)
    out = repo / "episodes"
    assert record.main(_record_args(out, "12:nominal")) == 0
    manifest = json.loads(
        (out / "m0-scripted-nominal-seed-000012" / "episode.json").read_text(encoding="utf-8")
    )
    assert "planning_failed: no joint solution" in manifest["notes"]


def test_a_second_recording_is_refused_and_ledgered_as_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch)
    out = repo / "episodes"
    assert record.main(_record_args(out, "12:nominal")) == 0
    before = (out / "m0-scripted-nominal-seed-000012" / "episode.json").read_bytes()
    assert record.main(_record_args(out, "12:nominal")) == 2
    assert (out / "m0-scripted-nominal-seed-000012" / "episode.json").read_bytes() == before
    assert [line["status"] for line in _ledger(repo)][-1] == "failed"


def test_a_dev_seed_is_refused_before_any_run_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch)
    assert record.main(_record_args(repo / "episodes", "12:nominal", "8123:nominal")) == 2
    assert not (repo / "ledgers" / "runs.jsonl").exists()
    assert list((repo / "runs").iterdir()) == []


def test_record_refuses_outside_the_repository_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert record.main(_record_args(tmp_path / "out", "12:nominal")) == 2


def test_record_refuses_a_file_that_is_not_the_frozen_one(tmp_path: Path) -> None:
    edited = tmp_path / "M0-exit-tests.json"
    edited.write_text(FROZEN.read_text(encoding="utf-8") + " ", encoding="utf-8")
    code = record.main(
        ["--episode", "12:nominal", "--tolerance-file", str(edited), "--out", str(tmp_path / "o")]
    )
    assert code == 2
    assert not (tmp_path / "o").exists()


def test_record_refuses_a_frozen_file_of_another_kind(tmp_path: Path) -> None:
    other = ROOT / "evals" / "M1-exit-tests.json"
    code = record.main(
        ["--episode", "12:nominal", "--tolerance-file", str(other), "--out", str(tmp_path / "o")]
    )
    assert code == 2


def test_record_says_not_run_without_the_simulator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch)

    def unavailable(**_: Any) -> None:
        raise record.SimulatorUnavailableError("no stack")

    monkeypatch.setattr(record, "ManiSkillPickCube", unavailable)
    assert record.main(_record_args(repo / "o", "12:nominal")) == 3
    assert list((repo / "runs").iterdir()) == []


def _episode(tmp_path: Path, **plan: Any) -> tuple[Path, list[dict[str, Any]]]:
    target = tmp_path / "episode"
    record_episode(FakeArmEnv(), plan_policy(scripted_plan(3, **plan)), _fixture_spec("e"), target)
    lines = (target / "transitions.jsonl").read_text(encoding="utf-8").splitlines()
    return target, [json.loads(line) for line in lines]


def test_raw_facts_report_a_fixture_success(tmp_path: Path) -> None:
    _, records = _episode(tmp_path)
    facts = raw_facts(records)
    assert facts["records"] == len(records)
    assert facts["cube_peak_height_m"] > 0.0325
    assert facts["grasped_at_end"] is False
    assert facts["end_distance_to_target_xy_m"] <= 0.015625
    assert facts["largest_step_motion_in_last_10_steps_m"] == 0.0


def test_raw_facts_show_a_fixture_miss(tmp_path: Path) -> None:
    _, records = _episode(tmp_path, target_miss=0.05)
    assert raw_facts(records)["end_distance_to_target_xy_m"] == pytest.approx(0.05, abs=1e-6)


def test_raw_facts_show_a_grasp_that_was_never_released(tmp_path: Path) -> None:
    _, records = _episode(tmp_path, release=False)
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


def test_inspection_writes_once(tmp_path: Path) -> None:
    episode, _ = _episode(tmp_path)
    out = tmp_path / "inspected"
    assert inspect_episode.main(["--episode", str(episode), "--out", str(out)]) == 0
    report = json.loads((out / "inspection.json").read_text(encoding="utf-8"))
    assert report["episode_id"] == "e"
    assert report["raw_facts"]["records"] > 0
    assert inspect_episode.main(["--episode", str(episode), "--out", str(out)]) == 2


def test_inspection_loads_no_rubric_code() -> None:
    # The contract seam imports the rubric's types, so check what this module itself calls.
    code = (
        "import json, sys; import vishwaroop.sim.inspect_episode as tool; "
        "print(json.dumps(sorted(name for name in vars(tool))))"
    )
    done = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    names = set(json.loads(done.stdout))
    assert not names & {"assess", "samples_from_episode", "samples_from_records", "PickPlaceJudge"}


def _edit_manifest(episode: Path, **top: Any) -> None:
    path = episode / "episode.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["data"].update(top)
    path.write_text(json.dumps(manifest), encoding="utf-8")


def test_inspection_refuses_edited_transitions(tmp_path: Path) -> None:
    episode, _ = _episode(tmp_path)
    path = episode / "transitions.jsonl"
    path.write_text(path.read_text(encoding="utf-8").replace("0.0125", "9.0"), encoding="utf-8")
    out = tmp_path / "inspected"
    assert inspect_episode.main(["--episode", str(episode), "--out", str(out)]) == 2
    assert not out.exists()


@pytest.mark.parametrize("path", ["/etc/hosts", "../outside.jsonl"])
def test_inspection_refuses_an_unsafe_path(tmp_path: Path, path: str) -> None:
    episode, _ = _episode(tmp_path)
    (tmp_path / "outside.jsonl").write_text("{}\n", encoding="utf-8")
    _edit_manifest(episode, transitions_artifact={"path": path, "sha256": "0" * 64})
    out = tmp_path / "inspected"
    assert inspect_episode.main(["--episode", str(episode), "--out", str(out)]) == 2
    assert not out.exists()


def test_an_invalid_stream_is_refused_and_leaves_no_directory(tmp_path: Path) -> None:
    class Blind(FakeArmEnv):
        def _packet(self) -> Packet:
            packet = super()._packet()
            packet["object_position"] = [float("nan")] * 3
            return packet

    target = tmp_path / "blind"
    record_episode(Blind(), plan_policy(scripted_plan(3)), _fixture_spec("b"), target)
    out = tmp_path / "inspected"
    assert inspect_episode.main(["--episode", str(target), "--out", str(out)]) == 2
    assert not out.exists()


@pytest.mark.parametrize(
    ("worst", "code", "trusted", "shown"),
    [
        (0.0, 0, True, 0.0),
        (0.001, 0, True, 0.001),
        (0.0011, 1, False, 0.0011),
        (float("inf"), 1, False, "inf"),
    ],
)
def test_pictures_of_a_different_run_are_not_trusted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    worst: float,
    code: int,
    trusted: bool,
    shown: Any,
) -> None:
    episode, _ = _episode(tmp_path)
    monkeypatch.setattr(inspect_episode, "_render", lambda *_: worst)
    out = tmp_path / "inspected"
    assert inspect_episode.main(["--episode", str(episode), "--out", str(out), "--render"]) == code
    report = json.loads((out / "inspection.json").read_text(encoding="utf-8"))
    assert report["rendered_run_trusted"] is trusted
    assert report["rendered_run_max_deviation"] == shown


class _FixturePolicy:
    planning_error: str | None = None

    def __init__(self, _settings: Any) -> None:
        self._plan = scripted_plan(3)

    def __call__(self, _packet: Packet, step: int) -> list[float] | None:
        return self._plan[step] if step < len(self._plan) else None


def test_sensitivity_finds_nothing_on_a_fixture_that_reproduces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sensitivity, "ScriptedPickPlace", _FixturePolicy)
    monkeypatch.setattr(sensitivity, "_STREAMS", ("object_position", "target_position"))
    monkeypatch.setattr(sensitivity, "BRANCH_STEPS", (5,))
    result = sensitivity.measure(FakeArmEnv(), [3], [3], 0.001, RUBRIC, nudge=lambda state: state)
    assert result["seeds_skipped_unplanned"] == []
    for case in result["cases"].values():
        assert case == {
            "episodes": 1,
            "over_tolerance": 0,
            "max_deviation": 0.0,
            "label_flips": 0,
        }
    assert result["branches"]["5"]["over_tolerance"] == 0


def test_sensitivity_counts_a_fixture_that_drifts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sensitivity, "ScriptedPickPlace", _FixturePolicy)
    monkeypatch.setattr(sensitivity, "_STREAMS", ("joint_position", "target_position"))
    monkeypatch.setattr(sensitivity, "BRANCH_STEPS", ())
    env = FakeArmEnv(drift=0.01)
    result = sensitivity.measure(env, [3], [], 0.001, RUBRIC, nudge=lambda state: state)
    assert result["cases"]["restored_again"]["over_tolerance"] == 1
    assert result["cases"]["restored_again"]["max_deviation"] > 0.001


def test_sensitivity_skips_and_names_a_plan_that_could_not_be_made(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Unplanned(_FixturePolicy):
        planning_error = "no joint solution"

    monkeypatch.setattr(sensitivity, "ScriptedPickPlace", Unplanned)
    monkeypatch.setattr(sensitivity, "_STREAMS", ("object_position", "target_position"))
    result = sensitivity.measure(FakeArmEnv(), [3], [], 0.001, RUBRIC, nudge=lambda state: state)
    assert result["seeds_skipped_unplanned"] == [3]
    assert result["cases"]["plain_reset"]["episodes"] == 0


def test_the_nudge_moves_only_the_cube_x() -> None:
    state = {"seed": 1, "state": {"actors": {"cube": [[0.5, 0.25, 0.0125]]}}}
    moved = json.loads(sensitivity.nudge_cube(json.dumps(state).encode("utf-8"), 1e-3))
    assert moved["state"]["actors"]["cube"][0] == [0.501, 0.25, 0.0125]
    assert moved["seed"] == 1


@pytest.mark.parametrize(("first", "count"), [(7999, 2), (8000, 1), (-1, 1)])
def test_sensitivity_stays_out_of_the_dev_holdout(tmp_path: Path, first: int, count: int) -> None:
    code = sensitivity.main(
        [
            "--first-seed", str(first), "--seeds", str(count),
            "--tolerance-file", str(FROZEN), "--out", str(tmp_path / "report.json"),
        ]
    )  # fmt: skip
    assert code == 2
    assert not (tmp_path / "report.json").exists()


def test_sensitivity_will_not_overwrite(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    out.write_text("{}", encoding="utf-8")
    code = sensitivity.main(["--tolerance-file", str(FROZEN), "--out", str(out)])
    assert code == 2
    assert out.read_text(encoding="utf-8") == "{}"
