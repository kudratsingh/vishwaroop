"""The planner's stage rule and the suite's seed ranges. States are FABRICATED."""

from __future__ import annotations

import pytest

from vishwaroop.planning.cem import APPROACH, CARRY, CLOSE, DESCEND, PLACE, RISE, Settings, stage_of
from vishwaroop.planning.suite import SUITE_SEEDS, TUNING_SEEDS, parse_seeds

SETTINGS = Settings()


def _state(
    cube: tuple[float, float, float], target: tuple[float, float, float], flag: float
) -> list[float]:
    return [0.0] * 6 + list(cube) + list(target) + [flag]


def test_each_stage_follows_from_the_real_state() -> None:
    cube, target = (0.2, 0.0, 0.0125), (0.1, 0.1, 0.0)
    free = _state(cube, target, 0.0)
    assert stage_of(free, (0.3, 0.1, 0.1), SETTINGS, False) == APPROACH
    assert stage_of(free, (0.2, 0.0, 0.06), SETTINGS, False) == DESCEND
    assert stage_of(free, (0.2, 0.0, 0.0125), SETTINGS, False) == CLOSE
    held = _state(cube, target, 1.0)
    assert stage_of(held, cube, SETTINGS, True) == CARRY
    over = _state((0.1, 0.1, 0.03), target, 1.0)
    assert stage_of(over, (0.1, 0.1, 0.03), SETTINGS, True) == PLACE


def test_a_cube_on_the_target_is_done_only_after_it_was_carried() -> None:
    on_target = _state((0.1, 0.1, 0.0125), (0.1, 0.1, 0.0), 0.0)
    assert stage_of(on_target, (0.3, 0.3, 0.1), SETTINGS, True) == RISE
    assert stage_of(on_target, (0.3, 0.3, 0.1), SETTINGS, False) == APPROACH


def test_suite_and_tuning_seeds_stay_apart_and_in_their_ranges() -> None:
    assert not set(SUITE_SEEDS) & set(TUNING_SEEDS)
    assert len(SUITE_SEEDS) == 200
    assert parse_seeds("", tuning=False) == list(SUITE_SEEDS)
    assert parse_seeds("5000:5008", tuning=True) == list(range(5000, 5008))
    with pytest.raises(ValueError, match="outside"):
        parse_seeds("9100:9110", tuning=True)
    with pytest.raises(ValueError, match="outside"):
        parse_seeds("5000:5010", tuning=False)


def test_torch_an_episode_decides_the_same_whatever_ran_before_it() -> None:
    """What a resumed suite needs: each episode's draws depend only on its own seed."""
    torch = pytest.importorskip("torch")
    from vishwaroop.models.compute_pilot import MEMBERS, _new_ensemble
    from vishwaroop.models.cube_study import _Kinematics
    from vishwaroop.planning.cem import Planner

    torch.manual_seed(0)
    layers = [(w.detach(), b.detach()) for w, b in _new_ensemble([19 + 3 * 19 + 3, 8, 26])]
    assert layers[0][0].shape[0] == MEMBERS
    stats = {
        "state_mean": torch.zeros(13),
        "state_std": torch.ones(13),
        "delta_std": torch.ones(13),
        "lag": torch.full((6,), 0.5),
        "action_mean": torch.zeros(6),
        "action_std": torch.ones(6),
        "kinematics": _Kinematics("cpu"),
    }
    settings = Settings(samples=16, iterations=2)
    state = [0.035, 0.038, -0.042, 1.568, 1.582, -0.3, 0.2, 0.0, 0.0125, 0.1, 0.1, 0.0, 0.0]
    history = [state] * 4
    actions = [state[:6]] * 3
    lower, upper = [-3.0] * 6, [3.0] * 6

    def first_action(before: int | None) -> list[float]:
        planner = Planner(
            stats,
            layers,
            "carry-contact-beta-fall-still-reach",
            settings,
            lower,
            upper,
            None,
            "cpu",
            0,
        )
        if before is not None:
            planner.reset(before)
            planner.decide(history, actions, (0.3, 0.1, 0.1))
        planner.reset(9100)
        return planner.decide(history, actions, (0.3, 0.1, 0.1))[0]

    assert first_action(None) == first_action(9099)
