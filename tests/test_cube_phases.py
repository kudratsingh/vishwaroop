"""Phase labels and the hold-against-carry table, with no torch. Trajectories are FABRICATED."""

from __future__ import annotations

import math

import pytest

from vishwaroop.models.cube_phases import (
    WINDOW_PHASES,
    episode_window_phases,
    reductions,
    step_phase,
    step_table,
    window_phase,
)
from vishwaroop.sim.so100_kinematics import tool_point

TARGET = [0.2, 0.0, 0.05]


def _state(joints: list[float], cube: list[float], flag: float) -> list[float]:
    return [*joints, *cube, *TARGET, flag]


def _joints(step: int) -> list[float]:
    return [0.01 * step, 0.4, 0.2, 1.0, 1.57, -0.8]


def _carried_episode(steps: int) -> list[list[float]]:
    """A grasped cube fixed to the tool point, so carrying should explain all of its motion."""
    offset = [0.001, 0.0, 0.0]
    states = []
    for step in range(steps):
        tool = tool_point(_joints(step))
        states.append(
            _state(_joints(step), [a + b for a, b in zip(tool, offset, strict=True)], 1.0)
        )
    return states


@pytest.mark.parametrize(
    ("flags", "moved", "before", "expected"),
    [
        ([False, False], False, False, "resting"),
        ([False, False], False, True, "resting"),
        ([False, False], True, False, "moved_before_grasp"),
        ([False, False], True, True, "moved_after_grasp"),
        ([False, True], True, False, "grasp_onset"),
        ([True, True], True, True, "held"),
        ([True, False], True, True, "release"),
    ],
)
def test_each_window_phase(flags: list[bool], moved: bool, before: bool, expected: str) -> None:
    assert window_phase(flags, moved, before) == expected
    assert expected in WINDOW_PHASES


def test_an_empty_window_is_refused() -> None:
    with pytest.raises(ValueError, match="first state"):
        window_phase([], False, False)


def test_window_phases_line_up_with_the_pilot_windows() -> None:
    joints = _joints(0)
    still = [0.1, 0.1, 0.0125]
    falling = [0.1, 0.1, 0.03]
    states = (
        [_state(joints, still, 0.0)] * 2
        + [_state(joints, still, 1.0)] * 2
        + [_state(joints, falling, 0.0)]
        + [_state(joints, still, 0.0)] * 2
    )
    phases = episode_window_phases(states, history=1, horizon=1)
    assert phases == [
        "grasp_onset",  # rollout starts at index 1, and the flag is on at index 2
        "held",
        "release",
        "moved_after_grasp",
        "resting",
    ]
    assert len(phases) == len(states) - 3 + 1


def test_a_short_episode_has_no_windows() -> None:
    assert episode_window_phases([_state(_joints(0), [0.1, 0.1, 0.0], 0.0)], 3, 10) == []


def test_step_phases() -> None:
    assert step_phase(False, False, False, False) == "resting"
    assert step_phase(False, False, True, False) == "moved_before_grasp"
    assert step_phase(False, False, True, True) == "moved_after_grasp"
    assert step_phase(False, True, False, False) == "flag_turns_on"
    assert step_phase(True, True, False, True) == "held"
    assert step_phase(True, False, True, True) == "flag_turns_off"


def test_carry_explains_a_cube_fixed_to_the_tool() -> None:
    table = step_table([_carried_episode(20)])
    held = table["phases"]["held"]
    assert held["steps"] == 19
    assert held["share_of_squared_motion"] == pytest.approx(1.0)
    assert held["hold_rms_mm"] > 1.0
    assert held["carry_rms_mm"] == pytest.approx(0.0, abs=1e-9)


def test_carry_is_wrong_for_a_cube_left_on_the_table() -> None:
    joints = [_joints(step) for step in range(5)]
    states = [_state(item, [0.1, 0.1, 0.0125], 0.0) for item in joints]
    resting = step_table([states])["phases"]["resting"]
    assert resting["steps"] == 4
    assert resting["hold_rms_mm"] == 0.0
    assert resting["carry_rms_mm"] > 0.5


def test_a_table_with_no_transitions_is_refused() -> None:
    with pytest.raises(ValueError, match="no transitions"):
        step_table([])


def test_reductions_use_the_best_baseline_at_each_horizon() -> None:
    values = reductions([0.8, 1.0], [[1.0, 4.0], [2.0, 2.0]])
    assert values[0] == pytest.approx(0.2)
    assert values[1] == pytest.approx(0.5)


def test_reductions_refuse_mismatched_horizons() -> None:
    with pytest.raises(ValueError, match="horizons"):
        reductions([1.0], [[1.0, 2.0]])


def test_carry_step_is_finite_for_a_single_step_episode() -> None:
    table = step_table([_carried_episode(2)])
    assert math.isfinite(table["phases"]["held"]["carry_rms_mm"])


def test_torch_carry_moves_the_cube_only_when_the_flag_is_on() -> None:
    torch = pytest.importorskip("torch")
    from vishwaroop.models.cube_study import Variant, _Kinematics, _step, largest_gap_m

    assert largest_gap_m("cpu") < 1e-4
    stats = {
        "state_mean": torch.zeros(13),
        "state_std": torch.ones(13),
        "delta_std": torch.ones(13),
        "lag": torch.ones(6),
        "action_mean": torch.zeros(6),
        "action_std": torch.ones(6),
        "kinematics": _Kinematics("cpu"),
    }
    cube = [0.1, 0.1, 0.0125]
    state = torch.tensor([[_state(_joints(0), cube, 1.0)]], dtype=torch.float32)
    action = torch.tensor([[_joints(5)]], dtype=torch.float32)
    pair = 19
    history = torch.zeros(1, 1, 3 * pair)
    layers = [(torch.zeros(1, pair + 3 * pair, 26), torch.zeros(1, 1, 26))]
    variant = Variant(carry=True, contact=False, beta=0.0)
    on, _ = _step(stats, variant, layers, history, state, action)
    off, _ = _step(stats, variant, layers, history, state, action, torch.zeros(1, 1, 1))
    moved = [b - a for a, b in zip(tool_point(_joints(0)), tool_point(_joints(5)), strict=True)]
    expected = [a + b for a, b in zip(cube, moved, strict=True)]
    assert on[0, 0, 6:9].tolist() == pytest.approx(expected, abs=2e-5)
    assert off[0, 0, 6:9].tolist() == pytest.approx(cube, abs=1e-6)
