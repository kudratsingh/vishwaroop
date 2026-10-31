"""The independent place rubric. All inputs here are FABRICATED, not measured episodes."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

from vishwaroop.interfaces import SuccessJudge
from vishwaroop.outcome.pickplace import (
    PickPlaceJudge,
    PlaceRubric,
    StateSample,
    assess,
)

RUBRIC = PlaceRubric(
    rubric_version="test",
    target_radius_m=0.015625,
    rest_height_m=0.0125,
    rest_height_tolerance_m=0.005,
    min_lift_above_rest_m=0.02,
    max_step_motion_m=0.001,
    dwell_steps=10,
)
TARGET = (0.1, 0.0, 0.0125)


def _samples(
    final: tuple[float, float, float] = TARGET,
    *,
    lifted: bool = True,
    grasped_at_end: bool = False,
    dwell: int = 10,
) -> list[StateSample]:
    """A lift, then ``dwell`` samples at ``final``."""
    height = 0.08 if lifted else 0.0125
    path = [(0.0, 0.0, 0.0125), (0.05, 0.0, height), (0.1, 0.0, height)]
    samples = [StateSample(i, p, TARGET, True) for i, p in enumerate(path)]
    start = len(samples)
    samples += [StateSample(start + i, final, TARGET, grasped_at_end) for i in range(dwell)]
    return samples


def test_success() -> None:
    outcome = assess(_samples(), RUBRIC)
    assert outcome.success is True
    assert outcome.label == "success"


def test_never_lifted_is_a_failure_even_when_pushed_into_the_target() -> None:
    outcome = assess(_samples(lifted=False), RUBRIC)
    assert (outcome.success, outcome.label) == (False, "never_lifted")


def test_still_grasped_fails() -> None:
    outcome = assess(_samples(grasped_at_end=True), RUBRIC)
    assert (outcome.success, outcome.label) == (False, "still_grasped")


def test_held_in_the_air_over_the_target_fails() -> None:
    outcome = assess(_samples((0.1, 0.0, 0.05)), RUBRIC)
    assert (outcome.success, outcome.label) == (False, "not_on_table")


def test_outside_target_fails() -> None:
    outcome = assess(_samples((0.2, 0.0, 0.0125)), RUBRIC)
    assert (outcome.success, outcome.label) == (False, "outside_target")


def test_exactly_on_the_radius_passes_and_just_outside_fails() -> None:
    on_edge = (TARGET[0] + RUBRIC.target_radius_m, 0.0, 0.0125)
    assert assess(_samples(on_edge), RUBRIC).success is True
    outside = (TARGET[0] + RUBRIC.target_radius_m + 1e-6, 0.0, 0.0125)
    assert assess(_samples(outside), RUBRIC).label == "outside_target"


def test_still_moving_fails() -> None:
    samples = _samples()
    last = samples[-1]
    samples[-1] = StateSample(last.step, (0.1 + 0.002, 0.0, 0.0125), TARGET, False)
    outcome = assess(samples, RUBRIC)
    assert (outcome.success, outcome.label) == (False, "not_settled")


def test_too_few_samples_do_not_decide() -> None:
    samples = [StateSample(0, TARGET, TARGET, False)]
    outcome = assess(samples, RUBRIC)
    assert (outcome.success, outcome.label) == (None, "insufficient_evidence")


def test_an_invalid_sample_anywhere_does_not_decide() -> None:
    samples = _samples()
    samples[1] = StateSample(1, None, TARGET, True)
    outcome = assess(samples, RUBRIC)
    assert (outcome.success, outcome.label) == (None, "insufficient_evidence")


def test_rubric_refuses_missing_or_extra_keys() -> None:
    raw = {
        "rubric_version": "x",
        "target_radius_m": 1.0,
        "rest_height_m": 1.0,
        "rest_height_tolerance_m": 1.0,
        "min_lift_above_rest_m": 1.0,
        "max_step_motion_m": 1.0,
        "dwell_steps": 1,
    }
    assert PlaceRubric.from_mapping(raw).dwell_steps == 1
    with pytest.raises(ValueError, match="rubric keys"):
        PlaceRubric.from_mapping({**raw, "extra": 1})
    del raw["dwell_steps"]
    with pytest.raises(ValueError, match="rubric keys"):
        PlaceRubric.from_mapping(raw)


def test_frozen_rubric_loads() -> None:
    root = Path(__file__).resolve().parents[1]
    frozen = json.loads((root / "evals" / "M0-exit-tests.json").read_text(encoding="utf-8"))
    assert PlaceRubric.from_mapping(frozen["place_rubric"]).rubric_version == "m0-place-1"


def test_judge_implements_the_interface() -> None:
    assert isinstance(PickPlaceJudge(RUBRIC), SuccessJudge)


def test_outcome_code_imports_only_the_standard_library_and_itself() -> None:
    """ET-M0-4: the outcome shares nothing with a policy, a reward or a learned model."""
    outcome_dir = Path(__file__).resolve().parents[1] / "src" / "vishwaroop" / "outcome"
    assert list(outcome_dir.glob("*.py"))
    for path in outcome_dir.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    assert node.level == 1, f"{path.name} reaches outside the outcome package"
                    continue
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert name.split(".")[0] in sys.stdlib_module_names, f"{path.name}: {name}"
