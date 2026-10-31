"""Shared pytest fixtures. The package under test is discovered from src/ so the same tests run in
both repositories (vishwaroop / banshee) without edits."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOOLS = ROOT / "tools"
for p in (SRC, TOOLS, ROOT / "contracts" / "v1"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _package_name() -> str:
    candidates = [p.name for p in SRC.iterdir() if p.is_dir() and (p / "__init__.py").exists()]
    assert len(candidates) == 1, f"expected exactly one package under src/, found {candidates}"
    return candidates[0]


PKG = _package_name()


@pytest.fixture(scope="session")
def pkg_name() -> str:
    return PKG


@pytest.fixture(scope="session")
def core() -> ModuleType:
    return importlib.import_module(f"{PKG}.core")


@pytest.fixture(scope="session")
def root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def phases_config() -> dict[str, object]:
    loaded: dict[str, object] = json.loads(
        (ROOT / "config" / "phases.json").read_text(encoding="utf-8")
    )
    return loaded
