"""The refusals every ET-M3-6 command shares (WO-022), with no numpy and no torch.

- ``check_frozen``: the frozen files ET-M3-6 rests on still have their frozen sha256s. The M3 code
  checks them itself and never relies on ET-M3-1's ledger state or on ``sim.replay``'s M0 check.
- ``require_owner_approval``: a named record in ``ledgers/approvals.jsonl``, from the owner, that
  this reviewed code lists for the action (``RECORDING``, ``TRAINING``, ``SCORING``). Nothing is
  matched by substring: the record id must be on the action's list, its ``work_order`` must be
  WO-022, neither its gate nor its ``not_authorized`` may deny the action, it must not have expired,
  and no later owner record on WO-022 that this code was not reviewed against may exist. The
  owner's WO-022 record (``approvals-20261108T081923998845Z-b8daa5a7``) approves recording and
  training and refuses scoring, so ``SCORING`` lists no record (WO-022, Stop conditions).
- ``check_f3_protocol_frozen``: scoring also waits for F3's protocol to be frozen; ``F3_PROTOCOL``
  is ``None`` in WO-022, so scoring is refused whatever the ledger says.
- ``check_not_run`` and ``check_not_started``: one result per command, and a stopped command is
  resumed, never started again (AGENTS.md section 13.9).
- ``check_resume``: a resumed command has the same settings and the same code under ``src/``.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
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
STATUS = Path("work_orders/STATUS.jsonl")
RUNS = Path("runs")
WORK_ORDER = "WO-022"
# The owner's WO-022 decision, 2026-11-08: recording and training approved; scoring NOT approved
# until F3's protocol is frozen; agent detail 1 vetoed, details 2 and 3 approved.
OWNER_WO_022 = "approvals-20261108T081923998845Z-b8daa5a7"
# Every owner record on WO-022 this code was reviewed against. A later one (a hold, a revocation,
# a scoring approval) stops every command until the code is reviewed against it.
REVIEWED_OWNER_RECORDS = (OWNER_WO_022,)
# F3's frozen protocol file and its sha256, named by a later reviewed work order. None in WO-022:
# scoring waits for it (check_f3_protocol_frozen).
F3_PROTOCOL: tuple[Path, str] | None = None
PLAN_FILE = "plan.json"
CODE_PATHS = ("src",)


class GuardRefusalError(ValueError):
    """A precondition of an ET-M3-6 command does not hold; nothing was simulated or trained."""


@dataclass(frozen=True)
class Authorization:
    """What one kind of command needs from the owner.

    ``record_ids`` are the owner's records this reviewed code accepts for ``action``; ``stem`` is
    the word whose denial in a record's gate or ``not_authorized`` refuses the record for
    ``action``.
    """

    action: str
    stem: str
    work_order: str
    record_ids: tuple[str, ...]


RECORDING = Authorization("recording", "record", WORK_ORDER, (OWNER_WO_022,))
TRAINING = Authorization("training", "train", WORK_ORDER, (OWNER_WO_022,))
# No record approves scoring: the owner's WO-022 record refuses it until F3's protocol is frozen.
SCORING = Authorization("scoring", "scor", WORK_ORDER, ())

_DENIAL = re.compile(
    r"\b(not|no|never|without|hold|held|paused?|veto\w*|revok\w*|refus\w*|den(?:y|ied)|"
    r"withdraw\w*|suspend\w*|stop\w*)\b"
)
_EXPIRY_ACCEPTED = re.compile(r"^(WO-\d+) accepted$")
_EXPIRY_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def check_frozen(frozen: dict[Path, str] = FROZEN, root: Path = Path()) -> dict[str, str]:
    """Refuse unless every frozen file has its frozen sha256. Returns path -> sha256."""
    for path, expected in frozen.items():
        actual = hashlib.sha256((root / path).read_bytes()).hexdigest()
        if actual != expected:
            raise GuardRefusalError(f"{path} has sha256 {actual}, not the frozen {expected}")
    return {str(path): digest for path, digest in frozen.items()}


def _denies(record: dict[str, Any], stem: str) -> str | None:
    """The text of ``record`` that denies the action whose word starts with ``stem``, if any.

    A gate clause (split at ';') that names the action and holds a negation denies it, and so does
    any ``not_authorized`` entry that names the action at all.
    """
    for clause in str(record.get("gate", "")).lower().split(";"):
        if stem in clause and _DENIAL.search(clause):
            return clause.strip()
    for entry in record.get("not_authorized") or []:
        if stem in str(entry).lower():
            return str(entry)
    return None


def _expired(record: dict[str, Any], status: Path, today: datetime.date) -> str | None:
    """Why the record's ``expiry`` has passed, if it has; an expiry this code cannot read counts."""
    expiry = record.get("expiry")
    if expiry is None:
        return None
    text = str(expiry).strip()
    accepted = _EXPIRY_ACCEPTED.match(text)
    if accepted:
        work_order = accepted.group(1)
        if any(
            event.get("wo") == work_order and event.get("event") == "accepted"
            for event in read_lines(status)
        ):
            return f"its expiry {text!r} has passed: {status} records {work_order} accepted"
        return None
    if _EXPIRY_DATE.match(text):
        if today > datetime.date.fromisoformat(text):
            return f"its expiry {text} has passed"
        return None
    return f"its expiry {text!r} is not one this code reads"


def _later_owner_records(
    records: list[dict[str, Any]], record: dict[str, Any], work_order: str
) -> list[str]:
    """Owner records on ``work_order`` after ``record`` that this code was not reviewed against."""
    later = []
    for other in records:
        if other.get("approver") != "owner" or other.get("record_id") in REVIEWED_OWNER_RECORDS:
            continue
        names_it = (
            other.get("work_order") == work_order
            or work_order.lower() in str(other.get("gate", "")).lower()
        )
        if names_it and str(other.get("ts", "")) > str(record.get("ts", "")):
            later.append(str(other.get("record_id")))
    return later


def require_owner_approval(
    record_id: str | None,
    authorization: Authorization,
    ledger: Path = APPROVALS,
    status: Path = STATUS,
    today: datetime.date | None = None,
) -> dict[str, Any]:
    """The owner's approval record ``record_id`` for ``authorization.action``, or a refusal.

    Refused: no record id; an id this code does not list for the action; an id not in the ledger;
    an approver other than the owner; a ``work_order`` other than the action's; a gate clause or a
    ``not_authorized`` entry that denies the action; an expiry that has passed or cannot be read;
    and any later owner record on the work order that this code was not reviewed against.
    """
    action = authorization.action
    if not record_id:
        raise GuardRefusalError(
            f"--owner-approval is required: the owner's record approving {action} "
            f"({authorization.work_order})"
        )
    if record_id not in authorization.record_ids:
        listed = list(authorization.record_ids) or "none"
        raise GuardRefusalError(
            f"{record_id} is not an owner record this code accepts for {action}; accepted: {listed}"
        )
    records = read_lines(Path(ledger))
    found = [record for record in records if record.get("record_id") == record_id]
    if len(found) != 1:
        raise GuardRefusalError(f"no approvals record {record_id} in {ledger}")
    record = found[0]
    if record.get("approver") != "owner":
        raise GuardRefusalError(f"{record_id} is not the owner's approval")
    if record.get("work_order") != authorization.work_order:
        raise GuardRefusalError(
            f"{record_id} is for {record.get('work_order')!r}, not {authorization.work_order}"
        )
    denial = _denies(record, authorization.stem)
    if denial is not None:
        raise GuardRefusalError(f"{record_id} does not approve {action}: {denial!r}")
    expired = _expired(record, Path(status), today or datetime.datetime.now(datetime.UTC).date())
    if expired is not None:
        raise GuardRefusalError(f"{record_id}: {expired}")
    later = _later_owner_records(records, record, authorization.work_order)
    if later:
        raise GuardRefusalError(
            f"later owner records on {authorization.work_order} {later} have not been reviewed "
            "into this code; nothing runs until they are"
        )
    return record


def check_f3_protocol_frozen(
    protocol: tuple[Path, str] | None, status: Path = STATUS, root: Path = Path()
) -> dict[str, str]:
    """Refuse scoring until F3's protocol is frozen (owner, 2026-11-08, ``OWNER_WO_022``).

    ``protocol`` is F3's frozen file and its sha256, which a later reviewed work order names; it is
    ``None`` in WO-022, so scoring is refused. When named, the file must have that sha256 and
    ``status`` must hold a ``frozen`` event whose note gives it.
    """
    if protocol is None:
        raise GuardRefusalError(
            "F3's protocol is not frozen: no arm is scored on block 16 or on the no-harm set "
            f"until it is (owner, 2026-11-08, {OWNER_WO_022})"
        )
    path, expected = protocol
    actual = hashlib.sha256((Path(root) / path).read_bytes()).hexdigest()
    if actual != expected:
        raise GuardRefusalError(f"F3's protocol {path} has sha256 {actual}, not {expected}")
    if not any(
        event.get("event") == "frozen" and expected in str(event.get("note", ""))
        for event in read_lines(Path(root) / status)
    ):
        raise GuardRefusalError(f"{status} records no freeze of F3's protocol {path} {expected}")
    return {str(path): expected}


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
