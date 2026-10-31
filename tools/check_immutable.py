#!/usr/bin/env python3
"""Enforce the append-only rule on protected paths for a pull request (AGENTS.md section 6).

Compares the merge base of ``--base`` and ``HEAD`` with ``HEAD`` using ``git diff --name-status``
and
fails on:

- any deletion, rename or file-type change under a protected path;
- any modification under ``data/``, ``runs/``, ``artifacts/manifests/`` (write-once);
- a modification of a ledger (``ledgers/*.jsonl``, ``work_orders/STATUS.jsonl``) or a report
  (``reports/*.md``) that is not a pure append (old content must be a byte prefix of new content);
- any modification of a work order with an ``accepted`` event anywhere in the ledger (frozen).

Derived files (``docs/STATUS_BOARD.md``, ``reports/INDEX.md``) and the READMEs inside protected
directories are exempt because they are regenerated or documentary.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
WRITE_ONCE_PREFIXES = ("data/", "runs/", "artifacts/manifests/")
APPEND_ONLY_PREFIXES = ("ledgers/", "reports/")
EXEMPT = {
    "docs/STATUS_BOARD.md",
    "reports/INDEX.md",
    "reports/README.md",
    "ledgers/README.md",
    "data/README.md",
    "runs/README.md",
    "artifacts/README.md",
}
STATUS_LEDGER = "work_orders/STATUS.jsonl"


def git(*args: str, cwd: Path = ROOT, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def accepted_work_orders(status_text: str) -> set[str]:
    """WO ids with an ``accepted`` event anywhere in the ledger; a later line cannot undo it."""
    accepted: set[str] = set()
    for line in status_text.splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        wo = record.get("wo")
        if isinstance(wo, str) and record.get("event") == "accepted":
            accepted.add(wo)
    return accepted


def is_protected(path: str) -> bool:
    if path in EXEMPT:
        return False
    return (
        path.startswith(WRITE_ONCE_PREFIXES)
        or path.startswith(APPEND_ONLY_PREFIXES)
        or path == STATUS_LEDGER
        or (path.startswith("work_orders/WO-") and path.endswith(".md"))
    )


def evaluate(base_ref: str, cwd: Path = ROOT) -> list[str]:
    merge_base = git("merge-base", base_ref, "HEAD", cwd=cwd).strip()
    diff = git("diff", "--name-status", "-M", merge_base, "HEAD", cwd=cwd)
    # Frozen WOs are judged by the status ledger as of HEAD (a PR cannot un-accept a WO).
    head_status = git("show", f"HEAD:{STATUS_LEDGER}", cwd=cwd, check=False)
    frozen = accepted_work_orders(head_status)
    violations: list[str] = []
    for raw in diff.splitlines():
        parts = raw.split("\t")
        status = parts[0]
        path = parts[-1]
        old_path = parts[1] if status.startswith("R") and len(parts) == 3 else path
        if not (is_protected(path) or is_protected(old_path)):
            continue
        if status.startswith("D"):
            violations.append(f"{path}: deleted (protected paths are never deleted)")
        elif status.startswith("R"):
            violations.append(f"{old_path} -> {path}: renamed (protected paths are never renamed)")
        elif status.startswith("T"):
            violations.append(f"{path}: file type changed (protected paths keep their type)")
        elif status.startswith("M"):
            if path.startswith(WRITE_ONCE_PREFIXES):
                violations.append(f"{path}: modified (write-once; create a new record instead)")
            elif path.startswith("work_orders/WO-"):
                wo_id = (
                    PurePosixPath(path).name.split("-")[0]
                    + "-"
                    + PurePosixPath(path).name.split("-")[1]
                )
                if wo_id in frozen:
                    violations.append(
                        f"{path}: modified but {wo_id} is accepted (frozen; open a new WO)"
                    )
            else:  # append-only ledgers and reports
                old = git("show", f"{merge_base}:{path}", cwd=cwd, check=False)
                new = git("show", f"HEAD:{path}", cwd=cwd, check=False)
                if not new.startswith(old):
                    violations.append(f"{path}: modified in a way that is not a pure append")
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="base ref, e.g. origin/main")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        violations = evaluate(args.base, cwd=args.root.resolve())
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 2
    for item in violations:
        print(f"FAIL: {item}")
    if violations:
        return 1
    print("append-only check OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
