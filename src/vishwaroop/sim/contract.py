"""The one place this package reaches the shared trajectory contract.

The contract comes from the pinned ``ironclad-kit`` release (ADR-0007). Moving that pin, in a work
order of this repository's own, is what changes the contract's version here.
"""

from __future__ import annotations

from types import ModuleType

from ironclad.contracts.v1 import validate, writer

from ..outcome.pickplace import PickPlaceJudge, PlaceRubric


def validator() -> ModuleType:
    """Return the contract's ``validate`` module."""
    return validate


def writer_module() -> ModuleType:
    """Return the contract's ``writer`` module."""
    return writer


def contract_judge(rubric: PlaceRubric) -> PickPlaceJudge:
    """A judge that decides only on episodes the contract validator accepts."""
    return PickPlaceJudge(rubric, validate=validate.validate_episode)
