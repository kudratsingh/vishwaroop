"""The refusals every ET-M3-6 command shares (WO-022), with no numpy and no torch.

- ``check_frozen``: the frozen files ET-M3-6 rests on still have their frozen sha256s. The M3 code
  checks them itself and never relies on ET-M3-1's ledger state or on ``sim.replay``'s M0 check.
- ``require_owner_approval``: a named record in ``ledgers/approvals.jsonl``, from the owner, whose
  gate mentions every required phrase. Recording waits for an approval naming WO-022; scoring on
  block 16 waits for one naming ET-M3-6 scoring (WO-022, Stop conditions).
- ``check_not_run`` and ``check_not_started``: one result per command, and a stopped command is
  resumed, never started again (AGENTS.md section 13.9).
- ``check_resume``: a resumed command has the same settings and the same code under ``src/``.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

FROZEN = {
    Path("evals/M3-exit-tests.json"): (
        "2e35a50397b1c97919cb0be7d31b09b374d3fd0f0564741090b93c5e31e8f2d4"
    ),
    Path("evals/M3-protocol.md"): (
        "34ac1338b97d732f3de66f30e83227778af5360117df7674b21dce7dc253ea34"
    ),
    Path("evals/M3-protocol-4.json"): (
        "52508a87852607ec4431d0bc70c8d36bca6b529b6115270373e769c2401f5c2e"
    ),
    Path("evals/M0-exit-tests.json"): (
        "22fbc41c88e549b97076725e61af6ce38d3ee8d0f3f6bb8f7cd7ecfcd4efadda"
    ),
    Path("evals/M3-remeasure.json"): (
        "133ae3c484868b4747ecc42d639a23c4d9b6f6bd7abe982ff857f373a9deada7"
    ),
}
M0_EXIT_TESTS = Path("evals/M0-exit-tests.json")
APPROVALS = Path("ledgers/approvals.jsonl")
RUNS = Path("runs")
RECORDING_GATE = ("WO-022",)
SCORING_GATE = ("ET-M3-6", "scoring")
PLAN_FILE = "plan.json"
CODE_PATHS = ("src",)


class GuardRefusalError(ValueError):
    """A precondition of an ET-M3-6 command does not hold; nothing was simulated or trained."""


def check_frozen(frozen: dict[Path, str] = FROZEN, root: Path = Path()) -> dict[str, str]:
    """Refuse unless every frozen file has its frozen sha256. Returns path -> sha256."""
    for path, expected in frozen.items():
        actual = hashlib.sha256((root / path).read_bytes()).hexdigest()
        if actual != expected:
            raise GuardRefusalError(f"{path} has sha256 {actual}, not the frozen {expected}")
    return {str(path): digest for path, digest in frozen.items()}


def require_owner_approval(
    record_id: str | None, gate_mentions: tuple[str, ...], ledger: Path = APPROVALS
) -> dict[str, Any]:
    """The owner's approval record ``record_id``, refused unless its gate names every phrase.

    Matching ignores case. No record id, an unknown one, an approver other than the owner, or a gate
    that does not mention every phrase is a refusal, so nothing runs before the owner answers.
    """
    if not record_id:
        raise GuardRefusalError(
            f"--owner-approval is required: an approvals record whose gate mentions {gate_mentions}"
        )
    for line in Path(ledger).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record: dict[str, Any] = json.loads(line)
        if record.get("record_id") != record_id:
            continue
        if record.get("approver") != "owner":
            raise GuardRefusalError(f"{record_id} is not the owner's approval")
        gate = str(record.get("gate", "")).lower()
        missing = [phrase for phrase in gate_mentions if phrase.lower() not in gate]
        if missing:
            raise GuardRefusalError(
                f"{record_id}'s gate {record.get('gate')!r} does not mention {missing}"
            )
        return record
    raise GuardRefusalError(f"no approvals record {record_id} in {ledger}")


def check_not_run(runs_root: Path, result: str) -> None:
    """Refuse once a result, or its partial file, exists in any run directory."""
    found = sorted(Path(runs_root).glob(f"*/{result}*"))
    if found:
        raise GuardRefusalError(f"already run in {found[0]}; WO-022 allows one {result}")


def check_not_started(runs_root: Path, marker: str, resume_from: Path | None) -> None:
    """Refuse a fresh start once ``marker`` exists in any run, and a resume from a run without it.

    A command that stopped is resumed from its own run (``--resume-from``), never started again.
    """
    found = sorted(Path(runs_root).glob(f"*/{marker}"))
    if resume_from is None:
        if found:
            raise GuardRefusalError(
                f"{found[0]} exists: this was started before; resume it with --resume-from"
            )
        return
    if not (Path(resume_from) / marker).exists():
        raise GuardRefusalError(f"{resume_from} has no {marker} to resume")


def check_resume(plan: dict[str, Any], config: dict[str, Any], code_changed: bool) -> None:
    """Refuse to continue a stopped command with different settings or different code."""
    if plan["config"] != config:
        raise GuardRefusalError(
            f"settings differ from the stopped run: {plan['config']} against {config}"
        )
    if code_changed:
        raise GuardRefusalError(f"code under src/ changed since the stopped run's {plan['commit']}")


def code_changed(commit: str) -> bool:
    """Whether any file under ``src/`` differs between ``commit`` and HEAD."""
    result = subprocess.run(
        ["git", "diff", "--quiet", commit, "HEAD", "--", *CODE_PATHS], check=False
    )
    if result.returncode not in (0, 1):
        raise GuardRefusalError(f"git could not compare the code with {commit}")
    return result.returncode == 1


def write_once(path: Path, value: Any) -> None:
    """Write a whole JSON file once, through a partial file, so a crash leaves no half result."""
    text = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    partial = path.with_name(f"{path.name}.partial")
    with partial.open("x", encoding="utf-8") as stream:
        stream.write(text)
    if path.exists():
        raise GuardRefusalError(f"{path} exists; results are written once")
    partial.replace(path)


def append_line(path: Path, value: Any) -> None:
    """Append one JSON line to a progress log, opened in append mode only."""
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")


def read_lines(path: Path) -> list[dict[str, Any]]:
    """Every JSON line of a progress log; an absent log is empty."""
    if not Path(path).exists():
        return []
    return [
        json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line
    ]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
