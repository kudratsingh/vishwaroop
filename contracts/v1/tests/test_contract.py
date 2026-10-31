"""Conformance tests for contract v1: validator, split audit, ledger merge, and reference writer.

These tests run against FABRICATED fixtures. A passing suite proves serialization and integrity
rules, not that any simulator, policy, or robot was involved.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from audit_splits import audit  # noqa: E402
from validate import ContractError, parse_json, validate_episode  # noqa: E402
from writer import EpisodeBuilder  # noqa: E402

Episode = dict[str, Any]


@pytest.fixture
def episode(tmp_path: Path) -> Path:
    target = tmp_path / "episode"
    shutil.copytree(HERE / "examples" / "arm_sim", target)
    return target / "episode.json"


def edit(path: Path, fn: Callable[[Episode], None]) -> Episode:
    data = json.loads(path.read_text())
    fn(data)
    path.write_text(json.dumps(data))
    return data


def edit_record(path: Path, fn: Callable[[list[dict[str, Any]]], None]) -> None:
    data = json.loads(path.read_text())
    transitions = path.parent / data["data"]["transitions_artifact"]["path"]
    records = [json.loads(line) for line in transitions.read_text().splitlines()]
    fn(records)
    transitions.write_text("".join(json.dumps(r) + "\n" for r in records))
    data["data"]["transitions_artifact"]["sha256"] = hashlib.sha256(
        transitions.read_bytes()
    ).hexdigest()
    path.write_text(json.dumps(data))


# ----------------------------------------------------------------------------- fixtures validate


@pytest.mark.parametrize("folder", ["arm_sim", "drone_sim", "imagined_arm"])
def test_valid_examples(folder: str) -> None:
    result = validate_episode(HERE / "examples" / folder / "episode.json")
    assert result["records"] == 2
    assert result["status"] == "contract_valid"


def test_all_examples_split_audit() -> None:
    assert audit(sorted((HERE / "examples").glob("*/episode.json")))["episodes"] == 3


def test_schemas_are_valid_draft_2020_12() -> None:
    from jsonschema import Draft202012Validator

    for name in ("episode.schema.json", "transition.schema.json", "validation_ledger.schema.json"):
        Draft202012Validator.check_schema(json.loads((HERE / name).read_text()))


# ----------------------------------------------------------------------------- integrity


def test_hash_mismatch(episode: Path) -> None:
    (episode.parent / "configuration.json").write_text("{}")
    with pytest.raises(ContractError, match="checksum"):
        validate_episode(episode)


def test_record_count(episode: Path) -> None:
    edit(episode, lambda e: e["data"].update(record_count=99))
    with pytest.raises(ContractError, match="count"):
        validate_episode(episode)


def test_path_traversal(episode: Path) -> None:
    edit(
        episode, lambda e: e["configuration"]["controller_artifact"].update(path="../outside.json")
    )
    with pytest.raises(ContractError, match="traversal"):
        validate_episode(episode)


def test_symlink_escape(episode: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    link = episode.parent / "escape.json"
    link.symlink_to(outside)
    digest = hashlib.sha256(outside.read_bytes()).hexdigest()
    edit(
        episode,
        lambda e: e["configuration"].update(
            controller_artifact={"path": "escape.json", "sha256": digest}
        ),
    )
    with pytest.raises(ContractError, match="escaped"):
        validate_episode(episode)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_nonfinite(value: str) -> None:
    with pytest.raises(ContractError):
        parse_json('{"value":' + value + "}")


def test_duplicate_keys() -> None:
    with pytest.raises(ContractError, match="duplicate"):
        parse_json('{"a":1,"a":2}')


def test_unknown_field(episode: Path) -> None:
    edit(episode, lambda e: e.update(secret_extra="not allowed"))
    with pytest.raises(ContractError):
        validate_episode(episode)


# ----------------------------------------------------------------------------- semantics


def test_action_spec_dimensions(episode: Path) -> None:
    edit(episode, lambda e: e["action_spec"]["units"].pop())
    with pytest.raises(ContractError, match="dimension"):
        validate_episode(episode)


def test_unknown_frame(episode: Path) -> None:
    edit(episode, lambda e: e["action_spec"].update(frame_id="unknown"))
    with pytest.raises(ContractError, match="frame"):
        validate_episode(episode)


def test_missing_sim_initial(episode: Path) -> None:
    edit(episode, lambda e: e.update(simulator=None))
    with pytest.raises(ContractError, match="initial"):
        validate_episode(episode)


def test_no_state_forcing(episode: Path) -> None:
    edit(episode, lambda e: e["simulator"].update(restore_mode="every_step"))
    with pytest.raises(ContractError):
        validate_episode(episode)


def test_invalid_action_dimensions(episode: Path) -> None:
    edit_record(episode, lambda r: r[0]["action"].update(requested=[0.0]))
    with pytest.raises(ContractError, match="dimension"):
        validate_episode(episode)


def test_fault_actions_retained(episode: Path) -> None:
    edit_record(episode, lambda r: r[0]["action"].update(requested=[99.0, 0.0]))
    assert validate_episode(episode)["status"] == "contract_valid"


def test_future_input_leakage(episode: Path) -> None:
    edit_record(episode, lambda r: r[0]["observations"][0].update(received_t_ns=r[0]["t_ns"] + 1))
    with pytest.raises(ContractError, match="future"):
        validate_episode(episode)


def test_noncontiguous_time(episode: Path) -> None:
    edit_record(episode, lambda r: r[0].update(dt_ns=10))
    with pytest.raises(ContractError):
        validate_episode(episode)


def test_bad_validity_mask(episode: Path) -> None:
    edit_record(episode, lambda r: r[0]["observations"][0].update(valid=False))
    with pytest.raises(ContractError, match="validity"):
        validate_episode(episode)


def test_missing_stream_explicit(episode: Path) -> None:
    edit_record(episode, lambda r: r[0].update(observations=[]))
    with pytest.raises(ContractError):
        validate_episode(episode)


def test_missing_observation_payload(episode: Path) -> None:
    edit_record(episode, lambda r: r[0]["observations"][0].update(value=None))
    with pytest.raises(ContractError, match="validity"):
        validate_episode(episode)


def test_missing_time_stage(episode: Path) -> None:
    edit_record(episode, lambda r: r[0]["action"].update(sent_t_ns=r[0]["t_ns"]))
    with pytest.raises(ContractError, match="without"):
        validate_episode(episode)


def test_trained_policy_identity(episode: Path) -> None:
    edit(episode, lambda e: e["policy"].update(origin="trained"))
    with pytest.raises(ContractError, match="trained"):
        validate_episode(episode)


def test_fixture_not_evidence(episode: Path) -> None:
    edit(episode, lambda e: e["validation"].update(statuses=["replay_checked"]))
    with pytest.raises(ContractError, match="fixtures"):
        validate_episode(episode)


def test_no_outcome_without_evidence(episode: Path) -> None:
    edit(episode, lambda e: e["outcome"].update(success=True))
    with pytest.raises(ContractError, match="assessment"):
        validate_episode(episode)


def test_imagined_requires_generator(episode: Path) -> None:
    edit(episode, lambda e: e.update(environment_kind="imagined", simulator=None))
    with pytest.raises(ContractError, match="parent and generator"):
        validate_episode(episode)


def test_global_parent_required() -> None:
    with pytest.raises(ContractError, match="absent"):
        audit([HERE / "examples" / "imagined_arm" / "episode.json"])


def test_split_leakage(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    shutil.copytree(HERE / "examples" / "arm_sim", a)
    shutil.copytree(HERE / "examples" / "drone_sim", b)
    session = json.loads((a / "episode.json").read_text())["split"]["session_group_id"]
    edit(
        b / "episode.json",
        lambda e: e["split"].update(partition="sealed", session_group_id=session),
    )
    with pytest.raises(ContractError, match="group leakage"):
        audit([a / "episode.json", b / "episode.json"])


# ----------------------------------------------------------------------------- validation ledger


def _ledger_line(tmp_path: Path, episode_id: str, status: str, kind: str, assessed: str) -> Path:
    evidence_file = tmp_path / "replay-report.json"
    evidence_file.write_text('{"fabricated": true, "note": "test evidence only"}')
    record = {
        "schema_version": "1.0.0",
        "record_id": "ledger-test-0001",
        "ts": "2026-10-31T00:00:00Z",
        "episode_id": episode_id,
        "status": status,
        "evidence": {
            "kind": kind,
            "assessed_episode_id": assessed,
            "artifact": {
                "path": "replay-report.json",
                "sha256": hashlib.sha256(evidence_file.read_bytes()).hexdigest(),
            },
        },
        "protocol_version": "test",
        "actor": "test",
        "notes": "fabricated test record",
    }
    ledger = tmp_path / "validation_ledger.jsonl"
    ledger.write_text(json.dumps(record) + "\n")
    return ledger


def test_ledger_merges_replay_evidence_without_editing_manifest(tmp_path: Path) -> None:
    folder = tmp_path / "imagined"
    shutil.copytree(HERE / "examples" / "imagined_arm", folder)
    # A real export would not be a schema fixture; mark this copy as an evaluation record for the test.
    edit(
        folder / "episode.json",
        lambda e: e.update(purpose="evaluation", notes="TEST COPY of a fabricated fixture"),
    )
    before = (folder / "episode.json").read_bytes()
    ledger = _ledger_line(
        tmp_path, "fixture-imagined-001", "replay_checked", "physics_replay", "fixture-replay-001"
    )
    result = validate_episode(folder / "episode.json", ledger)
    assert "replay_checked" in result["effective_validation_statuses"]
    assert (folder / "episode.json").read_bytes() == before  # manifest untouched


def test_ledger_rejects_physical_status_on_imagined(tmp_path: Path) -> None:
    folder = tmp_path / "imagined"
    shutil.copytree(HERE / "examples" / "imagined_arm", folder)
    edit(folder / "episode.json", lambda e: e.update(purpose="evaluation"))
    ledger = _ledger_line(
        tmp_path,
        "fixture-imagined-001",
        "physically_evaluated",
        "physical_assessment",
        "fixture-imagined-001",
    )
    with pytest.raises(ContractError, match="physical assessment requires a real episode"):
        validate_episode(folder / "episode.json", ledger)


def test_ledger_evidence_artifact_must_exist(tmp_path: Path) -> None:
    folder = tmp_path / "imagined"
    shutil.copytree(HERE / "examples" / "imagined_arm", folder)
    edit(folder / "episode.json", lambda e: e.update(purpose="evaluation"))
    ledger = _ledger_line(tmp_path, "fixture-imagined-001", "replay_checked", "physics_replay", "x")
    (tmp_path / "replay-report.json").unlink()
    with pytest.raises(ContractError, match="missing or escaped artifact"):
        validate_episode(folder / "episode.json", ledger)


def test_ledger_ignores_other_episodes(tmp_path: Path) -> None:
    folder = tmp_path / "arm"
    shutil.copytree(HERE / "examples" / "arm_sim", folder)
    ledger = _ledger_line(tmp_path, "someone-else", "replay_checked", "physics_replay", "x")
    result = validate_episode(folder / "episode.json", ledger)
    assert result["effective_validation_statuses"] == []


# ----------------------------------------------------------------------------- reference writer


def _manifest_from_fixture() -> tuple[dict[str, Any], dict[str, bytes]]:
    source = HERE / "examples" / "arm_sim"
    manifest = json.loads((source / "episode.json").read_text())
    manifest.pop("data")
    manifest["episode_id"] = "writer-test-001"
    files = {
        name: (source / name).read_bytes()
        for name in ("rubric.json", "configuration.json", "initial-state.json", "assets.json")
    }

    def blank(value: Any) -> Any:  # let the builder fill hashes
        if isinstance(value, dict):
            if set(value) == {"path", "sha256"}:
                return {"path": value["path"], "sha256": ""}
            return {k: blank(v) for k, v in value.items()}
        if isinstance(value, list):
            return [blank(v) for v in value]
        return value

    return blank(manifest), files


def _records(episode_id: str) -> list[dict[str, Any]]:
    source = HERE / "examples" / "arm_sim" / "transitions.jsonl"
    records = [json.loads(line) for line in source.read_text().splitlines()]
    for r in records:
        r["episode_id"] = episode_id
    return records


def test_writer_builds_valid_episode(tmp_path: Path) -> None:
    manifest, files = _manifest_from_fixture()
    builder = EpisodeBuilder(manifest)
    for name, data in files.items():
        builder.add_file(name, data)
    for record in _records("writer-test-001"):
        builder.add_record(record)
    out = builder.write(tmp_path / "exports" / "writer-test-001")
    assert validate_episode(out / "episode.json")["records"] == 2
    assert not list((tmp_path / "exports").glob(".*incoming*"))


def test_writer_refuses_overwrite(tmp_path: Path) -> None:
    manifest, files = _manifest_from_fixture()
    target = tmp_path / "exports" / "writer-test-001"
    for _ in range(2):
        builder = EpisodeBuilder(manifest)
        for name, data in files.items():
            builder.add_file(name, data)
        for record in _records("writer-test-001"):
            builder.add_record(record)
        if target.exists():
            with pytest.raises(ContractError, match="write-once"):
                builder.write(target)
        else:
            builder.write(target)


def test_writer_rejects_out_of_order_steps() -> None:
    manifest, _files = _manifest_from_fixture()
    builder = EpisodeBuilder(manifest)
    with pytest.raises(ContractError, match="out of order"):
        builder.add_record({"step": 1})


def test_writer_rejects_missing_referenced_file(tmp_path: Path) -> None:
    manifest, files = _manifest_from_fixture()
    files.pop("rubric.json")
    builder = EpisodeBuilder(manifest)
    for name, data in files.items():
        builder.add_file(name, data)
    for record in _records("writer-test-001"):
        builder.add_record(record)
    with pytest.raises(ContractError, match="no such file was added"):
        builder.write(tmp_path / "exports" / "x")
    assert not (tmp_path / "exports" / "x").exists()
