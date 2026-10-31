"""Simulator-tier tests for the real adapter. Skipped unless the pinned stack is present and starts.

A skip here means **not run**, never passed (AGENTS.md section 4.5).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from vishwaroop.sim.env import ManiSkillPickCube, SimEnv, SimulatorUnavailableError

pytestmark = pytest.mark.sim


@pytest.fixture(scope="module")
def env() -> Iterator[ManiSkillPickCube]:
    pytest.importorskip("mani_skill")
    try:
        yield ManiSkillPickCube()
    except SimulatorUnavailableError as exc:
        pytest.skip(f"not run: {exc}")


def test_adapter_implements_the_interface(env: ManiSkillPickCube) -> None:
    assert isinstance(env, SimEnv)
    assert env.action_spec.labels


def test_restoring_the_saved_state_returns_the_same_packet(env: ManiSkillPickCube) -> None:
    first = env.reset(7)
    state = env.save_state()
    assert env.restore_state(state) == first
