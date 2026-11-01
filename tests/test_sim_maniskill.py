"""Simulator-tier tests for the real adapter. Skipped unless the pinned stack is present and starts.

A skip here means **not run**, never passed (AGENTS.md section 4.5).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from vishwaroop.outcome.pickplace import samples_from_episode
from vishwaroop.sim.env import ManiSkillPickCube, SimEnv, SimulatorUnavailableError
from vishwaroop.sim.record import record_scripted
from vishwaroop.sim.replay import load_frozen, replay_episode

FROZEN = Path(__file__).resolve().parents[1] / "evals" / "M0-exit-tests.json"

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


@pytest.mark.parametrize(
    ("variant", "label"),
    [
        ("nominal", "success"),
        ("missed-grasp", "never_lifted"),
        ("no-release", "still_grasped"),
        ("wrong-place", "outside_target"),
    ],
)
def test_a_scripted_episode_gets_its_label_and_replays_exactly(
    env: ManiSkillPickCube, tmp_path: Path, variant: str, label: str
) -> None:
    episode = record_scripted(env, 12, variant, "sim-tier-test", FROZEN, tmp_path)
    tolerance, rubric = load_frozen(FROZEN)
    assert samples_from_episode(episode)
    report = replay_episode(episode, env, tolerance, rubric)
    assert report.claim_valid, report.reason
    assert report.recorded_label == label
    assert [repeat.max_deviation for repeat in report.repeats] == [0.0, 0.0, 0.0]
