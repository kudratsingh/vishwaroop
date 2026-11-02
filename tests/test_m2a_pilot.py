"""The pilot's arithmetic and its model's shapes. Images are FABRICATED."""

from __future__ import annotations

import pytest

from vishwaroop.models.m2a_pilot import PLANNED_EPOCHS, PLANNED_IMAGES, extrapolate


def test_the_extrapolation_is_plain_arithmetic() -> None:
    hours = extrapolate(80.0)["encoder_only_hours"]
    assert hours == pytest.approx(PLANNED_IMAGES * PLANNED_EPOCHS / 80.0 / 3600)
    assert hours == pytest.approx(41.67, abs=0.01)


def test_torch_the_tokenizer_reconstructs_the_input_shape() -> None:
    torch = pytest.importorskip("torch")
    from vishwaroop.models.m2a_pilot import RESOLUTION, Tokenizer

    model = Tokenizer("cpu")
    images = torch.rand(2, 3, RESOLUTION, RESOLUTION)
    assert model(images).shape == images.shape


def test_torch_a_short_training_reports_a_rate() -> None:
    torch = pytest.importorskip("torch")
    from vishwaroop.models.m2a_pilot import RESOLUTION, train

    frames = (torch.rand(40, 3, RESOLUTION, RESOLUTION) * 255).to(torch.uint8)
    result = train(frames, "cpu", seconds=3.0)
    assert result["steps"] >= 1
    assert result["images_per_second_median_step"] > 0
