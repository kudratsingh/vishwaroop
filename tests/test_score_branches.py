"""ET-M1-2's pair rule, ET-M1-5's AUROC and their intervals. All numbers are FABRICATED."""

from __future__ import annotations

from pathlib import Path

import pytest

from vishwaroop.scoring.score_branches import (
    auroc,
    bootstrap_auroc,
    check_not_run,
    pair_accuracy,
    wilson,
)


def test_pairs_closer_than_5_mm_are_excluded_and_a_predicted_tie_is_wrong() -> None:
    simulated = [0.10, 0.104, 0.12, 0.20]
    predicted = [0.10, 0.50, 0.12, 0.12]
    right, scored, excluded, contributing = pair_accuracy([(simulated, predicted)])
    assert excluded == 1  # 0.100 against 0.104
    assert scored == 5
    # right: (0,2) (0,3); wrong: (1,2) (1,3) reversed, (2,3) tied
    assert right == 2
    assert contributing == 1


def test_a_state_with_no_separated_pair_does_not_contribute() -> None:
    assert pair_accuracy([([0.1, 0.101], [0.2, 0.1])]) == (0, 0, 1, 0)
    with pytest.raises(ValueError, match="each chunk"):
        pair_accuracy([([0.1], [0.1, 0.2])])


def test_auroc_counts_ties_as_half() -> None:
    assert auroc([0.9, 0.1], [True, False]) == 1.0
    assert auroc([0.5, 0.5], [True, False]) == 0.5
    assert auroc([0.2, 0.8], [True, False]) == 0.0
    with pytest.raises(ValueError, match="both classes"):
        auroc([0.1], [True])


def test_wilson_brackets_the_share() -> None:
    low, high = wilson(80, 100)
    assert low < 0.8 < high
    assert low == pytest.approx(0.7112, abs=1e-3)
    with pytest.raises(ValueError, match="no trials"):
        wilson(0, 0)


def test_bootstrap_auroc_is_reproducible_and_brackets_a_clear_case() -> None:
    groups = [[(0.9, True), (0.1, False)], [(0.8, True), (0.3, False)], [(0.2, False)]] * 5
    first = bootstrap_auroc(groups, seed=3, resamples=200)
    assert first == bootstrap_auroc(groups, seed=3, resamples=200)
    assert first == (1.0, 1.0)


def test_a_second_scoring_is_refused(tmp_path: Path) -> None:
    check_not_run(tmp_path)
    (tmp_path / "r").mkdir()
    (tmp_path / "r" / "branch_scores.json.partial").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="one scoring"):
        check_not_run(tmp_path)


def test_torch_the_nominal_variant_ignores_the_network() -> None:
    torch = pytest.importorskip("torch")
    from vishwaroop.models.cube_study import VARIANTS, _Kinematics, _step

    stats = {
        "state_mean": torch.zeros(13),
        "state_std": torch.ones(13),
        "delta_std": torch.ones(13),
        "lag": torch.ones(6),
        "action_mean": torch.zeros(6),
        "action_std": torch.ones(6),
        "kinematics": _Kinematics("cpu"),
    }
    state = torch.zeros(1, 1, 13)
    state[..., 6:9] = torch.tensor([0.2, 0.0, 0.0125])
    action = torch.full((1, 1, 6), 0.1)
    pair = 19
    history = torch.zeros(1, 1, 3 * pair)
    size = pair + 3 * pair + 3
    weights = [(torch.randn(1, size, 26), torch.randn(1, 1, 26))]
    plain, _ = _step(
        stats, VARIANTS["nominal-still-reach"], weights, history, state, action, None, state
    )
    zero = [(torch.zeros(1, size, 26), torch.zeros(1, 1, 26))]
    learned, _ = _step(
        stats,
        VARIANTS["carry-contact-beta-fall-still-reach"],
        zero,
        history,
        state,
        action,
        None,
        state,
    )
    assert torch.equal(plain, learned)
