"""The append-only guarantees of the core record helpers."""

from __future__ import annotations

import importlib
import json
import logging
from pathlib import Path

import pytest


def _mod(pkg_name: str, name: str):  # type: ignore[no-untyped-def]
    return importlib.import_module(f"{pkg_name}.core.{name}")


# ----------------------------------------------------------------------------- jsonutil


def test_strict_json_rejects_duplicates_and_nonfinite(pkg_name: str) -> None:
    ju = _mod(pkg_name, "jsonutil")
    with pytest.raises(ju.StrictJSONError):
        ju.parse_strict('{"a": 1, "a": 2}')
    with pytest.raises(ju.StrictJSONError):
        ju.parse_strict('{"a": NaN}')
    with pytest.raises(ju.StrictJSONError):
        ju.dumps_canonical({"a": float("inf")})
    assert ju.dumps_canonical({"b": 1, "a": [1, 2]}) == '{"a":[1,2],"b":1}'


# ----------------------------------------------------------------------------- ledger


def test_ledger_appends_and_never_truncates(pkg_name: str, tmp_path: Path) -> None:
    ledger = _mod(pkg_name, "ledger")
    path = tmp_path / "ledgers" / "demo.jsonl"
    first = ledger.append_record(path, {"event": "a"})
    second = ledger.append_record(path, {"event": "b"})
    assert first["record_id"] != second["record_id"]
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "a"
    # appending again keeps earlier bytes as an exact prefix
    before = path.read_bytes()
    ledger.append_record(path, {"event": "c"})
    assert path.read_bytes().startswith(before)
    assert [r["event"] for r in ledger.read_records(path)] == ["a", "b", "c"]


def test_ledger_rejects_non_object_and_multiline(pkg_name: str, tmp_path: Path) -> None:
    ledger = _mod(pkg_name, "ledger")
    with pytest.raises(ledger.LedgerError):
        ledger.append_record(tmp_path / "x.jsonl", ["not", "an", "object"])  # type: ignore[arg-type]


def test_ledger_reader_flags_corruption(pkg_name: str, tmp_path: Path) -> None:
    ledger = _mod(pkg_name, "ledger")
    path = tmp_path / "bad.jsonl"
    path.write_text('{"ok": true}\n\n{"ok": false}\n')
    with pytest.raises(ledger.LedgerError, match="empty line"):
        ledger.read_records(path)


# ----------------------------------------------------------------------------- artifacts


def test_artifact_store_is_content_addressed_and_has_no_delete(
    pkg_name: str, tmp_path: Path
) -> None:
    artifacts = _mod(pkg_name, "artifacts")
    store = artifacts.ArtifactStore(tmp_path / "artifacts")
    first = store.put_bytes(b"hello")
    second = store.put_bytes(b"hello")
    assert first.sha256 == second.sha256
    assert second.already_present is True
    assert store.open_verified(first.sha256) == b"hello"
    assert not hasattr(store, "delete")
    assert not list((tmp_path / "artifacts").rglob(".incoming-*"))


def test_artifact_store_detects_corruption(pkg_name: str, tmp_path: Path) -> None:
    artifacts = _mod(pkg_name, "artifacts")
    store = artifacts.ArtifactStore(tmp_path / "artifacts")
    stored = store.put_bytes(b"payload")
    stored.path.write_bytes(b"tampered")
    with pytest.raises(artifacts.ArtifactError, match=r"verification|corrupt"):
        store.open_verified(stored.sha256)
    with pytest.raises(artifacts.ArtifactError, match="corrupt"):
        store.put_bytes(b"payload")


def test_artifact_put_file_and_manifest_write_once(pkg_name: str, tmp_path: Path) -> None:
    artifacts = _mod(pkg_name, "artifacts")
    store = artifacts.ArtifactStore(tmp_path / "artifacts")
    source = tmp_path / "blob.bin"
    source.write_bytes(b"x" * 3000)
    stored = store.put_file(source)
    assert stored.size_bytes == 3000
    store.write_manifest("blob", {"sha256": stored.sha256, "producer": "test"})
    with pytest.raises(artifacts.ArtifactError, match="already exists"):
        store.write_manifest("blob", {"sha256": stored.sha256})
    with pytest.raises(artifacts.ArtifactError):
        store.write_manifest("../escape", {})


# ----------------------------------------------------------------------------- runs


def test_run_dir_is_created_once_with_provenance(pkg_name: str, tmp_path: Path) -> None:
    runs = _mod(pkg_name, "runs")
    run_dir = runs.new_run_dir(
        tmp_path, purpose="unit-test", config={"a": 1}, seeds={"torch": 0}, env_lock={"python": "x"}
    )
    for name in (
        "config.snapshot.json",
        "seeds.json",
        "env.lock.json",
        "git.json",
        "manifest.json",
    ):
        assert (run_dir / name).is_file()
    ledger_lines = (tmp_path / "ledgers" / "runs.jsonl").read_text().splitlines()
    assert json.loads(ledger_lines[0])["status"] == "started"
    runs.finish_run(tmp_path, run_dir, status="failed", note="deliberate")
    ledger_lines = (tmp_path / "ledgers" / "runs.jsonl").read_text().splitlines()
    assert json.loads(ledger_lines[-1])["status"] == "failed"
    assert (run_dir / "status.failed.json").is_file()
    assert (run_dir / "manifest.json").read_text()  # untouched, still present
    with pytest.raises(runs.RunError):
        runs.finish_run(tmp_path, run_dir, status="deleted")


# ----------------------------------------------------------------------------- log


def test_structured_logger_writes_json_lines_and_redacts(pkg_name: str, tmp_path: Path) -> None:
    log = _mod(pkg_name, "log")
    path = tmp_path / "events.jsonl"
    logger = log.get_logger(f"test.{pkg_name}.structured", path)
    fake_key = "AKIA" + "ABCDEFGHIJKLMNOP"  # built at runtime so the repo scan does not flag it
    logger.info("hello", fields={"token": fake_key, "n": 1})
    for handler in logger.logger.handlers:
        handler.flush()
    line = json.loads(path.read_text().splitlines()[0])
    assert line["msg"] == "hello"
    assert line["fields"]["token"] == "[REDACTED]"
    assert line["fields"]["n"] == 1
    logging.getLogger(f"test.{pkg_name}.structured").handlers.clear()


# ----------------------------------------------------------------------------- config


def test_config_loader_validates_against_schema(pkg_name: str, tmp_path: Path, root: Path) -> None:
    config = _mod(pkg_name, "config")
    good = tmp_path / "ok.json"
    good.write_text(
        json.dumps(
            {
                "record_id": "r1",
                "ts": "2026-10-31T00:00:00Z",
                "suite_id": "s",
                "milestone_id": "m",
                "protocol_version": "1",
                "frozen_candidate_hashes": ["a" * 64],
                "analysis_code_sha256": "b" * 64,
                "approver": "owner",
                "approval_ref": "approvals-1",
                "opened_at": "2026-10-31T00:00:00Z",
                "released_outputs": [],
                "reason": "test",
                "prior_openings": 0,
                "resulting_status": "regression",
                "replacement_suite_id": None,
            }
        )
    )
    schema = root / "config" / "sealed-access.schema.json"
    assert config.load_validated(good, schema)["approver"] == "owner"
    bad = tmp_path / "bad.json"
    bad.write_text('{"record_id": "r1"}')
    with pytest.raises(config.ConfigError):
        config.load_validated(bad, schema)
