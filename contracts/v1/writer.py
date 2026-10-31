#!/usr/bin/env python3
"""Reference exporter: build a contract-v1 episode directory atomically and validate it.

Usage from an adapter (simulator logger, flight-log converter):

    builder = EpisodeBuilder(manifest_without_data_and_artifact_hashes)
    builder.add_file("rubric.json", rubric_bytes)  # any artifact the manifest references
    builder.add_record(step_record)                          # transition records in order
    episode_dir = builder.write(export_root / "ep-0001")    # refuses if the directory exists

The builder fills in sha256 values for artifacts that are referenced by file name (``{"path": "x",
"sha256": ""}``), writes ``transitions.jsonl`` and the ``data`` block, writes everything into a
temporary sibling directory, validates it with ``validate.validate_episode``, then renames it into
place. An existing target is never overwritten (append-only data policy).
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from validate import ContractError, validate_episode


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fill_hashes(value: Any, files: dict[str, bytes]) -> Any:
    """Copy the value, filling every artifact ref whose sha256 is empty from the added files."""
    if isinstance(value, dict):
        if set(value) == {"path", "sha256"} and value["sha256"] == "":
            if value["path"] not in files:
                raise ContractError(
                    f"manifest references {value['path']} but no such file was added"
                )
            return {"path": value["path"], "sha256": _sha256(files[value["path"]])}
        return {k: _fill_hashes(v, files) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill_hashes(v, files) for v in value]
    return value


class EpisodeBuilder:
    """Collect files and transition records, then write a validated episode directory once."""

    def __init__(self, manifest: dict[str, Any]) -> None:
        if "data" in manifest:
            raise ContractError("do not supply the data block; the builder writes it")
        self._manifest = copy.deepcopy(manifest)
        self._files: dict[str, bytes] = {}
        self._records: list[dict[str, Any]] = []

    def add_file(self, name: str, data: bytes) -> str:
        """Add an artifact file (relative name, no directories) and return its sha256."""
        if (
            "/" in name
            or "\\" in name
            or name in {"", ".", "..", "episode.json", "transitions.jsonl"}
        ):
            raise ContractError(f"invalid artifact name {name!r}")
        if name in self._files and self._files[name] != data:
            raise ContractError(f"artifact {name} was already added with different bytes")
        self._files[name] = data
        return _sha256(data)

    def add_record(self, record: dict[str, Any]) -> None:
        """Append one transition record (schema v1). Step numbers must be 0..n-1 in order."""
        expected_step = len(self._records)
        if record.get("step") != expected_step:
            raise ContractError(
                f"record step {record.get('step')} out of order; expected {expected_step}"
            )
        self._records.append(copy.deepcopy(record))

    def write(self, target_dir: Path) -> Path:
        """Write, validate, and atomically place the episode directory. Never overwrites."""
        if not self._records:
            raise ContractError("an episode needs at least one transition record")
        target_dir = Path(target_dir)
        if target_dir.exists():
            raise ContractError(f"{target_dir} already exists; episodes are write-once")
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = Path(
            tempfile.mkdtemp(prefix=f".{target_dir.name}.incoming-", dir=target_dir.parent)
        )
        try:
            transitions = "".join(
                json.dumps(r, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
                for r in self._records
            ).encode("utf-8")
            files = dict(self._files)
            files["transitions.jsonl"] = transitions
            manifest = _fill_hashes(self._manifest, files)
            manifest["data"] = {
                "format": "jsonl",
                "record_count": len(self._records),
                "transitions_artifact": {
                    "path": "transitions.jsonl",
                    "sha256": _sha256(transitions),
                },
            }
            for name, data in files.items():
                (tmp_dir / name).write_bytes(data)
            (tmp_dir / "episode.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            validate_episode(tmp_dir / "episode.json")
            os.rename(
                tmp_dir, target_dir
            )  # atomic on the same filesystem; fails if target appeared
        except Exception:
            for leftover in tmp_dir.glob("*"):
                leftover.unlink()
            tmp_dir.rmdir()
            raise
        return target_dir
