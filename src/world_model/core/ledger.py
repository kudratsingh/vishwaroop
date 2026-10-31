"""Append-only JSON Lines ledgers.

A ledger is a file of one JSON object per line. This module can only append to it: the file is
opened with ``O_APPEND`` and never truncated, renamed, or rewritten. Corrections are new records
that reference the record they correct (``DATA_POLICY.md`` section 1).
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .jsonutil import StrictJSONError, dumps_canonical, parse_strict


class LedgerError(ValueError):
    """Raised for malformed ledger records or disallowed operations."""


def utc_now_iso() -> str:
    """Current UTC time as an RFC 3339 string with microseconds."""
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def new_record_id(prefix: str) -> str:
    """Unique, sortable record id: ``<prefix>-<UTC timestamp>-<random>``."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{prefix}-{stamp}-{secrets.token_hex(4)}"


def append_record(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    """Append one record to the ledger at ``path`` and return the record as written.

    The record gets ``record_id`` and ``ts`` fields if absent. The write is a single
    ``os.write`` of one line in ``O_APPEND`` mode followed by ``fsync``; there is no code path
    that truncates or rewrites the file. Parent directories are created if needed.
    """
    if not isinstance(record, dict):
        raise LedgerError("a ledger record must be a JSON object")
    if "\n" in dumps_canonical(record):
        raise LedgerError("ledger records must serialize to a single line")
    written = dict(record)
    written.setdefault("record_id", new_record_id(path.stem))
    written.setdefault("ts", utc_now_iso())
    line = dumps_canonical(written) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return written


def iter_records(path: Path) -> Iterator[dict[str, Any]]:
    """Yield records in file order; raise ``LedgerError`` on a malformed line."""
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as stream:
        for number, raw in enumerate(stream, start=1):
            line = raw.strip()
            if not line:
                raise LedgerError(f"{path}:{number}: empty line in ledger")
            try:
                record = parse_strict(line)
            except StrictJSONError as exc:
                raise LedgerError(f"{path}:{number}: {exc}") from exc
            if not isinstance(record, dict):
                raise LedgerError(f"{path}:{number}: record is not an object")
            yield record


def read_records(path: Path) -> list[dict[str, Any]]:
    """Read all records into a list (ledgers are bounded; this is not a streaming store)."""
    return list(iter_records(path))
