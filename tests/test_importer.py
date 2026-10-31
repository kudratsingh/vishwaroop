"""Read-only import: refuses incomplete or tampered exports; copies write-once; appends a ledger."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from vishwaroop import importer


def _export(
    tmp_path: Path, *, complete: bool = True, tamper: bool = False, escape: bool = False
) -> Path:
    root = tmp_path / "export-001"
    root.mkdir()
    (root / "weights.safetensors").write_bytes(b"not real weights")
    (root / "results.json").write_text('{"fabricated": true}')
    files = {
        "weights.safetensors": hashlib.sha256(b"not real weights").hexdigest(),
        "results.json": hashlib.sha256(b'{"fabricated": true}').hexdigest(),
    }
    if escape:
        files["../outside.json"] = "0" * 64
    manifest = {
        "export_id": "export-001",
        "producer": "vla-rl-so101",
        "files": files,
        "identities": {"run_family": "famA", "checkpoint_id": "ckpt-7", "protocol_version": "p1"},
    }
    (root / "MANIFEST.json").write_text(json.dumps(manifest))
    if tamper:
        (root / "results.json").write_text('{"fabricated": true, "edited": 1}')
    if complete:
        (root / "COMPLETE").write_text("")
    return root


def test_verify_refuses_incomplete_export(tmp_path: Path) -> None:
    root = _export(tmp_path, complete=False)
    with pytest.raises(importer.ExportImportError, match="COMPLETE marker missing"):
        importer.verify_export(root)


def test_verify_refuses_hash_mismatch(tmp_path: Path) -> None:
    root = _export(tmp_path, tamper=True)
    with pytest.raises(importer.ExportImportError, match="hash mismatch"):
        importer.verify_export(root)


def test_verify_refuses_path_escape(tmp_path: Path) -> None:
    root = _export(tmp_path, escape=True)
    with pytest.raises(importer.ExportImportError, match="unsafe path"):
        importer.verify_export(root)


def test_register_copies_write_once_and_appends_ledger(tmp_path: Path) -> None:
    root = _export(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    record = importer.register_import(root, repo)
    target = repo / "data" / "imports" / "export-001"
    assert (target / "weights.safetensors").is_file()
    assert not os.access(target / "weights.safetensors", os.W_OK) or os.geteuid() == 0
    ledger_lines = (repo / "ledgers" / "imports.jsonl").read_text().splitlines()
    assert len(ledger_lines) == 1
    assert json.loads(ledger_lines[0])["identities"]["run_family"] == "famA"
    assert record["read_only"] is True
    # export untouched
    assert sorted(p.name for p in root.iterdir()) == [
        "COMPLETE",
        "MANIFEST.json",
        "results.json",
        "weights.safetensors",
    ]
    with pytest.raises(importer.ExportImportError, match="write-once"):
        importer.register_import(root, repo)


def test_cli_verify(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _export(tmp_path)
    assert importer.main(["verify", str(root)]) == 0
    assert '"files": 2' in capsys.readouterr().out
    assert importer.main(["verify", str(tmp_path / "nope")]) == 2
