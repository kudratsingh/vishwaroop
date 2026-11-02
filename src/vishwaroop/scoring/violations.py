"""Constraint violations and task cost for one action chunk, from states alone (WO-005).

Frozen in ``evals/M1-planner-scorer.json`` before any result. A state is the 13 values of
``pilot_data.STATE_STREAMS``: 6 joints (rad), cube (m), target (m), grasp flag. The table top is
at height 0. Each margin is scaled by its own limit, so a margin above 1 is a violation. The same
functions score the simulator's states and a model's predicted ones. Standard library only.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise

from ..sim.so100_kinematics import tool_point

KNOCK_M = 0.010
DROP_HEIGHT_M = 0.030
TARGET_RADIUS_M = 0.015625  # evals/M0-exit-tests.json
TABLE_CLEARANCE_M = 0.005
REST_HEIGHT_M = 0.0125
HELD = 0.5

State = Sequence[float]


def _cube(state: State) -> tuple[float, float, float]:
    return (state[6], state[7], state[8])


def _held(state: State) -> bool:
    return state[12] >= HELD


def margins(states: Sequence[State]) -> dict[str, float]:
    """Knock, drop and table margins over a chunk's states, the first being where it starts."""
    if len(states) < 2:
        raise ValueError("a chunk needs its start and at least one step")
    if any(len(state) != 13 or not all(map(math.isfinite, state)) for state in states):
        raise ValueError("a state is not 13 finite values")
    knock = 0.0
    drop = 0.0
    table = 0.0
    for before, after in pairwise(states):
        a, b = _cube(before), _cube(after)
        if not _held(before) and not _held(after):
            knock += math.hypot(b[0] - a[0], b[1] - a[1])
        if _held(before) and not _held(after):
            height = (b[2] - REST_HEIGHT_M) / DROP_HEIGHT_M
            away = math.hypot(b[0] - after[9], b[1] - after[10]) / TARGET_RADIUS_M
            drop = max(drop, min(height, away))
        tool_height = tool_point(after[:6])[2]
        table = max(table, TABLE_CLEARANCE_M / max(tool_height, 1e-6))
    return {"knock": knock / KNOCK_M, "drop": drop, "table": table}


def violated(scaled: dict[str, float]) -> bool:
    """Any margin strictly beyond its limit."""
    return any(value > 1.0 for value in scaled.values())


def task_cost(state: State) -> float:
    """The tool point's distance to the cube plus the cube's distance to the target, in metres."""
    tool = tool_point(state[:6])
    cube = _cube(state)
    target = (state[9], state[10], state[11])
    return math.dist(tool, cube) + math.dist(cube, target)
