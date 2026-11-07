"""Scene snapshots and episode renders, by ``evals/M3-protocol.md`` section 3.

For each M3 seed, before anything is generated or recorded from it: ``reset(seed)``, then
``save_state()``, then ``restore_state()`` of that saved state (the ADR-0006 path), then the initial
512 x 512 human render. The snapshot manifest records the seed and block, the saved state's sha256,
``asset_manifest()``, ``configuration()`` and ``stack_identity()`` with their sha256, the task id
and version, the cube's half size (0.0125 m) and colour (red), the goal position, the human render
camera's pose and intrinsics and the cube's mass and friction where the environment exposes them
(otherwise a statement of what ``configuration()`` contains), and the render's sha256. A snapshot is
written once: an existing directory is refused.

An episode render restores the saved state, renders frame 0, and renders frame t after control step
t, with the scripted controller seeing only the input streams, as ``sim.export.record_episode``
does. Frames stay in memory. Positions are in metres in the world frame; pixels are (row, column).
Needs numpy, and for real scenes the robotics environment.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..sim.baseline import ScriptedPickPlace
from ..sim.env import SimEnv
from .checker import candidate_manifest
from .operators import EpisodeKind
from .protocol import PROTOCOL_VERSION, block_of, partition_for_seed, scene_group_id

CUBE_HALF_SIZE_M = 0.0125
CUBE_COLOUR = "red"
RENDER_SHAPE = (512, 512, 3)
CAMERA_NAME = "render_camera"
MANIFEST_FILE = "snapshot.json"
STATE_FILE = "initial-state.json"
RENDER_FILE = "initial-render.npy"


class SnapshotError(ValueError):
    """A snapshot that cannot be taken, written or read as the protocol requires."""


class RenderingEnv(SimEnv, Protocol):
    """A ``SimEnv`` that can render its human camera view as H x W x 3 uint8."""

    def render_rgb(self) -> Any: ...


def canonical_sha256(value: Any) -> str:
    """sha256 of the value's canonical JSON: sorted keys, no spaces, no NaN."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def array_sha256(array: Any) -> str:
    """sha256 of an array's raw C-order bytes; its shape and dtype are recorded beside it."""
    import numpy as np

    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def _plain(value: Any) -> Any:
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return value.tolist() if hasattr(value, "tolist") else value


def camera_parameters(env: Any) -> dict[str, Any]:
    """The human render camera's pose and intrinsics, read from the ManiSkill task the adapter
    wraps; a statement instead when the environment does not expose them."""
    task = getattr(env, "_task", None)
    cameras = getattr(task, "_human_render_cameras", None)
    if not isinstance(cameras, dict) or CAMERA_NAME not in cameras:
        return {
            "exposed": False,
            "statement": (
                "the environment exposes no human render camera; configuration() contains "
                f"{sorted(env.configuration())}"
            ),
        }
    camera = cameras[CAMERA_NAME]
    params = {name: _plain(value)[0] for name, value in camera.get_params().items()}
    config = camera.config
    out: dict[str, Any] = {
        "exposed": True,
        "name": CAMERA_NAME,
        "width": int(config.width),
        "height": int(config.height),
        "fov_rad": float(config.fov),
        "near_m": float(config.near),
        "far_m": float(config.far),
        "intrinsic_cv": params["intrinsic_cv"],
        "extrinsic_cv": params["extrinsic_cv"],
        "cam2world_gl": params["cam2world_gl"],
        "convention": (
            "OpenCV: pixel (u, v, 1) ~ intrinsic_cv @ extrinsic_cv @ (x, y, z, 1), u the column "
            "and v the row; extrinsic_cv maps world to camera"
        ),
    }
    pose = getattr(getattr(camera, "camera", None), "global_pose", None)
    if pose is not None:
        out["pose_world_pq"] = _plain(pose.raw_pose)[0]
    return out


def cube_physics(env: Any) -> dict[str, Any]:
    """The cube's mass (kg) and friction where the environment exposes them, else a statement."""
    cube = getattr(getattr(env, "_task", None), "cube", None)
    bodies = getattr(cube, "_bodies", None)
    if cube is None or not bodies:
        return {
            "exposed": False,
            "statement": (
                "the environment exposes no cube body; configuration() contains "
                f"{sorted(env.configuration())}"
            ),
        }
    out: dict[str, Any] = {"exposed": True, "mass_kg": float(_plain(cube.mass)[0])}
    shapes = bodies[0].get_collision_shapes()
    if shapes:
        material = shapes[0].physical_material
        out["static_friction"] = float(material.static_friction)
        out["dynamic_friction"] = float(material.dynamic_friction)
        out["restitution"] = float(material.restitution)
    else:
        out["friction_statement"] = "the cube has no collision shape to read friction from"
    return out


def _cube_half_size(env: Any) -> float:
    exposed = getattr(getattr(env, "_task", None), "cube_half_size", None)
    if exposed is not None and abs(float(exposed) - CUBE_HALF_SIZE_M) > 1e-12:
        raise SnapshotError(f"the cube's half size is {exposed}, not the frozen {CUBE_HALF_SIZE_M}")
    return CUBE_HALF_SIZE_M


def capture_render(env: RenderingEnv) -> Any:
    """The current human render as a read-only 512 x 512 x 3 uint8 copy."""
    import numpy as np

    frame = np.array(env.render_rgb(), dtype=np.uint8, copy=True)
    if frame.shape != RENDER_SHAPE:
        raise SnapshotError(f"the human render is {frame.shape}, not {RENDER_SHAPE}")
    frame.flags.writeable = False
    return frame


@dataclass(frozen=True)
class Snapshot:
    """A scene: its manifest, its saved initial state and its initial render."""

    manifest: dict[str, Any]
    initial_state: bytes
    render: Any

    @property
    def seed(self) -> int:
        return int(self.manifest["seed"])

    def candidate_manifest(self) -> dict[str, Any]:
        return candidate_manifest(self.manifest)


def take_snapshot(env: RenderingEnv, seed: int, task_id: str, task_version: str) -> Snapshot:
    """reset, save_state, restore_state, render, and the manifest. Refuses blocks 0-9 and 18-19."""
    partition = partition_for_seed(seed)
    env.reset(seed)
    state = env.save_state()
    packet = env.restore_state(state)
    render = capture_render(env)
    assets = env.asset_manifest()
    configuration = env.configuration()
    stack = env.stack_identity()
    manifest = {
        "protocol_version": PROTOCOL_VERSION,
        "seed": seed,
        "block": block_of(seed),
        "partition": partition,
        "scene_group_id": scene_group_id(seed),
        "path": "reset(seed), save_state(), restore_state(saved), render (ADR-0006)",
        "task_id": task_id,
        "task_version": task_version,
        "initial_state": {"path": STATE_FILE, "sha256": hashlib.sha256(state).hexdigest()},
        "asset_manifest": assets,
        "asset_manifest_sha256": canonical_sha256(assets),
        "asset_sha256s": [assets["files"][name] for name in sorted(assets["files"])],
        "configuration": configuration,
        "configuration_sha256": canonical_sha256(configuration),
        "stack_identity": stack,
        "stack_identity_sha256": canonical_sha256(stack),
        "cube_half_size_m": _cube_half_size(env),
        "cube_colour": CUBE_COLOUR,
        "cube_physics": cube_physics(env),
        "goal_position": [float(value) for value in packet["target_position"]],
        "camera": camera_parameters(env),
        "initial_render": {
            "path": RENDER_FILE,
            "shape": list(render.shape),
            "dtype": str(render.dtype),
            "sha256": array_sha256(render),
            "hashed": "raw C-order uint8 bytes",
        },
    }
    return Snapshot(manifest, state, render)


def write_snapshot(snapshot: Snapshot, directory: Path) -> Path:
    """Write the snapshot once into a new ``directory``; refuses one that exists."""
    import numpy as np

    directory = Path(directory)
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise SnapshotError(f"{directory} exists; a snapshot is written once") from exc
    with (directory / STATE_FILE).open("xb") as stream:
        stream.write(snapshot.initial_state)
    with (directory / RENDER_FILE).open("xb") as stream:
        np.save(stream, np.ascontiguousarray(snapshot.render), allow_pickle=False)
    text = json.dumps(snapshot.manifest, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with (directory / MANIFEST_FILE).open("x", encoding="utf-8") as stream:
        stream.write(text)
    return directory


def read_snapshot(directory: Path) -> Snapshot:
    """Read a written snapshot, refused if its state or render does not match its sha256."""
    import numpy as np

    directory = Path(directory)
    manifest = json.loads((directory / MANIFEST_FILE).read_text(encoding="utf-8"))
    state = (directory / STATE_FILE).read_bytes()
    if hashlib.sha256(state).hexdigest() != manifest["initial_state"]["sha256"]:
        raise SnapshotError(f"{directory}: the initial state does not match its sha256")
    render = np.load(directory / RENDER_FILE, allow_pickle=False)
    if array_sha256(render) != manifest["initial_render"]["sha256"]:
        raise SnapshotError(f"{directory}: the initial render does not match its sha256")
    render.flags.writeable = False
    return Snapshot(manifest, state, render)


def projection_matrix(manifest: dict[str, Any]) -> list[list[float]]:
    """``intrinsic_cv @ extrinsic_cv`` from a snapshot manifest, 3 x 4; refused when the camera was
    not exposed."""
    camera = manifest["camera"]
    if not camera.get("exposed"):
        raise SnapshotError("the snapshot records no camera projection")
    k, e = camera["intrinsic_cv"], camera["extrinsic_cv"]
    return [[sum(k[r][m] * e[m][c] for m in range(3)) for c in range(4)] for r in range(3)]


@dataclass(frozen=True)
class RenderedEpisode:
    """Frames 0 to T of one scripted episode on a scene, and what the controller did."""

    episode: EpisodeKind
    frames: list[Any]
    actions: list[list[float]]
    planning_error: str | None
    initial_joints: list[float]
    initial_cube: list[float]
    cube_positions: list[list[float]]

    @property
    def steps(self) -> int:
        return len(self.actions)


def render_episode(
    env: RenderingEnv, snapshot: Snapshot, episode: EpisodeKind, max_steps: int
) -> RenderedEpisode:
    """Restore the scene's saved state and run the episode's scripted controller, rendering frame 0
    after the restore and frame t after control step t. ``ScriptedPickPlace`` uses
    ``noise_seed = seed``. Also kept: the restored joint and cube positions, which frame
    eligibility uses, and the simulator's cube position at every frame, which only the pilot's
    premise check reads."""
    if episode.seed != snapshot.seed:
        raise SnapshotError(f"episode seed {episode.seed} is not the scene's {snapshot.seed}")
    inputs = {stream.name for stream in env.stream_specs if stream.role == "input"}
    policy = ScriptedPickPlace(episode.settings, noise_seed=episode.seed)
    packet = env.restore_state(snapshot.initial_state)
    initial_joints = [float(value) for value in packet["joint_position"]]
    initial_cube = [float(value) for value in packet["object_position"]]
    cubes = [initial_cube]
    frames = [capture_render(env)]
    actions: list[list[float]] = []
    for step in range(max_steps):
        action = policy({name: packet[name] for name in packet if name in inputs}, step)
        if action is None:
            break
        packet = env.step(list(action))
        actions.append(list(action))
        cubes.append([float(value) for value in packet["object_position"]])
        frames.append(capture_render(env))
    return RenderedEpisode(
        episode, frames, actions, policy.planning_error, initial_joints, initial_cube, cubes
    )
