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
