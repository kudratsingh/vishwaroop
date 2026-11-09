"""WO-025: the throughput and latency tools' pure parts (no simulator, no torch, no network)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from vishwaroop.models import wo025_sim_throughput as sim
from vishwaroop.models import wo025_vla_latency as vla
from vishwaroop.sim import so101_scene


def test_so101_is_required_and_so100_is_reference() -> None:
    assert sim.SCENES == {"so101": "required", "so100": "reference"}
    cells = sim.configurations("cuda", ["so101", "so100"])
    assert {c["label"] for c in cells if c["scene"] == "so100"} == {"reference"}
    assert {c["label"] for c in cells if c["scene"] == "so101"} == {"required"}


def test_configurations_cover_every_cell_in_order() -> None:
    cuda = sim.configurations("cuda", ["so101"])
    assert len(cuda) == 3 * 4
    assert [c["num_envs"] for c in cuda[:4]] == [1, 64, 256, 1024]
    cpu = sim.configurations("cpu", ["so101", "so100"])
    assert len(cpu) == 6 and {c["num_envs"] for c in cpu} == {1}


def test_the_tool_refuses_to_run_without_so101() -> None:
    assert sim.main(["--scenes", "so100"]) == 2


def test_rates_count_every_camera_of_every_environment() -> None:
    cell = {"scene": "so101", "obs_mode": "rgb", "num_envs": 64}
    out = sim.rates(cell, seconds=2.0, steps=100)
    assert out["control_steps_per_second"] == 50.0
    assert out["env_steps_per_second"] == 3200.0
    assert out["rendered_frames_per_second"] == 6400.0
    state = sim.rates({"scene": "so100", "obs_mode": "state", "num_envs": 1}, 1.0, 10)
    assert state["rendered_frames_per_second"] == 0.0


def test_so101_assets_are_pinned_by_commit_and_hash() -> None:
    assert len(so101_scene.SO_ARM100_COMMIT) == 40
    assert so101_scene.URDF_NAME in so101_scene.ASSET_SHA256
    assert all(len(v) == 64 for v in so101_scene.ASSET_SHA256.values())
    assert sum(name.endswith(".stl") for name in so101_scene.ASSET_SHA256) == 13


def test_verify_assets_refuses_missing_and_changed_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = b"robot"
    monkeypatch.setattr(so101_scene, "ASSET_SHA256", {"a.urdf": hashlib.sha256(good).hexdigest()})
    with pytest.raises(so101_scene.AssetError, match="missing"):
        so101_scene.verify_assets(tmp_path)
    (tmp_path / "a.urdf").write_bytes(b"changed")
    with pytest.raises(so101_scene.AssetError, match="pinned"):
        so101_scene.verify_assets(tmp_path)
    (tmp_path / "a.urdf").write_bytes(good)
    assert so101_scene.verify_assets(tmp_path) == {"a.urdf": hashlib.sha256(good).hexdigest()}


def test_weights_are_refused_unless_hub_pin_and_file_agree(tmp_path: Path) -> None:
    pinned = vla.WEIGHTS_SHA256["smolvla"]
    weights = tmp_path / "model.safetensors"
    weights.write_bytes(b"not the model")
    with pytest.raises(vla.WeightsMismatchError, match="the Hub says"):
        vla.check_weights("smolvla", weights, "0" * 64)
    with pytest.raises(vla.WeightsMismatchError, match="has sha256"):
        vla.check_weights("smolvla", weights, pinned)


def test_checkpoints_are_pinned_to_full_revisions() -> None:
    assert set(vla.CHECKPOINTS) == set(vla.WEIGHTS_SHA256) == {"smolvla", "pi05"}
    assert all(len(rev) == 40 for _, rev in vla.CHECKPOINTS.values())
    assert vla.BATCHES == (1, 4, 8)


def test_summarize_reports_percentiles_and_per_step() -> None:
    out = vla.summarize([float(v) for v in range(1, 101)], chunk_length=50)
    assert out["p50_ms"] == 50.5
    assert out["p95_ms"] == 95.0
    assert out["max_ms"] == 100.0
    assert out["p50_ms_per_action_step"] == 50.5 / 50
