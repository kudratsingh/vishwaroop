#!/usr/bin/env python3
"""Append-only status ledger for phases, exit tests and work orders, plus the derived status board.

Usage:
  python tools/status_board.py --append --wo WO-001 --event in_progress --note "..."
  python tools/status_board.py --append --phase M0 --event ready
  python tools/status_board.py --append --et ET-M0-1 --event passed \
      --report reports/WO-001-m0.md --commit <sha>
  python tools/status_board.py --render > docs/STATUS_BOARD.md

The ledger is ``work_orders/STATUS.jsonl``; it is never edited, only appended. The board is derived.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "work_orders" / "STATUS.jsonl"
PHASES = ROOT / "config" / "phases.json"

WO_EVENTS = {
    "created",
    "ready",
    "in_progress",
    "blocked",
    "unblocked",
    "accepted",
    "failed",
    "superseded",
}
PHASE_EVENTS = {"ready", "in_progress", "blocked", "unblocked", "passed", "failed"}
ET_EVENTS = {"frozen", "passed", "failed", "not_run"}

# state -> allowed next states (for work orders and phases)
WO_TRANSITIONS: dict[str, set[str]] = {
    "created": {"ready", "superseded"},
    "ready": {"in_progress", "superseded"},
    "in_progress": {"blocked", "accepted", "failed", "superseded"},
    "blocked": {"unblocked", "superseded", "failed"},
    "unblocked": {"in_progress", "blocked", "accepted", "failed", "superseded"},
    "accepted": set(),
    "failed": {"superseded"},
    "superseded": set(),
}
PHASE_TRANSITIONS: dict[str, set[str]] = {
    "not_started": {"ready"},
    "ready": {"in_progress"},
    "in_progress": {"blocked", "passed", "failed"},
    "blocked": {"unblocked", "failed"},
    "unblocked": {"in_progress", "blocked", "passed", "failed"},
    "passed": set(),
    "failed": {"ready"},  # a failed phase may be re-planned with new frozen exit tests
}


class StatusError(ValueError):
    """Invalid id, event, or transition."""


def load_phases(path: Path = PHASES) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def read_ledger(path: Path = LEDGER) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            raise StatusError(f"{path}:{number}: empty line")
        records.append(json.loads(line))
    return records


def wo_files(root: Path = ROOT) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for p in sorted((root / "work_orders").glob("WO-*.md")):
        m = re.match(r"(WO-\d{3})-", p.name)
        if m:
            found[m.group(1)] = p
    return found


def wo_title(path: Path) -> str:
    first = path.read_text(encoding="utf-8").splitlines()[0]
    return first.split("|", 1)[1].strip() if "|" in first else first.lstrip("# ").strip()


def wo_phase(path: Path) -> str | None:
    m = re.search(r"\*\*Phase:\*\*\s*([A-Za-z0-9+]+)", path.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def current_states(
    records: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    wos: dict[str, dict[str, Any]] = {}
    phases: dict[str, dict[str, Any]] = {}
    ets: dict[str, dict[str, Any]] = {}
    for r in records:
        if "wo" in r:
            wos[r["wo"]] = r
        elif "phase" in r:
            phases[r["phase"]] = r
        elif "et" in r:
            ets[r["et"]] = r
    return wos, phases, ets


def validate_append(
    record: dict[str, Any], phases_cfg: dict[str, Any], records: list[dict[str, Any]], root: Path
) -> None:
    wos, phases, _ets = current_states(records)
    phase_ids = {p["id"] for p in phases_cfg["phases"]}
    et_ids = {et["id"] for p in phases_cfg["phases"] for et in p["exit_tests"]}
    if "wo" in record:
        if record["wo"] not in wo_files(root):
            raise StatusError(
                f"unknown work order {record['wo']} (no work_orders/{record['wo']}-*.md)"
            )
        if record["event"] not in WO_EVENTS:
            raise StatusError(f"invalid WO event {record['event']}")
        prev = wos.get(record["wo"], {}).get("event", "created")
        if record["event"] != "created" and record["event"] not in WO_TRANSITIONS[prev]:
            raise StatusError(f"{record['wo']}: cannot go from {prev} to {record['event']}")
        if record["event"] == "accepted" and not (record.get("report") and record.get("commit")):
            raise StatusError("accepted requires --report and --commit")
    elif "phase" in record:
        if record["phase"] not in phase_ids:
            raise StatusError(f"unknown phase {record['phase']}")
        if record["event"] not in PHASE_EVENTS:
            raise StatusError(f"invalid phase event {record['event']}")
        prev = phases.get(record["phase"], {}).get("event", "not_started")
        if record["event"] not in PHASE_TRANSITIONS[prev]:
            raise StatusError(f"{record['phase']}: cannot go from {prev} to {record['event']}")
        if record["event"] == "passed" and not record.get("report"):
            raise StatusError("a phase passes only with --report pointing at the exit-test report")
    elif "et" in record:
        if record["et"] not in et_ids:
            raise StatusError(f"unknown exit test {record['et']}")
        if record["event"] not in ET_EVENTS:
            raise StatusError(f"invalid exit-test event {record['event']}")
        if record["event"] in {"passed", "failed"} and not record.get("report"):
            raise StatusError("exit-test results require --report")
    else:
        raise StatusError("record must name --wo, --phase, or --et")


def append(
    record: dict[str, Any], *, ledger: Path = LEDGER, phases_path: Path = PHASES, root: Path = ROOT
) -> dict[str, Any]:
    records = read_ledger(ledger)
    validate_append(record, load_phases(phases_path), records, root)
    stamp = datetime.now(UTC)
    written = {
        "record_id": f"status-{stamp.strftime('%Y%m%dT%H%M%S%fZ')}-{secrets.token_hex(3)}",
        "ts": stamp.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        **{k: v for k, v in record.items() if v is not None},
    }
    line = json.dumps(written, sort_keys=True, separators=(",", ":")) + "\n"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(ledger, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return written


def render(*, ledger: Path = LEDGER, phases_path: Path = PHASES, root: Path = ROOT) -> str:
    cfg = load_phases(phases_path)
    records = read_ledger(ledger)
    wos, phases, ets = current_states(records)
    files = wo_files(root)
    out: list[str] = []
    out.append(f"# Status board — {cfg['project']}")
    out.append("")
    out.append(
        "_Derived from `work_orders/STATUS.jsonl` and `config/phases.json` by "
        "`tools/status_board.py`. Do not edit by hand._"
    )
    out.append("")
    out.append(
        f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} · "
        f"ledger records: {len(records)}"
    )
    out.append("")
    out.append("## Phases")
    out.append("")
    out.append(
        "| Phase | Name | State | Exit tests (passed / frozen / total) | Prerequisites "
        "| Work orders |"
    )
    out.append("|---|---|---|---|---|---|")
    for p in cfg["phases"]:
        state = phases.get(p["id"], {}).get("event", "not_started")
        total = len(p["exit_tests"])
        frozen = sum(
            1
            for et in p["exit_tests"]
            if ets.get(et["id"], {}).get("event") in {"frozen", "passed", "failed"}
        )
        passed = sum(1 for et in p["exit_tests"] if ets.get(et["id"], {}).get("event") == "passed")
        wo_list = ", ".join(w for w, path in files.items() if wo_phase(path) == p["id"]) or "—"
        prereq = ", ".join(p.get("prerequisites", [])) or "—"
        out.append(
            f"| {p['id']} | {p['name']} | **{state}** | {passed} / {frozen} / {total} "
            f"| {prereq} | {wo_list} |"
        )
    out.append("")
    out.append("## Exit tests")
    out.append("")
    out.append("| Exit test | Phase | Statement | Threshold | State | Report |")
    out.append("|---|---|---|---|---|---|")
    for p in cfg["phases"]:
        for et in p["exit_tests"]:
            rec = ets.get(et["id"], {})
            out.append(
                f"| {et['id']} | {p['id']} | {et['statement']} | {et['threshold']} "
                f"| {rec.get('event', 'not_run')} | {rec.get('report', '—')} |"
            )
    out.append("")
    out.append("## Work orders")
    out.append("")
    out.append("| WO | Title | Phase | State | Last event (UTC) | Report |")
    out.append("|---|---|---|---|---|---|")
    for wo_id, path in files.items():
        rec = wos.get(wo_id, {})
        out.append(
            f"| {wo_id} | {wo_title(path)} | {wo_phase(path) or '?'} "
            f"| **{rec.get('event', 'created')}** | {rec.get('ts', '—')} "
            f"| {rec.get('report', '—')} |"
        )
    out.append("")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--append", action="store_true")
    group.add_argument("--render", action="store_true")
    parser.add_argument("--wo")
    parser.add_argument("--phase")
    parser.add_argument("--et")
    parser.add_argument("--event")
    parser.add_argument("--note")
    parser.add_argument("--report")
    parser.add_argument("--commit")
    parser.add_argument("--actor", default=os.environ.get("AGENT_ID", "agent"))
    args = parser.parse_args(argv)
    try:
        if args.render:
            sys.stdout.write(render())
            return 0
        if not args.event:
            raise StatusError("--event is required with --append")
        record = {
            "wo": args.wo,
            "phase": args.phase,
            "et": args.et,
            "event": args.event,
            "note": args.note,
            "report": args.report,
            "commit": args.commit,
            "actor": args.actor,
        }
        written = append(record)
        print(json.dumps(written, sort_keys=True))
        return 0
    except (StatusError, FileNotFoundError, json.JSONDecodeError, KeyError) as exc:
        print(f"REFUSED: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
