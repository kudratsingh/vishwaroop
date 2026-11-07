"""The two operators' parameter rules, ET-M3-1's episode kinds, and leak rule 1. No simulator."""

from __future__ import annotations

import random
from dataclasses import replace

import pytest

from vishwaroop.sim.baseline import VARIANTS, PlanSettings
from vishwaroop.synth.operators import (
    CLOSE_HIGH,
    LATERAL_MISS,
    NOMINAL,
    LeakRuleError,
    check_leak_rule_1,
    close_high,
    et_m3_1_episodes,
    kind_for_seed,
    lateral_miss,
    lateral_sign,
)

DEFAULT = PlanSettings()


def test_lateral_miss_draws_its_offset_from_the_seed_along_y_only() -> None:
    for seed in (10001, 10905, 11000):
        d = random.Random(seed).uniform(0.02, 0.05)
        first = lateral_miss(seed, 1)
        second = lateral_miss(seed, 2)
        assert first.grasp_offset_xy_m == (0.0, d)
        assert second.grasp_offset_xy_m == (0.0, -d)
        assert 0.02 <= d <= 0.05
        assert replace(first, grasp_offset_xy_m=(0.0, 0.0)) == DEFAULT


def test_the_lateral_sign_alternates_by_its_own_episode_count() -> None:
    assert [lateral_sign(k) for k in range(1, 7)] == [1, -1, 1, -1, 1, -1]
    with pytest.raises(ValueError, match="starts at 1"):
        lateral_sign(0)


def test_close_high_closes_d_above_the_default_grasp_height() -> None:
    for seed in (10003, 10907, 11001):
        d = random.Random(seed).uniform(0.02, 0.04)
        settings = close_high(seed)
        assert settings.grasp_height_m == 0.012 + d
        assert 0.032 <= settings.grasp_height_m <= 0.052
        assert replace(settings, grasp_height_m=0.012) == DEFAULT


def test_even_seeds_are_nominal_and_odd_seeds_alternate_operators() -> None:
    kinds = [kind_for_seed(seed) for seed in range(10900, 10908)]
    assert kinds == [NOMINAL, LATERAL_MISS, NOMINAL, CLOSE_HIGH] * 2


def test_the_pilot_sequence_counts_lateral_misses_within_itself() -> None:
    episodes = et_m3_1_episodes(list(range(10900, 10920)))
    assert len(episodes) == 20
    nominal = [e for e in episodes if e.kind == NOMINAL]
    assert all(e.settings == VARIANTS["nominal"] and e.seed % 2 == 0 for e in nominal)
    lateral = [e for e in episodes if e.kind == LATERAL_MISS]
    assert [e.seed for e in lateral] == [10901, 10905, 10909, 10913, 10917]
    assert [e.k for e in lateral] == [1, 2, 3, 4, 5]
    assert [e.settings.grasp_offset_xy_m[1] > 0 for e in lateral] == [
        True,
        False,
        True,
        False,
        True,
    ]
    assert {e.family for e in lateral} == {"m3-synth-lateral-miss"}
    high = [e for e in episodes if e.kind == CLOSE_HIGH]
    assert [e.seed for e in high] == [10903, 10907, 10911, 10915, 10919]
    assert {e.family for e in high} == {"m3-synth-close-high"}
    assert all(e.k is None for e in high)
    assert episodes[1].to_json()["noise_seed"] == 10901


def test_a_sequence_must_be_ascending_and_distinct() -> None:
    with pytest.raises(ValueError, match="ascending"):
        et_m3_1_episodes([10002, 10001])
    with pytest.raises(ValueError, match="ascending"):
        et_m3_1_episodes([10001, 10001])


@pytest.mark.parametrize("name", sorted(VARIANTS))
def test_leak_rule_1_refuses_every_existing_family(name: str) -> None:
    with pytest.raises(LeakRuleError):
        check_leak_rule_1(VARIANTS[name])


@pytest.mark.parametrize(
    "settings",
    [
        PlanSettings(grasp_offset_xy_m=(-0.04, 0.0), grasp_height_m=0.04),
        PlanSettings(place_offset_xy_m=(-0.03, 0.0), grasp_height_m=0.04),
        PlanSettings(place_height_m=0.05, grasp_height_m=0.04),
        PlanSettings(arm_noise_rad=0.01, grasp_height_m=0.04),
        PlanSettings(arm_noise_rad=0.02, grasp_height_m=0.04),
        PlanSettings(grasp_offset_xy_m=(-0.012, 0.0), grasp_height_m=0.04),
        PlanSettings(place_offset_xy_m=(-0.016, 0.0), grasp_height_m=0.04),
        PlanSettings(arm_noise_rad=0.05),
        PlanSettings(arm_noise_rad=0.15),
    ],
)
def test_leak_rule_1_refuses_a_reproduced_family_or_branch_setting(settings: PlanSettings) -> None:
    with pytest.raises(LeakRuleError):
        check_leak_rule_1(settings)


def test_every_drawn_operator_setting_passes_leak_rule_1() -> None:
    for seed in range(10000, 10200):
        check_leak_rule_1(lateral_miss(seed, 1 + seed % 2))
        check_leak_rule_1(close_high(seed))
