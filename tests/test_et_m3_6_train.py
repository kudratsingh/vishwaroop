"""Each arm's added windows and the shared statistics' digest, on FABRICATED tensors and episodes.
Nothing is trained here; no simulator ran."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

torch = pytest.importorskip("torch")
np = pytest.importorskip("numpy")

from test_synth_et_m3_6_data import _m0_like, _write_episode  # noqa: E402
from vishwaroop.models import et_m3_6_train as train  # noqa: E402
from vishwaroop.models.et_m3_6_data import (  # noqa: E402
    BASE_WINDOWS,
    W_STAR,
    DataRefusalError,
    f1_augment,
)
from vishwaroop.synth.m3_record import (  # noqa: E402
    CLOSE_HIGH_FAMILY,
    LATERAL_FAMILY,
    NOMINAL_FAMILY,
)


def _data() -> Any:
    generator = torch.Generator().manual_seed(0)
    return SimpleNamespace(
        device="cpu",
        windows_s=torch.rand((BASE_WINDOWS, 14, 13), generator=generator),
        windows_a=torch.rand((BASE_WINDOWS, 13, 6), generator=generator),
        state_std=torch.linspace(0.1, 1.3, 13),
        action_std=torch.linspace(0.2, 0.7, 6),
    )


def test_f0_adds_nothing() -> None:
    s, a, info = train.added_windows("F0", _data(), {})
    assert len(s) == 0 and len(a) == 0 and info["windows"] == 0


def test_f1_adds_the_frozen_augmentation_of_the_trained_base_windows() -> None:
    data = _data()
    s, a, info = train.added_windows("F1", data, {})
    expected_s, expected_a, _ = f1_augment(
        data.windows_s.double().numpy(),
        data.windows_a.double().numpy(),
        data.state_std.double().numpy(),
        data.action_std.double().numpy(),
    )
    assert s.dtype == torch.float32 and len(s) == W_STAR == info["windows"]
    np.testing.assert_array_equal(s.numpy(), expected_s.astype(np.float32))
    np.testing.assert_array_equal(a.numpy(), expected_a.astype(np.float32))
    assert train.added_windows("F1", data, {})[2]["windows_sha256"] == info["windows_sha256"]


def test_f_star_adds_the_27_target_episodes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(train, "load_train", lambda *_: _m0_like())
    s, _, info = train.added_windows("F_star", _data(), {})
    assert len(s) == W_STAR and len(info["episodes"]) == 27
    assert info["episodes"][0] == "m0-scripted-missed-grasp-seed-002001"


def test_f2_is_cut_to_exactly_w_star_and_refused_when_short(tmp_path: Path) -> None:
    families = [LATERAL_FAMILY, CLOSE_HIGH_FAMILY]
    kept = [
        _write_episode(tmp_path, families[i % 2], 11000 + i, 1012) for i in range(5)
    ]  # 1,000 windows each
    s, a, info = train.added_windows("F2", _data(), {"f2": {"kept": kept}}, tmp_path)
    assert len(s) == len(a) == W_STAR
    assert info["windows_by_episode"] == [1000, 1000, 1000, 1000, 161] and info["matched"]
    # the last episode's windows are its first 161: the cut is from its end
    assert float(s[-1, 0, 0]) == 160.0
    with pytest.raises(DataRefusalError, match="not W"):
        train.added_windows("F2", _data(), {"f2": {"kept": kept[:2]}}, tmp_path)


def test_f1s_short_of_w_star_is_unmatched_not_refused(tmp_path: Path) -> None:
    kept = [_write_episode(tmp_path, NOMINAL_FAMILY, 11000 + i, 1012) for i in range(2)]
    s, _, info = train.added_windows("F1s", _data(), {"f1s": {"kept": kept}}, tmp_path)
    assert len(s) == 2000 and not info["matched"]


def test_the_statistics_digest_names_the_six_statistics() -> None:
    stats = {
        name: torch.arange(3, dtype=torch.float32)
        for name in ("state_mean", "state_std", "delta_std", "lag", "action_mean", "action_std")
    }
    digest = train.stats_digest(stats)
    assert digest == train.stats_digest(dict(stats))
    changed = {**stats, "lag": torch.tensor([0.0, 1.0, 2.5])}
    assert train.stats_digest(changed) != digest


def test_the_hyperparameters_are_wo_004s() -> None:
    from vishwaroop.models.compute_pilot import BATCH, HIDDEN, MEMBERS, WINDOW
    from vishwaroop.models.cube_study import VARIANTS

    assert train.TRAINED_VARIANT == "carry-contact-beta-fall" and train.TRAINED_VARIANT in VARIANTS
    assert train.EPOCHS == 30 and train.SEEDS == (0, 1, 2)
    assert (MEMBERS, HIDDEN, BATCH, WINDOW) == (3, 256, 256, 14)
