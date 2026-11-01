"""Read-only import of completed exports from other projects (arm checkpoints, drone logs).

An export is a directory the producer finished and sealed::

    <export>/MANIFEST.json   {"export_id": ..., "producer": ...,
                              "files": {"rel/path": "<sha256>", ...},
                              "identities": {...}}   # run family, checkpoint, dataset, protocol
    <export>/COMPLETE        written last by the producer: the export is finished
    <export>/<files...>

``verify_export`` refuses anything without ``COMPLETE`` or ``MANIFEST.json``, with a hash mismatch,
with a file listed but missing, or with a path that escapes the export directory. It never writes
into the export, never locks it, never polls. ``register_import`` copies the files write-once into
``data/imports/<export_id>/``, marks them read-only, and appends one line to
``ledgers/imports.jsonl``.

Automatic export hooks inside the producing project are a future owner-approved producer change;
this module only reads what the owner placed in an export root (docs/DATA_AND_SNAPSHOTS.md
section 4).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ironclad.core.artifacts import sha256_file
from ironclad.core.config import ConfigError, load_json
from ironclad.core.ledger import append_record

COMPLETE_MARKER = "COMPLETE"
MANIFEST_NAME = "MANIFEST.json"
REQUIRED_MANIFEST_KEYS = ("export_id", "producer", "files", "identities")


class ExportImportError(ValueError):
    """An export is incomplete, inconsistent, or unsafe to import."""


@dataclass(frozen=True)
class VerifiedExport:
    """A verified export: identity, producer, file hashes, producer identities."""

    export_id: str
    producer: str
    root: Path
    files: dict[str, str]
    identities: dict[str, Any]


def verify_export(export_dir: Path) -> VerifiedExport:
    """Verify completion marker, manifest shape, path containment and every file hash."""
    root = export_dir.resolve()
    if not root.is_dir():
        raise ExportImportError(f"export directory does not exist: {export_dir}")
    if not (root / COMPLETE_MARKER).is_file():
        raise ExportImportError(
            "export is not complete: COMPLETE marker missing (refusing partial export)"
        )
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ExportImportError("export has no MANIFEST.json")
    try:
        manifest = load_json(manifest_path)
    except ConfigError as exc:
        raise ExportImportError(f"manifest unreadable: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ExportImportError("manifest must be a JSON object")
    missing = [k for k in REQUIRED_MANIFEST_KEYS if k not in manifest]
    if missing:
        raise ExportImportError(f"manifest missing keys {missing}")
    files = manifest["files"]
    if not isinstance(files, dict) or not files:
        raise ExportImportError("manifest.files must be a non-empty object of path -> sha256")
    for rel, expected in files.items():
        candidate = Path(rel)
        if candidate.is_absolute() or ".." in candidate.parts or "\\" in rel:
            raise ExportImportError(f"unsafe path in manifest: {rel}")
        path = (root / candidate).resolve()
        if not path.is_relative_to(root):
            raise ExportImportError(f"path escapes export directory: {rel}")
        if not path.is_file():
            raise ExportImportError(f"file listed in manifest is missing: {rel}")
        if not isinstance(expected, str) or sha256_file(path) != expected:
            raise ExportImportError(
                f"hash mismatch for {rel}; refusing export (never 'fix' the manifest)"
            )
    export_id = manifest["export_id"]
    producer = manifest["producer"]
    identities = manifest["identities"]
    if not isinstance(export_id, str) or not export_id or "/" in export_id:
        raise ExportImportError("export_id must be a plain non-empty string")
    if not isinstance(producer, str) or not producer:
        raise ExportImportError("producer must be a non-empty string")
    if not isinstance(identities, dict):
        raise ExportImportError("identities must be an object")
    return VerifiedExport(export_id, producer, root, dict(files), dict(identities))


def _make_read_only(path: Path) -> None:
    for item in path.rglob("*"):
        if item.is_file():
            item.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


def register_import(export_dir: Path, repo_root: Path, *, actor: str = "agent") -> dict[str, Any]:
    """Verify, copy write-once to data/imports/<export_id>/, mark read-only, append the ledger."""
    verified = verify_export(export_dir)
    target = repo_root / "data" / "imports" / verified.export_id
    if target.exists():
        raise ExportImportError(
            f"{target} already exists; imports are write-once (a new export needs a new id)"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / f".{verified.export_id}.incoming"
    if tmp.exists():
        raise ExportImportError(
            f"stale incoming directory {tmp}; owner must inspect and remove it manually"
        )
    tmp.mkdir()
    try:
        for rel in verified.files:
            dest = tmp / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(verified.root / rel, dest)
        shutil.copy2(verified.root / MANIFEST_NAME, tmp / MANIFEST_NAME)
        # Re-verify the copy before publishing it.
        for rel, expected in verified.files.items():
            if sha256_file(tmp / rel) != expected:
                raise ExportImportError(f"copy of {rel} does not match its hash; aborting import")
        _make_read_only(tmp)
        os.rename(tmp, target)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    record = {
        "export_id": verified.export_id,
        "producer": verified.producer,
        "source": str(verified.root),
        "target": str(target.relative_to(repo_root)),
        "files": verified.files,
        "identities": verified.identities,
        "actor": actor,
        "read_only": True,
    }
    return append_record(repo_root / "ledgers" / "imports.jsonl", record)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["verify", "register"])
    parser.add_argument("export_dir", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            verified = verify_export(args.export_dir)
            print(
                json.dumps(
                    {
                        "export_id": verified.export_id,
                        "producer": verified.producer,
                        "files": len(verified.files),
                    }
                )
            )
        else:
            print(json.dumps(register_import(args.export_dir, args.repo_root), sort_keys=True))
        return 0
    except ExportImportError as exc:
        print(f"REFUSED: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
