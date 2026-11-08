"""The goal-envelope analysis's geometry on FABRICATED inputs. Standard library only."""

from __future__ import annotations

import math

import pytest

from vishwaroop.synth import goal_envelope_analysis as ga


def test_segment_rho() -> None:
    assert ga.segment_rho(1.0) == 0.0 and ga.segment_rho(1.2) == 0.0
    assert ga.segment_rho(0.5) == pytest.approx(4 / (3 * math.pi), rel=1e-9)
    assert ga.segment_rho(0.9) < ga.segment_rho(0.5) < ga.segment_rho(0.1) < 1.0
    assert ga.segment_rho(1e-9) == pytest.approx(1.0, abs=1e-2)


def test_projected_radius() -> None:
    manifest = {
        "goal_position": [0.0, 0.0, 1.0],
        "camera": {
            "extrinsic_cv": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]],
            "intrinsic_cv": [[500.0, 0, 256], [0, 500.0, 256], [0, 0, 1]],
        },
    }
    expected = 500.0 * math.tan(math.asin(ga.GOAL_RADIUS_M / 1.0))
    assert ga.projected_radius_px(manifest) == pytest.approx(expected)


def test_a_shift_is_caught_only_outside_the_envelope() -> None:
    frame = {"d": (0.0, 0.0), "envelope": 2.0, "w": 0.95, "green": 1}
    assert not ga._caught(frame, (0, 3), 1.5)
    assert ga._caught(frame, (0, 4), 1.5)
    assert not ga._caught({"w": 0.0, "green": 0}, (0, 40), 1.5)
