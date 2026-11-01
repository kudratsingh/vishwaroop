"""A ledgered run for the simulator commands (AGENTS.md section 8.1).

Each command runs inside ``ledgered_run``, so its directory under ``runs/`` and its lines in
``ledgers/runs.jsonl`` always end in ``completed``, ``failed`` or ``interrupted``, including when
the process is told to stop with SIGINT or SIGTERM. A hard kill still leaves only ``started``.

It refuses to run from anywhere but the checkout whose code is running, or without git, because the
code commit it records would then be false or absent.
"""

from __future__ import annotations

import json
import signal
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Any

from ironclad.core.runs import finish_run, new_run_dir

CODE_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class Run:
    """An open run. ``note`` becomes the note on its terminal ledger line."""

    directory: Path
    commit: str
    dirty: bool
    note: str = ""

    @property
    def code_note(self) -> str:
        return f"Code commit {self.commit}, dirty {self.dirty}."


def _terminated(_signal: int, _frame: FrameType | None) -> None:
    raise KeyboardInterrupt("SIGTERM")


def require_code_root() -> None:
    """Refuse unless the current directory is the checkout whose code is running."""
    if Path.cwd().resolve() != CODE_ROOT.resolve():
        raise ValueError(f"run this from the checkout whose code is running: {CODE_ROOT}")


@contextmanager
def ledgered_run(
    purpose: str, config: dict[str, Any], seeds: dict[str, int], env_lock: dict[str, Any]
) -> Iterator[Run]:
    """Open a run from the repository root, and always close it. ``ValueError`` if refused."""
    require_code_root()
    repo = Path()
    run_dir = new_run_dir(repo, purpose=purpose, config=config, seeds=seeds, env_lock=env_lock)
    git = json.loads((run_dir / "git.json").read_text(encoding="utf-8"))
    if git["commit"] is None or git["dirty"] is None:
        finish_run(repo, run_dir, status="failed", note="git could not name the code commit")
        raise ValueError("git could not name the code commit, so this run would have no provenance")
    previous = signal.signal(signal.SIGTERM, _terminated)
    run = Run(run_dir, git["commit"], git["dirty"])
    try:
        yield run
    except KeyboardInterrupt as exc:
        finish_run(repo, run_dir, status="interrupted", note=f"stopped: {exc}")
        raise
    except Exception as exc:
        finish_run(repo, run_dir, status="failed", note=f"{type(exc).__name__}: {exc}")
        raise
    else:
        finish_run(repo, run_dir, status="completed", note=run.note)
    finally:
        signal.signal(signal.SIGTERM, previous)
