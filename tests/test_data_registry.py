"""The registry and the collector, with no simulator. Fixtures are FABRICATED."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from ironclad.contracts.v1.validate import ContractError

from fake_env import FakeArmEnv, plan_policy, scripted_plan
from vishwaroop.data import registry
from vishwaroop.data.registry import RegistryError, check_episode, summarize
from vishwaroop.sim import collect, record
from vishwaroop.sim.env import Packet
from vishwaroop.sim.replay import load_frozen

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "evals" / "M0-exit-tests.json"
PLAN = ROOT / "evals" / "M0-dataset-plan.json"


class _Env(FakeArmEnv):
    """FABRICATED, with a saved state that names its seed, as the real adapter's does."""

    def save_state(self) -> bytes:
        return json.dumps({"seed": self._seed, "state": json.loads(super().save_state())}).encode()

    def restore_state(self, state: bytes) -> Packet:
        return super().restore_state(json.dumps(json.loads(state)["state"]).encode())

    def reset(self, seed: int) -> Packet:
        self._seed = seed
        return super().reset(seed)


class _Policy:
    planning_error: str | None = None

    def __init__(self, _settings: Any = None, noise_seed: int = 0) -> None:
        self._inner = plan_policy(scripted_plan(3))

    def __call__(self, packet: Packet, step: int) -> list[float] | None:
        return self._inner(packet, step)


class _Unplanned(_Policy):
    planning_error = "no joint solution"


@pytest.fixture
def episode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(record, "ScriptedPickPlace", _Policy)
    return record.record_scripted(_Env(), 2012, "nominal", "run-1", FROZEN, tmp_path / "eps", "c.")


def _rehash(episode: Path) -> None:
    """Keep an edit past the file hashes, so the check under test is what catches it."""
    path = episode / "episode.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    state = manifest["simulator"]["initial_state_artifact"]
    state["sha256"] = hashlib.sha256((episode / state["path"]).read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest), encoding="utf-8")


def _edit(episode: Path, change: Any) -> None:
    path = episode / "episode.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    change(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")


def test_a_recorded_episode_passes_and_its_facts_are_right(episode: Path) -> None:
    entry = check_episode(episode)
    assert entry.seed == 2012
    assert entry.family == "m0-scripted-nominal"
    assert entry.partition == "train"
    assert entry.scene_group_id == "m0-seed-block-2"
    assert entry.session_group_id == "run-1"
    assert entry.planning_failed is False
    assert entry.label
    assert len(entry.episode_sha256) == 64


def _forged_dev_split(manifest: dict[str, Any]) -> None:
    manifest["split"]["partition"] = "dev"
    manifest["purpose"] = "evaluation"
    manifest["policy"]["family_id"] = "m0-scripted-nominal"


def test_a_hand_edited_split_that_the_validator_accepts_is_caught(episode: Path) -> None:
    # The open review finding: this edit passes the contract, and replay never reads the split.
    _edit(episode, _forged_dev_split)
    registry.validate_episode(episode / "episode.json")
    with pytest.raises(RegistryError, match=r"seed 2012 belongs to train, but its split says dev"):
        check_episode(episode)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda m: m["split"].update(scene_group_id="m0-seed-block-3"),
            "belongs to m0-seed-block-2",
        ),
        (lambda m: m["split"].update(policy_run_group_id="other"), "run group and family differ"),
    ],
)
def test_other_split_edits_are_caught(episode: Path, change: Any, message: str) -> None:
    _edit(episode, change)
    with pytest.raises(RegistryError, match=message):
        check_episode(episode)


def _family_edit(family: str) -> Any:
    def change(manifest: dict[str, Any]) -> None:
        manifest["policy"]["family_id"] = family
        manifest["split"]["policy_run_group_id"] = family

    return change


@pytest.mark.parametrize(
    ("family", "message"),
    [
        ("other-family", "unknown family"),
        ("m0-scripted-unheard-of", "unknown family"),
        ("m0-scripted-dev-noisy-actions", "belongs to dev, not train"),
        ("m0-scripted-no-release", "does not name its family"),
    ],
)
def test_a_family_edit_is_caught(episode: Path, family: str, message: str) -> None:
    _edit(episode, _family_edit(family))
    with pytest.raises(RegistryError, match=message):
        check_episode(episode)


def test_an_edited_seed_is_caught_if_the_state_hash_was_not_also_changed(episode: Path) -> None:
    state = episode / "initial-state.json"
    saved = json.loads(state.read_text(encoding="utf-8"))
    saved["seed"] = 8012
    state.write_text(json.dumps(saved), encoding="utf-8")
    with pytest.raises(ContractError):
        check_episode(episode)


@pytest.mark.parametrize("seed", ["2012", True, None])
def test_a_state_without_an_integer_seed_is_refused(episode: Path, seed: Any) -> None:
    state = episode / "initial-state.json"
    saved = json.loads(state.read_text(encoding="utf-8"))
    saved["seed"] = seed
    state.write_text(json.dumps(saved), encoding="utf-8")
    _rehash(episode)
    with pytest.raises(RegistryError, match="no integer seed"):
        check_episode(episode)


def test_a_planning_failure_is_seen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(record, "ScriptedPickPlace", _Unplanned)
    path = record.record_scripted(_Env(), 2012, "nominal", "r", FROZEN, tmp_path, "")
    assert check_episode(path).planning_failed is True


def _entries(**labels: int) -> list[dict[str, Any]]:
    return [
        {
            "label": label,
            "family": "m0-scripted-nominal",
            "partition": "train",
            "planning_failed": False,
        }
        for label, count in labels.items()
        for _ in range(count)
    ]


def test_the_thresholds_are_met_exactly_at_the_frozen_numbers() -> None:
    summary = summarize(_entries(success=140, a=20, b=20, c=20))
    assert summary["episodes"] == 200
    assert summary["failure_share"] == pytest.approx(0.30)
    assert summary["failure_modes"] == ["a", "b", "c"]
    assert summary["et_m0_6_counts_met"] is True


@pytest.mark.parametrize(
    "labels",
    [
        {"success": 139, "a": 20, "b": 20, "c": 20},  # 199 episodes
        {"success": 141, "a": 19, "b": 20, "c": 20},  # 29.5% failures
        {"success": 140, "a": 30, "b": 30},  # two modes
    ],
)
def test_each_threshold_can_fail(labels: dict[str, int]) -> None:
    assert summarize(_entries(**labels))["et_m0_6_counts_met"] is False


def test_planning_failures_cannot_carry_the_failure_share() -> None:
    entries = _entries(success=140, a=20, b=20, c=20)
    for entry in entries[-5:]:
        entry["planning_failed"] = True
    summary = summarize(entries)
    assert summary["failure_share"] == pytest.approx(0.30)
    assert summary["failure_share_without_planning_failures"] < 0.30
    assert summary["et_m0_6_counts_met"] is False


def test_build_writes_once_and_summarize_rechecks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(record, "ScriptedPickPlace", _Policy)
    root = tmp_path / "set"
    for seed in (2012, 2013):
        record.record_scripted(_Env(), seed, "nominal", "run-1", FROZEN, root, "")
    out = tmp_path / "manifest.json"
    args = ["build", "--root", str(root), "--out", str(out)]
    assert registry.main(args) == 1  # two episodes miss the frozen count
    manifest = json.loads(out.read_text(encoding="utf-8"))
    assert manifest["summary"]["episodes"] == 2
    assert manifest["licenses"]["mani_skill"].startswith("Apache-2.0")
    assert registry.main(args) == 2
    assert registry.main(["summarize", str(out)]) == 1
    manifest["summary"]["episodes"] = 300
    out.write_text(json.dumps(manifest), encoding="utf-8")
    assert registry.main(["summarize", str(out)]) == 2


def test_build_refuses_a_set_holding_one_bad_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(record, "ScriptedPickPlace", _Policy)
    root = tmp_path / "set"
    record.record_scripted(_Env(), 2012, "nominal", "run-1", FROZEN, root, "")
    bad = record.record_scripted(_Env(), 2013, "nominal", "run-1", FROZEN, root, "")
    _edit(bad, _forged_dev_split)
    out = tmp_path / "manifest.json"
    assert registry.main(["build", "--root", str(root), "--out", str(out)]) == 2
    assert not out.exists()


def test_build_refuses_an_empty_directory(tmp_path: Path) -> None:
    out = tmp_path / "manifest.json"
    assert registry.main(["build", "--root", str(tmp_path), "--out", str(out)]) == 2


def test_the_committed_plan_keeps_the_rules_and_can_meet_the_threshold() -> None:
    plan = collect.load_plan(PLAN)
    total = sum(family["count"] for family in plan["families"])
    assert total >= 200
    partitions = {family["partition"] for family in plan["families"]}
    assert partitions == {"train", "dev"}
    assert plan["protocol_version"] == json.loads(FROZEN.read_text("utf-8"))["protocol_version"]


def _plan_file(tmp_path: Path, **family: Any) -> Path:
    base = {"variant": "nominal", "partition": "train", "first_seed": 2000, "count": 2}
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"families": [{**base, **family}]}), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "family",
    [
        {"partition": "dev"},
        {"first_seed": 8000},
        {"first_seed": 7999},
        {"count": 0},
        {"variant": "unknown"},
    ],
)
def test_a_plan_that_breaks_the_rules_is_refused(tmp_path: Path, family: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        collect.load_plan(_plan_file(tmp_path, **family))


class _Report:
    def __init__(self, valid: bool = True) -> None:
        self.repeats = [type("Repeat", (), {"max_deviation": 0.0 if valid else 0.5})()]
        self.claim_valid = valid
        self.reason = "ok" if valid else "deviated"


def _small_plan(**changes: Any) -> dict[str, Any]:
    return {
        "replay_sample_per_family": 1,
        "min_free_disk_gb": 0,
        "max_seconds_per_run": 1000,
        "families": [
            {"variant": "nominal", "partition": "train", "first_seed": 2000, "count": 2},
            {"variant": "timeout", "partition": "train", "first_seed": 2000, "count": 1},
            {"variant": "dev-noisy-actions", "partition": "dev", "first_seed": 8000, "count": 1},
        ],
        **changes,
    }


def test_collect_takes_one_partition_and_samples_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(record, "ScriptedPickPlace", _Policy)
    calls: list[Path] = []

    def replay(episode: Path, *_: Any) -> _Report:
        calls.append(episode)
        return _Report()

    report = collect.collect(_Env(), _small_plan(), "train", FROZEN, tmp_path, "run", "c.", replay)
    assert report["episodes"] == 3
    assert set(report["labels"]) == {"nominal", "timeout"}
    assert len(calls) == 2
    assert report["replay_sample_invalid"] == 0
    names = {path.name for path in tmp_path.iterdir()}
    assert "m0-scripted-nominal-seed-002001" in names
    assert not [name for name in names if "dev-" in name]


def test_collect_counts_a_sampled_replay_that_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(record, "ScriptedPickPlace", _Policy)
    report = collect.collect(
        _Env(), _small_plan(), "train", FROZEN, tmp_path, "run", "c.", lambda *_: _Report(False)
    )
    assert report["replay_sample_invalid"] == 2


def test_collect_stops_when_the_disk_is_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(record, "ScriptedPickPlace", _Policy)
    with pytest.raises(OSError, match="GB free"):
        collect.collect(
            _Env(), _small_plan(min_free_disk_gb=10**9), "train", FROZEN, tmp_path, "r", "c."
        )
    assert list(tmp_path.iterdir()) == []


def test_collect_stops_at_its_time_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(record, "ScriptedPickPlace", _Policy)
    ticks = iter([0.0, 1.0, 5000.0])
    with pytest.raises(TimeoutError, match="limit"):
        collect.collect(
            _Env(),
            _small_plan(),
            "train",
            FROZEN,
            tmp_path,
            "r",
            "c.",
            lambda *_: _Report(),
            lambda: next(ticks),
        )
    assert len(list(tmp_path.iterdir())) == 1


def test_collect_refuses_a_partition_with_no_families(tmp_path: Path) -> None:
    plan = _small_plan(families=[])
    with pytest.raises(ValueError, match="no families"):
        collect.collect(_Env(), plan, "train", FROZEN, tmp_path, "r", "c.")


def test_load_frozen_still_reads_the_rubric() -> None:
    assert load_frozen(FROZEN)[1].dwell_steps == 10
