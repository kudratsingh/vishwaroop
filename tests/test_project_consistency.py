"""Consistency of phases, exit tests, work orders, and policy documents in this repository."""

from __future__ import annotations

import json
import re
from pathlib import Path

ET_PATTERN = re.compile(r"ET-[A-Za-z0-9]+-\d+")


def _phases(root: Path) -> dict[str, object]:
    loaded: dict[str, object] = json.loads(
        (root / "config" / "phases.json").read_text(encoding="utf-8")
    )
    return loaded


def test_phases_json_shape(root: Path) -> None:
    cfg = _phases(root)
    phases = cfg["phases"]
    assert isinstance(phases, list) and phases
    ids = [p["id"] for p in phases]
    assert len(ids) == len(set(ids)), "phase ids must be unique"
    for phase in phases:
        for key in ("id", "name", "deliverable", "prerequisites", "exit_tests", "program_link"):
            assert key in phase, f"phase {phase.get('id')} missing {key}"
        for prereq in phase["prerequisites"]:
            assert prereq in ids, f"{phase['id']} prerequisite {prereq} is not a phase"
        assert phase["exit_tests"], f"{phase['id']} has no exit tests"
        for et in phase["exit_tests"]:
            assert et["id"].startswith(f"ET-{phase['id']}-"), et["id"]
            for key in ("statement", "evidence", "threshold"):
                assert et[key], f"{et['id']} missing {key}"


def test_phases_md_and_json_agree(root: Path) -> None:
    cfg = _phases(root)
    text = (root / "docs" / "PHASES.md").read_text(encoding="utf-8")
    json_ets = {et["id"] for p in cfg["phases"] for et in p["exit_tests"]}
    md_ets = set(ET_PATTERN.findall(text))
    assert json_ets <= md_ets, f"exit tests missing from PHASES.md: {sorted(json_ets - md_ets)}"
    assert md_ets <= json_ets, (
        f"exit tests in PHASES.md but not phases.json: {sorted(md_ets - json_ets)}"
    )
    for p in cfg["phases"]:
        assert f"## {p['id']}" in text or f"### {p['id']}" in text, (
            f"PHASES.md lacks a heading for {p['id']}"
        )


def test_work_orders_reference_known_phases_and_exit_tests(root: Path) -> None:
    cfg = _phases(root)
    phase_ids = {p["id"] for p in cfg["phases"]}
    et_ids = {et["id"] for p in cfg["phases"] for et in p["exit_tests"]}
    files = sorted((root / "work_orders").glob("WO-*.md"))
    assert files, "no work orders"
    seen_ids: set[str] = set()
    for path in files:
        text = path.read_text(encoding="utf-8")
        head = text.splitlines()[0]
        m = re.match(r"# (WO-\d{3}) \| .+", head)
        assert m, f"{path.name}: first line must be '# WO-nnn | title'"
        assert path.name.startswith(m.group(1) + "-"), (
            f"{path.name}: id in header does not match file name"
        )
        assert m.group(1) not in seen_ids, f"duplicate work order id {m.group(1)}"
        seen_ids.add(m.group(1))
        phase = re.search(r"\*\*Phase:\*\*\s*(\S+)", text)
        assert phase and phase.group(1) in phase_ids, f"{path.name}: unknown or missing phase"
        for et in ET_PATTERN.findall(text):
            assert et in et_ids, f"{path.name}: unknown exit test {et}"
        for section in (
            "## Objective",
            "## Scope",
            "## Out of scope",
            "## Verification",
            "## Stop conditions",
        ):
            assert section in text, f"{path.name}: missing section {section}"


def test_policy_documents_present_and_linked(root: Path) -> None:
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    for section in (
        "## 1. Scope and protection of existing work",
        "## 2. Authorization matrix",
        "## 4. Git, subagents and CI",
        "## 5. Phases, exit tests, work orders, status",
        "## 6. Data and records: append-only, never delete, never overwrite",
        "## 12. Stop conditions and escalation",
        "## 13. Project-specific rules",
    ):
        assert section in agents, f"AGENTS.md missing {section}"
    assert "{{PROJECT_ADDENDUM}}" not in agents
    claude = (root / "CLAUDE.md").read_text(encoding="utf-8")
    assert "AGENTS.md" in claude
    program = (root / "PROGRAM.md").read_text(encoding="utf-8")
    assert program.startswith("# PROGRAM.md")
    start = (root / "START_HERE.md").read_text(encoding="utf-8")
    assert "PROGRAM.md" in start and "AGENTS.md" in start


def test_status_ledger_is_valid_jsonl(root: Path) -> None:
    path = root / "work_orders" / "STATUS.jsonl"
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        assert line.strip(), f"STATUS.jsonl:{number} empty line"
        record = json.loads(line)
        assert "event" in record and ("wo" in record or "phase" in record or "et" in record)


def test_no_fixture_claims_in_reports(root: Path) -> None:
    """Reports directory must not contain milestone reports in the starter (nothing has run)."""
    reports = [
        p for p in (root / "reports").glob("*.md") if p.name not in {"README.md", "INDEX.md"}
    ]
    assert reports == [], (
        f"starter kit must not ship milestone reports: {[p.name for p in reports]}"
    )
