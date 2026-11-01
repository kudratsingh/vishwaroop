"""ET-M0-2's lock half: no null pin in the simulator section, and an honest state on every entry."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "config" / "stack-lock.resolved.v2.json").read_text(encoding="utf-8"))
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def test_the_simulator_section_has_no_null_pin() -> None:
    assert LOCK["simulator"]
    for name, entry in LOCK["simulator"].items():
        assert entry["value"], name
        assert entry["state"] in {"tested", "not_applicable"}, name
        assert DATE.match(entry["date"]), name


def test_not_applicable_is_kept_for_what_a_mac_has_none_of() -> None:
    skipped = {k for k, v in LOCK["simulator"].items() if v["state"] == "not_applicable"}
    assert skipped == {"os_image_digest", "cuda", "nvidia_driver"}


def test_only_the_lock_rule_allows_the_unresolved_section() -> None:
    assert "not_needed_for_m0" in LOCK["rule"]
    unresolved = {k: v for k, v in LOCK["not_needed_for_m0"].items() if k != "note"}
    assert unresolved and all(value is None for value in unresolved.values())


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
    path = ROOT / LOCK["simulator"]["full_environment"]["value"]
    lines = set(path.read_text(encoding="utf-8").splitlines())
    simulator = LOCK["simulator"]
    for package, entry in (
        ("mani-skill", "mani_skill_version_or_commit"),
        ("sapien", "sapien_version"),
        ("torch", "pytorch_version"),
        ("gymnasium", "gymnasium_version"),
        ("numpy", "numpy_version"),
        ("jsonschema", "jsonschema_version"),
    ):
        assert f"{package}=={simulator[entry]['value']}" in lines, package


def test_the_tested_ironclad_is_the_one_in_the_environment_file() -> None:
    path = ROOT / LOCK["simulator"]["full_environment"]["value"]
    version, commit = LOCK["simulator"]["ironclad_kit"]["value"].split(", commit ")
    assert version == "1.1.0"
    line = f"ironclad-kit @ git+https://github.com/kudratsingh/ironclad@{commit}"
    assert line in path.read_text(encoding="utf-8").splitlines()


def test_the_tested_python_is_the_version_ironclad_can_use() -> None:
    major, minor, _ = LOCK["simulator"]["python"]["value"].split(".")
    assert (int(major), int(minor)) >= (3, 12)


def test_the_first_lock_stays_for_the_first_recording() -> None:
    first = json.loads((ROOT / "config" / "stack-lock.resolved.json").read_text(encoding="utf-8"))
    assert first["simulator"]["python"]["value"] == "3.11.15"
