"""The frozen M0 and M1 specification stays consistent with the phases, and stays frozen."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _frozen(root: Path, name: str) -> dict[str, object]:
    loaded: dict[str, object] = json.loads((root / "evals" / name).read_text(encoding="utf-8"))
    return loaded


@pytest.mark.parametrize(
    ("phase", "name"), [("M0", "M0-exit-tests.json"), ("M1", "M1-exit-tests.json")]
)
def test_exit_test_ids_match_the_phase(
    root: Path, phases_config: dict[str, object], phase: str, name: str
) -> None:
    frozen = _frozen(root, name)
    assert frozen["phase"] == phase
    phases = phases_config["phases"]
    assert isinstance(phases, list)
    expected = {et["id"] for p in phases if p["id"] == phase for et in p["exit_tests"]}
    exit_tests = frozen["exit_tests"]
    assert isinstance(exit_tests, list)
    assert {et["id"] for et in exit_tests} == expected
    assert all(et["threshold"] for et in exit_tests)


def test_every_frozen_exit_test_has_a_frozen_event(root: Path) -> None:
    events = [
        json.loads(line)
        for line in (root / "work_orders" / "STATUS.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    frozen_events = {e["et"] for e in events if e.get("event") == "frozen" and "et" in e}
    for name in ("M0-exit-tests.json", "M1-exit-tests.json"):
        exit_tests = _frozen(root, name)["exit_tests"]
        assert isinstance(exit_tests, list)
        assert {et["id"] for et in exit_tests} <= frozen_events


def test_frozen_events_record_the_current_file_hashes(root: Path) -> None:
    """Editing a frozen file without a new version fails here."""
    import hashlib

    events = [
        json.loads(line)
        for line in (root / "work_orders" / "STATUS.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    notes = [e["note"] for e in events if e.get("event") == "frozen" and "et" in e]
    for name in ("M0-exit-tests.json", "M0-protocol.md", "M1-exit-tests.json"):
        digest = hashlib.sha256((root / "evals" / name).read_bytes()).hexdigest()
        assert any(f"evals/{name} sha256 {digest}" in note for note in notes), name


def test_the_protocol_names_run_and_family_grouping(root: Path) -> None:
    protocol = (root / "evals" / "M0-protocol.md").read_text(encoding="utf-8")
    assert "**training run or family**" in protocol
    for section in ("rubric", "Splits", "Policy holdout", "Sealed opening budget", "Baselines"):
        assert section in protocol
