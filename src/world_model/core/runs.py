"""Run directories: created exactly once, never reused, never deleted.

``new_run_dir`` makes ``runs/<UTC timestamp>_<id>/`` with an exclusive create and writes the
provenance files every run must have (``DATA_POLICY.md`` section 2). It also appends the
``started`` line to ``ledgers/runs.jsonl``; ``finish_run`` appends the terminal line. Nothing here
removes anything.
"""

from __future__ import annotations

import os
import platform
import secrets
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .jsonutil import dumps_canonical
from .ledger import append_record

TERMINAL_STATUSES = frozenset({"completed", "failed", "interrupted"})


class RunError(ValueError):
    """Raised when a run directory cannot be created or finished correctly."""


def _git_state(repo_root: Path) -> dict[str, Any]:
    """Commit, branch and dirty flag; records ``None`` values when git is unavailable."""

    def run(*args: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", *args],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip() if out.returncode == 0 else None

    status = run("status", "--porcelain")
    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": None if status is None else bool(status),
    }


def _write_once(path: Path, payload: dict[str, Any]) -> None:
    data = (dumps_canonical(payload) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def new_run_dir(
    repo_root: Path,
    *,
    purpose: str,
    config: dict[str, Any],
    seeds: dict[str, int],
    env_lock: dict[str, Any] | None = None,
    runs_root: Path | None = None,
    ledger_path: Path | None = None,
) -> Path:
    """Create a fresh run directory with provenance files and the ``started`` ledger line."""
    runs_root = runs_root or repo_root / "runs"
    ledger_path = ledger_path or repo_root / "ledgers" / "runs.jsonl"
    runs_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{stamp}_{secrets.token_hex(4)}"
    run_dir = runs_root / run_id
    try:
        run_dir.mkdir(mode=0o755)  # exclusive by default: mkdir fails if it exists
    except FileExistsError as exc:  # astronomically unlikely, but never reuse
        raise RunError(f"run directory already exists: {run_dir}") from exc
    (run_dir / "tmp").mkdir()
    _write_once(run_dir / "config.snapshot.json", config)
    _write_once(run_dir / "seeds.json", seeds)
    _write_once(
        run_dir / "env.lock.json",
        env_lock
        or {
            "python": sys.version,
            "platform": platform.platform(),
            "note": "no explicit environment lock supplied; record the real lock before any claim",
        },
    )
    _write_once(run_dir / "git.json", _git_state(repo_root))
    _write_once(
        run_dir / "manifest.json",
        {"run_id": run_id, "purpose": purpose, "status": "started", "inputs": [], "outputs": []},
    )
    append_record(
        ledger_path,
        {"run_id": run_id, "purpose": purpose, "status": "started", "run_dir": str(run_dir)},
    )
    return run_dir


def finish_run(
    repo_root: Path,
    run_dir: Path,
    *,
    status: str,
    note: str = "",
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Append the terminal ledger line for a run. The run directory itself is left untouched."""
    if status not in TERMINAL_STATUSES:
        raise RunError(f"status must be one of {sorted(TERMINAL_STATUSES)}")
    ledger_path = ledger_path or repo_root / "ledgers" / "runs.jsonl"
    # The manifest is write-once; the terminal status lives in the ledger and in a new file.
    _write_once(run_dir / f"status.{status}.json", {"status": status, "note": note})
    return append_record(
        ledger_path,
        {"run_id": run_dir.name, "status": status, "note": note, "run_dir": str(run_dir)},
    )
