"""ET-M0-2's lock half: no null pin in the simulator section, and an honest state on every entry."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "config" / "stack-lock.resolved.json").read_text(encoding="utf-8"))
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def test_the_simulator_section_has_no_null_pin() -> None:
    assert LOCK["simulator"]
    for name, entry in LOCK["simulator"].items():
        assert entry["value"], name
        assert entry["state"] == "tested", name
        assert DATE.match(entry["date"]), name


def test_the_fallback_machine_is_only_proposed() -> None:
    entries = {k: v for k, v in LOCK["fallback_linux_gpu_host"].items() if k != "note"}
    assert entries
    for name, entry in entries.items():
        assert entry["state"] == "proposed", name
        assert DATE.match(entry["date"]), name


def test_every_pending_robotics_pin_is_accounted_for() -> None:
    pending = json.loads((ROOT / "config" / "stack-lock.pending.json").read_text(encoding="utf-8"))
    known = set(LOCK["simulator"]) | set(LOCK["not_needed_for_m0"])
    assert set(pending["robotics_runtime"]) - known == set()


def test_the_named_environment_files_exist() -> None:
    assert (ROOT / LOCK["simulator"]["full_environment"]["value"]).is_file()
    assert (ROOT / "config" / "robotics-requirements.linux.txt").is_file()


def test_the_tested_versions_match_the_tested_environment_file() -> None:
    text = (ROOT / LOCK["simulator"]["full_environment"]["value"]).read_text(encoding="utf-8")
    simulator = LOCK["simulator"]
    assert f"mani-skill=={simulator['mani_skill_version_or_commit']['value']}" in text
    assert f"sapien=={simulator['sapien_version']['value']}" in text
    assert f"torch=={simulator['pytorch_version']['value']}" in text
    assert f"gymnasium=={simulator['gymnasium_version']['value']}" in text
    assert f"numpy=={simulator['numpy_version']['value']}" in text
    assert f"jsonschema=={simulator['jsonschema_version']['value']}" in text
