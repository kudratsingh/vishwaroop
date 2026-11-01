"""The SO-100 kinematics against values read from the running simulator.

The expected positions were measured on 2026-11-01 with ``mani_skill`` 3.0.1, by setting these joint
values in ``PickCubeSO100-v1`` and reading the two finger-tip links. No simulator runs here.
"""

from __future__ import annotations

import math

import pytest

from vishwaroop.sim.so100_kinematics import (
    approach_direction,
    fingertips,
    jaw_direction,
    solve_tool_down,
    tool_point,
)

LIMITS = [(-2.0, 2.0), (-1.5708, 1.5708), (-1.5708, 1.5708), (-1.8, 1.8)]
SEED = [0.0, 0.4, 0.2, 1.0, 1.5708, -0.8]


@pytest.mark.parametrize(
    ("joints", "expected"),
    [
        ([0.0, 0.0, 0.0, 0.0, 0.0, 0.0], (-0.338894, 0.0, 0.267353)),
        ([0.3, -0.5, 0.7, 0.6, 0.2, 0.4], (-0.432813, -0.068305, 0.138976)),
        ([-0.4, 0.8, -0.3, 1.0, -0.5, -0.8], (-0.433921, 0.101995, -0.039758)),
    ],
)
def test_tool_point_matches_the_simulator(
    joints: list[float], expected: tuple[float, float, float]
) -> None:
    assert math.dist(tool_point(joints), expected) < 5e-6


def test_each_fingertip_matches_the_simulator() -> None:
    fixed, moving = fingertips([0.0] * 6)
    assert math.dist(fixed, (-0.329199, 0.0, 0.226769)) < 5e-6
    assert math.dist(moving, (-0.348588, 0.0, 0.307936)) < 5e-6


@pytest.mark.parametrize(
    "target",
    [
        (-0.46, 0.0, 0.012),
        (-0.46, 0.0, 0.05),
        (-0.42, 0.05, 0.012),
        (-0.51, -0.05, 0.05),
        (-0.43, -0.05, 0.05),
    ],
)
def test_solver_reaches_the_task_area_with_the_jaws_straight_down(
    target: tuple[float, float, float],
) -> None:
    joints = solve_tool_down(target, SEED, limits=LIMITS)
    assert joints is not None
    assert math.dist(tool_point(joints), target) <= 0.0005
    assert approach_direction(joints)[2] < -0.999
    for value, (low, high) in zip(joints, LIMITS, strict=False):
        assert low <= value <= high
    assert joints[4:] == SEED[4:]


def test_solver_returns_none_out_of_reach() -> None:
    assert solve_tool_down((0.5, 0.5, 0.5), SEED, limits=LIMITS) is None


def test_the_far_edge_of_the_task_area_is_beyond_a_straight_down_pose() -> None:
    # The nominal plan's only failures in the first 40 seeds came from this limit.
    assert solve_tool_down((-0.40, -0.05, 0.05), SEED, limits=LIMITS) is None


def test_jaws_close_across_the_table_at_the_grasp_pose() -> None:
    joints = solve_tool_down((-0.46, 0.0, 0.012), SEED, limits=LIMITS)
    assert joints is not None
    assert abs(jaw_direction(joints)[2]) < 0.1


def test_jaw_direction_refuses_coincident_tips(monkeypatch: pytest.MonkeyPatch) -> None:
    import vishwaroop.sim.so100_kinematics as kinematics

    point = (0.0, 0.0, 0.0)
    monkeypatch.setattr(kinematics, "fingertips", lambda _: (point, point))
    with pytest.raises(ValueError, match="coincide"):
        jaw_direction(SEED)
