"""Branch chunks, states and constraint violations. Every trajectory here is FABRICATED."""

from __future__ import annotations

import pytest

from vishwaroop.scoring.violations import margins, task_cost, violated
from vishwaroop.sim.branches import CHUNK, make_chunks, run_chunk, select_states
from vishwaroop.sim.so100_kinematics import tool_point

JOINTS = [0.035, 0.038, -0.042, 1.568, 1.582, -0.3]
LOWER = [-2.0, -1.6, -1.6, -1.8, -3.2, -1.0]
UPPER = [2.0, 1.6, 1.6, 1.8, 3.2, 0.0]


def _state(cube: list[float], flag: float, joints: list[float] | None = None) -> list[float]:
    return [*(joints or JOINTS), *cube, 0.2, 0.0, 0.0, flag]


def test_a_free_cube_pushed_more_than_10_mm_is_a_knock() -> None:
    states = [_state([0.1 + 0.0021 * i, 0.0, 0.0125], 0.0) for i in range(6)]
    assert margins(states)["knock"] == pytest.approx(1.05)
    assert violated(margins(states))
    assert not violated(margins(states[:4]))


def test_a_carried_cube_moving_is_not_a_knock() -> None:
    states = [_state([0.1 + 0.01 * i, 0.0, 0.05], 1.0) for i in range(6)]
    assert margins(states)["knock"] == 0.0


def test_a_release_high_and_away_from_the_target_is_a_drop() -> None:
    held = _state([0.1, 0.0, 0.05], 1.0)
    dropped = _state([0.1, 0.0, 0.05], 0.0)
    assert margins([held, dropped])["drop"] > 1.0
    over_target = _state([0.2, 0.0, 0.05], 0.0)
    assert margins([held, over_target])["drop"] == 0.0
    low = _state([0.1, 0.0, 0.03], 0.0)
    assert margins([held, low])["drop"] < 1.0


def test_the_table_margin_crosses_one_below_5_mm() -> None:
    height = tool_point(JOINTS)[2]
    scaled = margins([_state([0.1, 0.0, 0.0125], 0.0)] * 2)["table"]
    assert scaled == pytest.approx(0.005 / height)


def test_bad_states_are_refused() -> None:
    with pytest.raises(ValueError, match="start"):
        margins([_state([0.1, 0.0, 0.0125], 0.0)])
    with pytest.raises(ValueError, match="13 finite"):
        margins([_state([0.1, 0.0, float("nan")], 0.0)] * 2)


def test_task_cost_adds_tool_to_cube_and_cube_to_target() -> None:
    tool = tool_point(JOINTS)
    state = _state(list(tool), 0.0)
    assert task_cost(state) == pytest.approx(
        ((tool[0] - 0.2) ** 2 + tool[1] ** 2 + tool[2] ** 2) ** 0.5
    )


def test_chunks_are_four_clipped_and_reproducible() -> None:
    recorded = [list(JOINTS)] * CHUNK
    first = make_chunks(recorded, 8000, 7, LOWER, UPPER)
    assert first == make_chunks(recorded, 8000, 7, LOWER, UPPER)
    assert len(first) == 4
    assert first[0] == recorded
    assert first[1] != first[2]
    assert all(
        low <= v <= high
        for chunk in first
        for action in chunk
        for v, low, high in zip(action, LOWER, UPPER, strict=True)
    )
    assert {action[5] for action in first[3]} == {-0.8}
    with pytest.raises(ValueError, match="chunk"):
        make_chunks(recorded[:3], 8000, 7, LOWER, UPPER)


def test_states_come_twenty_per_family_from_long_enough_episodes() -> None:
    entries = [{"episode_id": f"{f}-{s}", "family": f, "seed": s} for f in "ab" for s in range(25)]
    lengths = {e["episode_id"]: (15 if e["seed"] == 0 else 60) for e in entries}
    chosen = select_states(entries, lengths)
    assert len(chosen) == 40
    assert "a-0" not in {name for name, _ in chosen}
    assert all(3 <= step <= 60 - 11 for _, step in chosen)


class _FakeEnv:
    """Joints follow the action; nothing else moves. Fabricated."""

    def __init__(self, offset: float = 0.0) -> None:
        self.offset = offset
        self.joints = list(JOINTS)

    def _packet(self) -> dict[str, list[float]]:
        return {
            "joint_position": list(self.joints),
            "object_position": [0.1, 0.0, 0.0125],
            "target_position": [0.2, 0.0, 0.0],
            "object_grasped": [0.0],
        }

    def restore_state(self, state: bytes) -> dict[str, list[float]]:
        self.joints = [v + self.offset for v in JOINTS]
        return self._packet()

    def step(self, action: list[float]) -> dict[str, list[float]]:
        self.joints = list(action)
        return self._packet()


def test_a_reached_state_that_differs_from_the_recording_is_refused() -> None:
    from vishwaroop.models.pilot_data import EpisodeArrays

    states = [_state([0.1, 0.0, 0.0125], 0.0)] * 5
    episode = EpisodeArrays(seed=8000, states=states, actions=[list(JOINTS)] * 4)
    assert len(run_chunk(_FakeEnv(), episode, 0, [list(JOINTS)] * 2, b"{}")) == 3
    with pytest.raises(ValueError, match="differs"):
        run_chunk(_FakeEnv(offset=0.002), episode, 0, [list(JOINTS)] * 2, b"{}")
    assert len(run_chunk(_FakeEnv(offset=0.0009), episode, 0, [list(JOINTS)] * 2, b"{}")) == 3
