"""ET-M3-6's frozen scoring arithmetic on FABRICATED RMSE tables; no torch, no data."""

from __future__ import annotations

import math
from typing import Any

import pytest

from vishwaroop.models.et_m3_6_rule import (
    MARGIN,
    NO_HELP_FROM_TARGET_DATA,
    UNDEFINED,
    RuleInputError,
    gap_fraction,
    helps,
    same_to_six_figures,
    score,
    strictly_below,
    worst_reduction,
)

SEEDS = ("0", "1", "2")
STREAMS = ("joint_position", "object_position")


def table(value: float | list[float]) -> dict[str, dict[str, list[float]]]:
    values = value if isinstance(value, list) else [value] * 10
    return {seed: {stream: list(values) for stream in STREAMS} for seed in SEEDS}


def baselines(lowest: float) -> dict[str, dict[str, list[float]]]:
    names = ("constant", "linear", "nominal_hold", "nominal_carry", "nominal_carry_fall")
    return {
        name: {stream: [lowest + index] * 10 for stream in STREAMS}
        for index, name in enumerate(names)
    }


def test_equal_to_six_significant_figures_counts_as_not_below() -> None:
    assert same_to_six_figures(0.0123456, 0.01234564)
    assert not strictly_below(0.0123456, 0.01234564)  # below, but equal to 6 figures
    assert strictly_below(0.0123450, 0.0123460)
    assert not strictly_below(0.5, 0.5)
    assert not strictly_below(0.6, 0.5)
    assert strictly_below(1.23455e-5, 1.23465e-5)
    assert not strictly_below(1.234561e-5, 1.234564e-5)
    assert strictly_below(1.234564e-5, 1.234566e-5)  # 1.23456e-5 against 1.23457e-5


def test_one_cell_equal_to_six_figures_fails_part_a() -> None:
    reference = table(0.0123456)
    arm = table(0.0100000)
    arm["2"]["object_position"][9] = 0.01234564
    result = helps(arm, reference, w_arm=0.5, w_f0=0.5)
    assert not result["a_below_reference_everywhere"] and not result["helps"]
    assert result["a_cells_not_below"] == [
        {
            "seed": "2",
            "stream": "object_position",
            "horizon": 10,
            "arm": 0.01234564,
            "reference": 0.0123456,
        }
    ]


def test_part_a_passes_strictly_below_everywhere() -> None:
    result = helps(table(0.009), table(0.010), w_arm=0.3, w_f0=0.3)
    assert result["helps"] and result["a_below_reference_everywhere"] and result["b_no_harm"]


def test_the_002_margin_edge() -> None:
    w_f0 = 0.31
    at_edge = w_f0 - MARGIN
    assert helps(table(0.009), table(0.010), at_edge, w_f0)["b_no_harm"]
    just_below = math.nextafter(at_edge, -math.inf)
    result = helps(table(0.009), table(0.010), just_below, w_f0)
    assert not result["b_no_harm"] and not result["helps"]


def test_w_is_the_minimum_over_seeds_horizons_and_streams_against_the_lowest_baseline() -> None:
    no_harm = table(0.5)
    no_harm["1"]["joint_position"][6] = 0.9
    w = worst_reduction(no_harm, baselines(1.0))
    assert w == {
        "value": pytest.approx(0.1),
        "seed": "1",
        "stream": "joint_position",
        "horizon": 7,
    }


def test_w_needs_the_five_baselines() -> None:
    four = dict(list(baselines(1.0).items())[:4])
    with pytest.raises(RuleInputError, match="five"):
        worst_reduction(table(0.5), four)


def test_the_gap_fraction_and_its_undefined_cells() -> None:
    f0 = table(0.010)
    f_star = table(0.006)
    arm = table(0.008)
    f_star["0"]["object_position"][0] = 0.010  # F0 - F_star = 0
    f_star["1"]["joint_position"][9] = 0.012  # F0 - F_star < 0
    result = gap_fraction(f0, arm, f_star)
    assert result["0"]["object_position"]["h1"] == UNDEFINED
    assert result["1"]["joint_position"]["h10"] == UNDEFINED
    assert result["2"]["joint_position"]["h1"] == pytest.approx(0.5)
    assert set(result["2"]["joint_position"]) == {"h1", "h10"}


def test_a_missing_seed_or_horizon_is_refused() -> None:
    short = table(0.01)
    short["1"]["joint_position"] = [0.01] * 9
    with pytest.raises(RuleInputError, match="10 horizons"):
        helps(short, table(0.02), 0.0, 0.0)
    missing = table(0.01)
    del missing["2"]
    with pytest.raises(RuleInputError, match="no seed 2"):
        helps(table(0.01), missing, 0.0, 0.0)


def _arms(**values: float) -> dict[str, Any]:
    return {arm: table(value) for arm, value in values.items()}


def test_score_reports_every_comparison_and_leaves_et_m3_6_to_f3() -> None:
    evaluation = _arms(F0=0.010, F_star=0.006, F1=0.009, F1s=0.0085, F2=0.007)
    no_harm = _arms(F0=0.5, F_star=0.5, F1=0.5, F1s=0.5, F2=0.5)
    result = score(evaluation, no_harm, baselines(1.0))
    assert set(result["comparisons"]) == {"F_star_vs_F1", "F2_vs_F1", "F2_vs_F1s"}
    assert result["comparisons"]["F2_vs_F1"]["helps"]
    assert result["comparisons"]["F2_vs_F1s"]["helps"]
    assert result["sensitivity"] == "F_star helps by the rule against F1"
    assert result["et_m3_6"].startswith("not decided")
    assert set(result["differences_f1_minus_fk"]) == {"F0", "F_star", "F1s", "F2"}
    assert result["differences_f1_minus_fk"]["F2"]["0"]["joint_position"][0] == pytest.approx(0.002)
    assert set(result["gap_fraction_closed"]) == {"F1", "F1s", "F2"}
    assert result["gap_fraction_closed"]["F2"]["0"]["object_position"]["h10"] == pytest.approx(0.75)


def test_f_star_not_helping_is_reported_as_the_frozen_sentence() -> None:
    evaluation = _arms(F0=0.010, F_star=0.009, F1=0.009, F2=0.007)
    no_harm = _arms(F0=0.5, F_star=0.5, F1=0.5, F2=0.5)
    result = score(evaluation, no_harm, baselines(1.0))
    assert result["sensitivity"] == NO_HELP_FROM_TARGET_DATA
    assert NO_HELP_FROM_TARGET_DATA == (
        "the rule could not detect help even from collected target data"
    )


def test_harm_on_the_no_harm_episodes_blocks_help() -> None:
    evaluation = _arms(F0=0.010, F_star=0.006, F1=0.009, F2=0.007)
    no_harm = _arms(F0=0.5, F_star=0.5, F1=0.5, F2=0.53)  # W(F2) = 0.47 < 0.5 - 0.02
    result = score(evaluation, no_harm, baselines(1.0))
    assert result["comparisons"]["F2_vs_F1"]["a_below_reference_everywhere"]
    assert not result["comparisons"]["F2_vs_F1"]["helps"]
