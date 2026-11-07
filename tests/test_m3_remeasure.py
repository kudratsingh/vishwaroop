"""WO-020's frozen target rule and its refusals. Reductions here are FABRICATED."""

from __future__ import annotations

from pathlib import Path

import pytest

from vishwaroop.models.m3_remeasure import (
    CANDIDATES,
    PROTOCOL,
    check_not_run,
    check_protocol,
    target,
    worst,
)

MISSED, EARLY = CANDIDATES


def test_the_protocol_is_the_frozen_one(root: Path) -> None:
    check_protocol(root / PROTOCOL)


def test_the_lower_worst_reduction_is_the_target() -> None:
    assert target({MISSED: -0.63, EARLY: 0.12}) == MISSED
    assert target({MISSED: 0.30, EARLY: 0.10}) == EARLY


def test_both_clearing_twenty_percent_is_the_weaker_motivation_result() -> None:
    assert target({MISSED: 0.20, EARLY: 0.25}).startswith("weaker motivation")


def test_a_tie_goes_to_missed_grasp() -> None:
    assert target({MISSED: 0.1, EARLY: 0.1 + 5e-10}) == MISSED


def test_worst_takes_the_minimum_over_seeds_streams_and_horizons() -> None:
    cell = {"reductions": {"after": {"joint_position": [0.5] * 10, "object_position": [0.4] * 10}}}
    low = {
        "reductions": {
            "after": {"joint_position": [0.5] * 9 + [-0.2], "object_position": [0.4] * 10}
        }
    }
    spot = worst({"seeds": {"0": cell, "1": low}})
    assert spot == {"value": -0.2, "seed": "1", "stream": "joint_position", "horizon": 10}


def test_a_second_run_is_refused(tmp_path: Path) -> None:
    check_not_run(tmp_path)
    (tmp_path / "r").mkdir()
    (tmp_path / "r" / "m3_remeasure.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="one result"):
        check_not_run(tmp_path)
