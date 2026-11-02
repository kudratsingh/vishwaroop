"""The free-cube rule and the dev calibration split. All data here is FABRICATED."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from vishwaroop.models.m1_followups import (
    PLAN_PATH,
    PLAN_SHA256,
    check_not_run,
    check_plan,
    folds,
    never_worse,
)
from vishwaroop.models.pilot_data import EpisodeArrays


def test_the_frozen_follow_up_plan_is_the_one_the_code_requires(root: Path) -> None:
    plan = check_plan(root / PLAN_PATH)
    assert plan["changes_a_threshold"] is False
    assert hashlib.sha256((root / PLAN_PATH).read_bytes()).hexdigest() == PLAN_SHA256


def test_a_second_run_is_refused(tmp_path: Path) -> None:
    check_not_run(tmp_path)
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "m1_followups.json.partial").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="already run"):
        check_not_run(tmp_path)


def _episode(family: str, seed: int) -> EpisodeArrays:
    return EpisodeArrays(seed=seed, states=[], actions=[], family=family)


def test_folds_alternate_by_seed_within_each_family() -> None:
    episodes = [_episode("b", 5), _episode("a", 9), _episode("a", 3), _episode("b", 1)]
    assert folds(episodes) == [1, 1, 0, 0]


def test_never_worse_allows_equal_and_refuses_one_horizon_above() -> None:
    assert never_worse([1.0, 2.0], [1.0, 2.0])
    assert not never_worse([1.0, 2.0001], [1.0, 2.0])
    with pytest.raises(ValueError, match="horizons"):
        never_worse([1.0], [1.0, 2.0])


def _state(torch: object, height: float, flag: float) -> object:
    state = torch.zeros(1, 13)  # type: ignore[attr-defined]
    state[0, 6:9] = torch.tensor([0.1, 0.1, 0.0125 + height])  # type: ignore[attr-defined]
    state[0, 12] = flag
    return state


def test_torch_a_free_cube_on_the_table_stays_exactly_put() -> None:
    torch = pytest.importorskip("torch")
    from vishwaroop.models.cube_study import hold_free_cube

    state = _state(torch, 0.0, 0.0)
    prediction = state.clone()
    prediction[0, 6:9] += torch.tensor([0.003, -0.002, 0.001])
    prediction[0, :6] += 0.01
    kept = hold_free_cube(prediction, state, state[..., 12:13])
    assert torch.equal(kept[0, 6:9], state[0, 6:9])
    assert torch.equal(kept[0, :6], prediction[0, :6])  # the joints are untouched


def test_torch_a_held_or_falling_cube_is_left_to_the_model() -> None:
    torch = pytest.importorskip("torch")
    from vishwaroop.models.cube_study import hold_free_cube

    for height, flag in ((0.0, 1.0), (0.0, 0.5), (0.03, 0.0)):
        state = _state(torch, height, flag)
        prediction = state.clone()
        prediction[0, 6:9] += 0.004
        kept = hold_free_cube(prediction, state, state[..., 12:13])
        assert torch.equal(kept, prediction), (height, flag)


def test_torch_a_cube_just_inside_the_margin_counts_as_resting() -> None:
    torch = pytest.importorskip("torch")
    from vishwaroop.models.cube_study import hold_free_cube

    state = _state(torch, 0.0009, 0.4)
    prediction = state.clone()
    prediction[0, 6:9] += 0.004
    kept = hold_free_cube(prediction, state, state[..., 12:13])
    assert torch.equal(kept[0, 6:9], state[0, 6:9])
