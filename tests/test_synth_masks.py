"""ET-M3-1's frozen colour masks and 8-connectivity, pixel by pixel. Frames are FABRICATED."""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

from vishwaroop.synth import masks  # noqa: E402
from vishwaroop.synth.checker import MASK_RULES  # noqa: E402


def _one(r: int, g: int, b: int) -> object:
    return np.array([[[r, g, b]]], dtype=np.uint8)


@pytest.mark.parametrize(
    ("pixel", "red"),
    [
        ((121, 59, 59), True),
        ((120, 59, 59), False),
        ((121, 60, 59), False),
        ((121, 59, 60), False),
    ],
)
def test_the_red_rule_is_exactly_the_frozen_one(pixel: tuple[int, int, int], red: bool) -> None:
    assert bool(masks.red_mask(_one(*pixel))[0, 0]) is red


@pytest.mark.parametrize(
    ("pixel", "green"),
    [
        ((79, 121, 79), True),
        ((79, 120, 79), False),
        ((80, 121, 79), False),
        ((79, 121, 80), False),
    ],
)
def test_the_green_rule_is_exactly_the_frozen_one(pixel: tuple[int, int, int], green: bool) -> None:
    assert bool(masks.green_mask(_one(*pixel))[0, 0]) is green


def test_diagonal_neighbours_form_one_component() -> None:
    mask = np.zeros((4, 4), dtype=bool)
    mask[0, 0] = mask[1, 1] = mask[2, 2] = True
    assert len(masks.components(mask)) == 1


def test_the_mask_module_and_the_checker_agree_on_the_rules() -> None:
    assert MASK_RULES["red"] == masks.RED_RULE
    assert MASK_RULES["green"] == masks.GREEN_RULE
    assert MASK_RULES["connectivity"] == masks.CONNECTIVITY
