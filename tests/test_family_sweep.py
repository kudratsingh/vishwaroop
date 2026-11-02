"""Resuming, the free-fall term and the report-only freeze. Tensors and episodes are FABRICATED."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from vishwaroop.models.family_sweep import check_resume

CONFIG = {"holdouts": "seed", "variants": "carry-beta", "epochs": 30}
PLAN = {"config": CONFIG, "commit": "abc"}


def _spec(root: Path) -> dict[str, object]:
    loaded: dict[str, object] = json.loads(
        (root / "evals" / "M1-family-holdouts.json").read_text(encoding="utf-8")
    )
    return loaded


def test_resume_accepts_the_same_settings_and_code() -> None:
    check_resume(PLAN, dict(CONFIG), code_changed=False)


def test_resume_refuses_different_settings() -> None:
    with pytest.raises(ValueError, match="settings differ"):
        check_resume(PLAN, {**CONFIG, "epochs": 100}, code_changed=False)


def test_resume_refuses_changed_code() -> None:
    with pytest.raises(ValueError, match="code under src"):
        check_resume(PLAN, dict(CONFIG), code_changed=True)


def test_family_results_are_report_only_and_change_no_threshold(root: Path) -> None:
    spec = _spec(root)
    assert spec["use"] == "report_only"
    assert spec["changes_a_threshold"] is False
    assert "threshold" not in spec["sweep"]  # type: ignore[operator]


def test_the_sweep_covers_every_train_family(root: Path) -> None:
    manifest = json.loads(
        (root / "artifacts" / "manifests" / "m0-dataset-v1.json").read_text(encoding="utf-8")
    )
    families = {family for family in manifest["summary"]["by_family"] if "-dev-" not in family}
    assert set(_spec(root)["sweep"]["families"]) == families  # type: ignore[index]


def test_the_freeze_is_recorded_with_this_files_hash(root: Path) -> None:
    digest = hashlib.sha256((root / "evals" / "M1-family-holdouts.json").read_bytes()).hexdigest()
    notes = [
        json.loads(line).get("note", "")
        for line in (root / "work_orders" / "STATUS.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(f"evals/M1-family-holdouts.json sha256 {digest}" in note for note in notes)


def _fall_state(torch: object, height: float, flag: float = 0.0) -> object:
    state = torch.zeros(13)  # type: ignore[attr-defined]
    state[6:9] = torch.tensor([0.1, 0.1, 0.0125 + height])  # type: ignore[attr-defined]
    state[12] = flag
    return state


def test_torch_a_released_cube_falls_and_stops_at_the_table() -> None:
    torch = pytest.importorskip("torch")
    from vishwaroop.models.cube_study import FALL_PER_STEP_M, fall_displacement

    high = _fall_state(torch, 0.04)
    moved = fall_displacement(high, high, torch.zeros(1))
    assert moved.tolist() == pytest.approx([0.0, 0.0, -FALL_PER_STEP_M], abs=1e-6)
    low = _fall_state(torch, 0.01)
    assert fall_displacement(low, low, torch.zeros(1))[2].item() == pytest.approx(-0.01, abs=1e-6)


def test_torch_a_fall_keeps_its_velocity() -> None:
    torch = pytest.importorskip("torch")
    from vishwaroop.models.cube_study import FALL_PER_STEP_M, fall_displacement

    state = _fall_state(torch, 0.1)
    previous = state.clone()
    previous[6:9] += torch.tensor([-0.002, 0.001, 0.003])
    moved = fall_displacement(state, previous, torch.zeros(1))
    assert moved.tolist() == pytest.approx([0.002, -0.001, -0.003 - FALL_PER_STEP_M], abs=1e-6)


def test_torch_no_fall_on_the_table_or_while_grasped() -> None:
    torch = pytest.importorskip("torch")
    from vishwaroop.models.cube_study import fall_displacement

    table = _fall_state(torch, 0.0)
    assert fall_displacement(table, table, torch.zeros(1)).abs().max().item() == 0.0
    held = _fall_state(torch, 0.04)
    assert fall_displacement(held, held, torch.ones(1)).abs().max().item() == 0.0


def _fake_data(torch: object) -> tuple[object, dict[str, object]]:
    torch.manual_seed(5)  # type: ignore[attr-defined]
    states = torch.randn(600, 14, 13) * 0.01  # type: ignore[attr-defined]
    actions = torch.randn(600, 13, 6) * 0.01  # type: ignore[attr-defined]
    data = SimpleNamespace(
        device="cpu",
        windows_s=states,
        windows_a=actions,
        delta_std=torch.ones(13),  # type: ignore[attr-defined]
    )
    from vishwaroop.models.cube_study import _Kinematics

    stats = {
        "state_mean": torch.zeros(13),  # type: ignore[attr-defined]
        "state_std": torch.ones(13),  # type: ignore[attr-defined]
        "delta_std": torch.ones(13),  # type: ignore[attr-defined]
        "lag": torch.ones(6),  # type: ignore[attr-defined]
        "action_mean": torch.zeros(6),  # type: ignore[attr-defined]
        "action_std": torch.ones(6),  # type: ignore[attr-defined]
        "kinematics": _Kinematics("cpu"),
    }
    return data, stats


def test_torch_a_resumed_training_matches_an_unbroken_one(tmp_path: Path) -> None:
    torch = pytest.importorskip("torch")
    from vishwaroop.models.cube_study import VARIANTS, _train

    data, stats = _fake_data(torch)
    variant = VARIANTS["carry-contact-beta-fall"]
    unbroken, _ = _train(data, stats, variant, 3, 3)  # type: ignore[arg-type]
    path = tmp_path / "checkpoint.pt"
    _train(data, stats, variant, 3, 2, path)  # type: ignore[arg-type]
    (tmp_path / "checkpoint.partial").write_bytes(b"torn write from a crash")
    resumed, training = _train(data, stats, variant, 3, 3, path)  # type: ignore[arg-type]
    assert training["resumed_at_epoch"] == 2
    for layer, other in zip(unbroken, resumed, strict=True):
        for item, value in zip(layer, other, strict=True):
            assert torch.equal(item, value)
