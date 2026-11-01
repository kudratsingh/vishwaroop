"""Label what the cube is doing along a trajectory, with no simulator or torch.

These labels come from the true trajectory, so they are for analysis only and never model inputs.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from itertools import pairwise
from typing import Any

from ..sim.so100_kinematics import tool_point

JOINTS = 6
CUBE = (6, 9)
FLAG = 12
MOVED_M = 1e-4  # 0.1 mm in one step counts as a move
WINDOW_PHASES = (
    "resting",
    "moved_before_grasp",
    "moved_after_grasp",
    "grasp_onset",
    "held",
    "release",
)
STEP_PHASES = (
    "resting",
    "moved_before_grasp",
    "moved_after_grasp",
    "flag_turns_on",
    "held",
    "flag_turns_off",
)


def _cube(state: Sequence[float]) -> list[float]:
    return list(state[CUBE[0] : CUBE[1]])


def _grasped(state: Sequence[float]) -> bool:
    return state[FLAG] > 0.5


def _free_phase(moved: bool, grasped_before: bool) -> str:
    if not moved:
        return "resting"
    return "moved_after_grasp" if grasped_before else "moved_before_grasp"


def window_phase(flags: Sequence[bool], moved: bool, grasped_before: bool) -> str:
    """The phase of one rollout window. ``flags`` runs from the rollout's start to its last step."""
    if not flags:
        raise ValueError("a window needs at least its first state")
    if flags[0]:
        return "held" if all(flags) else "release"
    if any(flags):
        return "grasp_onset"
    return _free_phase(moved, grasped_before)


def episode_window_phases(
    states: Sequence[Sequence[float]], history: int, horizon: int
) -> list[str]:
    """One phase per window, in the order the pilot's window builder uses with stride 1."""
    length = history + horizon + 1
    if len(states) < length:
        return []
    flags = [_grasped(state) for state in states]
    phases = []
    for start in range(len(states) - length + 1):
        first = start + history
        last = first + horizon
        moved = any(
            math.dist(_cube(states[i]), _cube(states[i + 1])) >= MOVED_M for i in range(first, last)
        )
        phases.append(window_phase(flags[first : last + 1], moved, any(flags[:first])))
    return phases


def step_phase(flag_now: bool, flag_next: bool, moved: bool, grasped_before: bool) -> str:
    """The phase of one transition."""
    if flag_now:
        return "held" if flag_next else "flag_turns_off"
    if flag_next:
        return "flag_turns_on"
    return _free_phase(moved, grasped_before)


def step_table(episodes: Iterable[Sequence[Sequence[float]]]) -> dict[str, Any]:
    """Hold against carry, for one step, using the true next joints. Distances are in millimetres.

    This is the best a carrying nominal could do: a trained model has to predict the joints too.
    """
    count = dict.fromkeys(STEP_PHASES, 0)
    motion = dict.fromkeys(STEP_PHASES, 0.0)
    carry = dict.fromkeys(STEP_PHASES, 0.0)
    for states in episodes:
        grasped_before = False
        tool = tool_point(states[0][:JOINTS])
        for now, following in pairwise(states):
            next_tool = tool_point(following[:JOINTS])
            displacement = [b - a for a, b in zip(_cube(now), _cube(following), strict=True)]
            step = math.hypot(*displacement)
            phase = step_phase(_grasped(now), _grasped(following), step >= MOVED_M, grasped_before)
            count[phase] += 1
            motion[phase] += step * step
            carry[phase] += sum(
                (moved - (b - a)) ** 2
                for moved, a, b in zip(displacement, tool, next_tool, strict=True)
            )
            grasped_before = grasped_before or _grasped(now)
            tool = next_tool
    total_steps = sum(count.values())
    total_motion = sum(motion.values())
    if not total_steps:
        raise ValueError("no transitions")

    def rms_mm(value: float, phase: str) -> float:
        return 1000.0 * math.sqrt(value / count[phase]) if count[phase] else 0.0

    return {
        "steps": total_steps,
        "phases": {
            phase: {
                "steps": count[phase],
                "share_of_steps": count[phase] / total_steps,
                "share_of_squared_motion": motion[phase] / total_motion if total_motion else 0.0,
                "hold_rms_mm": rms_mm(motion[phase], phase),
                "carry_rms_mm": rms_mm(carry[phase], phase),
            }
            for phase in STEP_PHASES
        },
    }


def reductions(model: Sequence[float], baselines: Iterable[Sequence[float]]) -> list[float]:
    """Reduction against the best baseline at each horizon, as ET-M1-1 words it."""
    best = [min(values) for values in zip(*baselines, strict=True)]
    if len(best) != len(model):
        raise ValueError("model and baselines cover different horizons")
    return [1.0 - error / reference for error, reference in zip(model, best, strict=True)]
