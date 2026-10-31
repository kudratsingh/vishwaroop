"""The one place this package reaches the shared trajectory contract.

The contract is vendored under ``contracts/v1`` today. Shared files become a pinned dependency
(owner decision, 2026-10-31); when this repository bumps that version in its own work order, this
module is what changes.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

_CONTRACT_DIR = Path(__file__).resolve().parents[3] / "contracts" / "v1"


def _load(name: str) -> ModuleType:
    if str(_CONTRACT_DIR) not in sys.path:
        sys.path.insert(0, str(_CONTRACT_DIR))
    return importlib.import_module(name)


def validator() -> ModuleType:
    """Return the contract's ``validate`` module."""
    return _load("validate")


def writer() -> ModuleType:
    """Return the contract's ``writer`` module."""
    return _load("writer")
