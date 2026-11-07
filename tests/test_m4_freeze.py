"""ET-M4-1 and ET-M4-2 are frozen, and the status ledger carries this file's hash."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def test_the_status_ledger_records_the_frozen_m4_protocol(root: Path) -> None:
    path = root / "evals" / "M4-exit-tests.json"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    events = [
        json.loads(line)
        for line in (root / "work_orders" / "STATUS.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    frozen = {e["et"] for e in events if e.get("event") == "frozen" and digest in e.get("note", "")}
    assert {"ET-M4-1", "ET-M4-2"} <= frozen


def test_the_gate_and_its_supersession_are_as_the_owner_set() -> None:
    spec = json.loads(Path("evals/M4-exit-tests.json").read_text(encoding="utf-8"))
    gate = spec["ET-M4-2"]
    assert "0.85" in gate["threshold"]
    assert "step 20" in gate["gated_metric"]
    assert "equal-weight" in gate["gated_metric"]
    assert "never run" in spec["ET-M4-1"]["validator"]


def test_the_m3_remeasure_freeze_is_recorded_before_its_run(root: Path) -> None:
    path = root / "evals" / "M3-remeasure.json"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    notes = (root / "work_orders" / "STATUS.jsonl").read_text(encoding="utf-8")
    assert f"evals/M3-remeasure.json sha256 {digest}" in notes
