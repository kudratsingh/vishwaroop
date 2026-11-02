"""WO-016's retest: refusals and the calibrated spread. Data here is FABRICATED."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from vishwaroop.scoring.score_et5_retest import (
    CALIBRATION_BRANCHES,
    EVALUATION_BRANCHES,
    RULES,
    RULES_SHA256,
    check_not_run,
    load_checked,
)


def test_the_rules_are_the_frozen_ones(root: Path) -> None:
    rules = load_checked(root / RULES, RULES_SHA256)
    assert rules["changes_a_threshold"] is False


def test_calibration_and_evaluation_are_different_data() -> None:
    assert CALIBRATION_BRANCHES != EVALUATION_BRANCHES


def test_a_changed_input_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "b.json"
    path.write_text("{}", encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert load_checked(path, digest) == {}
    path.write_text('{"a": 1}', encoding="utf-8")
    with pytest.raises(ValueError, match="frozen"):
        load_checked(path, digest)


def test_a_second_scoring_is_refused(tmp_path: Path) -> None:
    check_not_run(tmp_path)
    (tmp_path / "r").mkdir()
    (tmp_path / "r" / "et5_retest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="one scoring"):
        check_not_run(tmp_path)


def test_torch_cube_spread_is_the_scaled_root_mean_square_at_the_last_step() -> None:
    torch = pytest.importorskip("torch")
    from vishwaroop.scoring.score_et5_retest import cube_spread

    std = torch.zeros(2, 10, 13)
    std[0, -1, 6:9] = torch.tensor([1.0, 2.0, 2.0])
    std[1, 0, 6:9] = 5.0  # an earlier step does not count
    assert cube_spread(std, 2.0) == pytest.approx([2.0 * 3.0**0.5, 0.0])
