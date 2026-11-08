"""Scene snapshots, episode renders and ET-M3-1's pilot and scoring flow, on a FABRICATED
rendering environment (tests/fake_scene.py). No simulator; nothing measured here is about one."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

from fake_scene import INTRINSIC, PROJECTION, FakeSceneEnv  # noqa: E402
from vishwaroop.synth import et_m3_1, inject  # noqa: E402
from vishwaroop.synth.checker import Tolerances, pilot_tolerances  # noqa: E402
from vishwaroop.synth.operators import et_m3_1_episodes  # noqa: E402
from vishwaroop.synth.protocol import ProtocolRefusalError  # noqa: E402
from vishwaroop.synth.snapshot import (  # noqa: E402
    SnapshotError,
    array_sha256,
    canonical_sha256,
    projection_matrix,
    read_snapshot,
    render_episode,
    take_snapshot,
    write_snapshot,
)

TASK = ("PickCubeSO100-v1", "m0-1", 200)
FIELDS = {
    "protocol_version",
    "seed",
    "block",
    "partition",
    "scene_group_id",
    "path",
    "task_id",
    "task_version",
    "initial_state",
    "asset_manifest",
    "asset_manifest_sha256",
    "asset_sha256s",
    "configuration",
    "configuration_sha256",
    "stack_identity",
    "stack_identity_sha256",
    "cube_half_size_m",
    "cube_colour",
    "cube_physics",
    "goal_position",
    "camera",
    "initial_render",
}


def test_a_snapshot_records_every_listed_field() -> None:
    env = FakeSceneEnv()
    snapshot = take_snapshot(env, 10002, *TASK[:2])
    manifest = snapshot.manifest
    assert set(manifest) == FIELDS
    assert manifest["seed"] == 10002 and manifest["block"] == 10
    assert manifest["partition"] == "train"
    assert manifest["scene_group_id"] == "m3-seed-block-10"
    assert manifest["configuration_sha256"] == canonical_sha256(env.configuration())
    assert manifest["stack_identity_sha256"] == canonical_sha256(env.stack_identity())
    assert manifest["asset_manifest_sha256"] == canonical_sha256(env.asset_manifest())
    assert manifest["asset_sha256s"] == ["a" * 64, "0" * 64, "f" * 64]
    assert manifest["cube_half_size_m"] == 0.0125 and manifest["cube_colour"] == "red"
    assert manifest["goal_position"] == env.reset(10002)["target_position"]
    assert manifest["initial_render"]["sha256"] == array_sha256(snapshot.render)
    assert manifest["initial_render"]["shape"] == [512, 512, 3]
    assert manifest["cube_physics"] == {
        "exposed": True,
        "mass_kg": 0.015625,
        "static_friction": 0.3,
        "dynamic_friction": 0.3,
        "restitution": 0.0,
    }
    camera = manifest["camera"]
    assert camera["exposed"] and camera["intrinsic_cv"] == INTRINSIC
    assert camera["width"] == camera["height"] == 512
    assert projection_matrix(manifest) == PROJECTION
    assert env.state_restores == 1
    assert not snapshot.render.flags.writeable


def test_without_an_exposed_camera_or_cube_the_snapshot_says_so() -> None:
    snapshot = take_snapshot(FakeSceneEnv(exposed=False), 10003, *TASK[:2])
    for name in ("camera", "cube_physics"):
        record = snapshot.manifest[name]
        assert record["exposed"] is False
        assert "configuration() contains ['env_id', 'fixture']" in record["statement"]
    with pytest.raises(SnapshotError, match="no camera"):
        projection_matrix(snapshot.manifest)


@pytest.mark.parametrize("seed", [7003, 9999, 18000, 19999])
def test_snapshots_refuse_m0_and_reserved_blocks_before_touching_the_env(seed: int) -> None:
    env = FakeSceneEnv()
    with pytest.raises(ProtocolRefusalError):
        take_snapshot(env, seed, *TASK[:2])
    assert env.state_restores == 0


def test_a_snapshot_is_written_once_and_read_back_by_its_hashes(tmp_path: Path) -> None:
    snapshot = take_snapshot(FakeSceneEnv(), 10004, *TASK[:2])
    where = write_snapshot(snapshot, tmp_path / "seed-010004")
    with pytest.raises(SnapshotError, match="written once"):
        write_snapshot(snapshot, where)
    back = read_snapshot(where)
    assert back.manifest == snapshot.manifest
    assert back.initial_state == snapshot.initial_state
    assert (back.render == snapshot.render).all()
    render = np.load(where / "initial-render.npy")
    render[0, 0] = (1, 2, 3)
    (where / "initial-render.npy").unlink()
    np.save(where / "initial-render.npy", render)
    with pytest.raises(SnapshotError, match="render"):
        read_snapshot(where)


def test_an_episode_starts_from_the_restored_state_and_renders_every_step() -> None:
    env = FakeSceneEnv()
    snapshot = take_snapshot(env, 10001, *TASK[:2])
    episode = et_m3_1_episodes([10001])[0]
    rendered = render_episode(env, snapshot, episode, TASK[2])
    assert rendered.planning_error is not None  # the fake scene is out of reach: the arm holds
    assert len(rendered.frames) == rendered.steps + 1 == 16
    assert (rendered.frames[0] == snapshot.render).all()
    assert env.state_restores == 2
    with pytest.raises(SnapshotError, match="seed"):
        render_episode(env, snapshot, et_m3_1_episodes([10002])[0], TASK[2])


def test_the_pilot_and_scoring_flow_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A shortened ET-M3-1 on fabricated scenes: 4 pilot seeds, 4 controls, 8 injections."""
    monkeypatch.setattr(et_m3_1, "PILOT_SEEDS", (10920, 10921, 10922, 10923))
    monkeypatch.setattr(et_m3_1, "CONTROL_SEEDS", (10580, 10581, 10582, 10583))
    plan = [(t, 0, inject.injection_seed(t, 0)) for t in range(1, 7)]
    plan += [(4, 1, inject.injection_seed(4, 1)), (4, 2, inject.injection_seed(4, 2))]
    monkeypatch.setattr(inject, "injection_plan", lambda: sorted(plan, key=lambda x: x[2]))
    env: Any = FakeSceneEnv()
    measured = et_m3_1.run_pilot(env, TASK, tmp_path / "pilot")
    assert [e["seed"] for e in measured["episodes"]] == [10920, 10921, 10922, 10923]
    assert all(e["goal_shift_min_px"]["value"] > 0 for e in measured["episodes"])
    assert all(e["final_cube"]["projects_inside_image"] for e in measured["episodes"])
    written = pilot_tolerances(measured["candidates"])
    tolerances = Tolerances.from_json(json.loads(json.dumps(written)))
    assert (tolerances.a_lo, tolerances.a_hi) == pytest.approx((0.9, 1.1))
    report = et_m3_1.run_score(env, TASK, tmp_path / "score", tolerances)
    assert all(item["passed"] for item in report["controls"])
    for item in report["injections"]:
        assert item["source_passed"], item
        assert item["injected_passed"] is False, item
    result = report["verdict"]
    assert result["injections_rejected"] == 8 and result["false_rejections"] == 0
    assert not result["passed"]  # 8 of the frozen 60: the shortened run cannot pass
    assert result["rejections_by_type"]["goal_or_task_changed"] == {"injected": 3, "rejected": 3}
    assert (tmp_path / "score" / "snapshots" / "seed-010770" / "snapshot.json").exists()
    shown = result["visibility"]["controls"]
    assert shown["candidates"] == 4 and shown["final_no_cube"] == shown["final_uncertain"] == 0
    assert all(row["final_cube"]["on_table"] for row in shown["per_candidate"])
    assert result["visibility"]["injection_sources"]["candidates"] == 8
    json.dumps(report, allow_nan=False)
    with pytest.raises(SnapshotError, match="written once"):
        et_m3_1.run_score(env, TASK, tmp_path / "score", tolerances)


class _CountingEnv(FakeSceneEnv):
    """A FABRICATED env whose render encodes how many steps ran since the last restore."""

    def __init__(self) -> None:
        super().__init__()
        self.steps_since_restore = 0

    def restore_state(self, state: bytes) -> Any:
        self.steps_since_restore = 0
        return super().restore_state(state)

    def step(self, action: list[float]) -> Any:
        self.steps_since_restore += 1
        return super().step(action)

    def render_rgb(self) -> Any:
        image = super().render_rgb().copy()
        image[0, 0, :] = self.steps_since_restore
        return image


def test_frame_t_is_rendered_after_exactly_t_steps_with_the_seed_as_noise_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from vishwaroop.synth import snapshot as module

    seen: list[int] = []
    real = module.ScriptedPickPlace

    def recording(settings: Any, noise_seed: int = 0) -> Any:
        seen.append(noise_seed)
        return real(settings, noise_seed=noise_seed)

    monkeypatch.setattr(module, "ScriptedPickPlace", recording)
    env = _CountingEnv()
    snap = take_snapshot(env, 10001, *TASK[:2])
    rendered = render_episode(env, snap, et_m3_1_episodes([10001])[0], TASK[2])
    assert len(rendered.frames) == rendered.steps + 1
    assert [int(f[0, 0, 0]) for f in rendered.frames] == list(range(rendered.steps + 1))
    assert seen == [10001]


def test_a_short_resize_source_is_replaced_from_10660_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FABRICATED: the frozen type-3 source is made short; the scorer takes 10660 instead."""
    monkeypatch.setattr(et_m3_1, "CONTROL_SEEDS", (10580,))
    frozen = inject.injection_seed(3, 0)
    monkeypatch.setattr(inject, "injection_plan", lambda: [(3, 0, frozen)])
    real = et_m3_1._size_frames
    monkeypatch.setattr(
        et_m3_1,
        "_size_frames",
        lambda snapshot, rendered: 1 if snapshot.seed == frozen else real(snapshot, rendered),
    )
    env: Any = FakeSceneEnv()
    measured = et_m3_1.run_pilot(env, TASK, tmp_path / "pilot")
    tolerances = Tolerances.from_json(
        json.loads(json.dumps(pilot_tolerances(measured["candidates"])))
    )
    report = et_m3_1.run_score(env, TASK, tmp_path / "score", tolerances)
    item = report["injections"][0]
    assert item["frozen_seed"] == frozen and item["seed"] == 10660
    assert item["skipped_seeds"] == [{"seed": frozen, "size_checkable_frames": 1, "T": 15}]
    assert item["detail"]["step"] >= 1 and item["injected_passed"] is False
