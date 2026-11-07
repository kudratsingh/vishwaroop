"""FABRICATED frames, manifests and a rendering fake environment for the M3 synth tests.

Nothing here is a simulator or a render of one. Frames are 512 x 512 grey with a red square "cube"
and a green disc "goal", drawn through a made-up affine camera: column = 256 + 1000 x, row = 256 +
1000 y, in pixels for world metres. Every number is chosen for the tests only.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from vishwaroop.sim.env import ActionSpec, Packet, StreamSpec

SIZE = 512
BACKGROUND = (90, 90, 90)
RED = (200, 20, 20)
GREEN = (20, 200, 20)
CUBE_PX = 24
GOAL_RADIUS_PX = 12
# The made-up camera, as OpenCV intrinsic and world-to-camera extrinsic matrices.
INTRINSIC = [[1000.0, 0.0, 256.0], [0.0, 1000.0, 256.0], [0.0, 0.0, 1.0]]
EXTRINSIC = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
PROJECTION = [[1000.0, 0.0, 0.0, 256.0], [0.0, 1000.0, 0.0, 256.0], [0.0, 0.0, 0.0, 1.0]]
ASSETS = {"files": {"a.stl": "a" * 64, "b.urdf": "0" * 64, "c.png": "f" * 64}}


def pixel(x: float, y: float) -> tuple[int, int]:
    """The fake camera's (row, column) for a world (x, y)."""
    return round(256 + 1000 * y), round(256 + 1000 * x)


def draw(cube: tuple[int, int] | None, goal: tuple[int, int] | None) -> Any:
    """A frame with the cube's top-left corner at ``cube`` and the goal centred at ``goal``."""
    frame = np.empty((SIZE, SIZE, 3), dtype=np.uint8)
    frame[:] = BACKGROUND
    if goal is not None:
        rows, cols = np.ogrid[:SIZE, :SIZE]
        disc = (rows - goal[0]) ** 2 + (cols - goal[1]) ** 2 <= GOAL_RADIUS_PX**2
        frame[disc] = GREEN
    if cube is not None:
        frame[cube[0] : cube[0] + CUBE_PX, cube[1] : cube[1] + CUBE_PX] = RED
    return frame


def episode_frames(steps: int = 8, start: tuple[int, int] = (300, 200)) -> list[Any]:
    """Frames 0 to ``steps``: the cube slides one pixel right per step, the goal stays."""
    frames = [draw((start[0], start[1] + t), (150, 350)) for t in range(steps + 1)]
    for frame in frames:
        frame.flags.writeable = False
    return frames


def manifest(seed: int) -> dict[str, Any]:
    """A fabricated candidate manifest."""
    return {
        "task_id": "PickCubeSO100-v1",
        "task_version": "m0-1",
        "seed": seed,
        "asset_sha256s": [ASSETS["files"][name] for name in sorted(ASSETS["files"])],
        "cube_half_size_m": 0.0125,
        "cube_colour": "red",
        "goal_position": [0.094, -0.106, 0.05],
    }


class _Material:
    static_friction = 0.3
    dynamic_friction = 0.3
    restitution = 0.0


class _Shape:
    physical_material = _Material()


class _Body:
    def get_collision_shapes(self) -> list[_Shape]:
        return [_Shape()]


class _Cube:
    mass = np.array([0.015625])
    _bodies = (_Body(),)


class _Config:
    width = SIZE
    height = SIZE
    fov = 1.0
    near = 0.01
    far = 100.0


class _Camera:
    config = _Config()

    def get_params(self) -> dict[str, Any]:
        return {
            "intrinsic_cv": np.array([INTRINSIC]),
            "extrinsic_cv": np.array([EXTRINSIC]),
            "cam2world_gl": np.array([np.eye(4)]),
        }


class _Task:
    cube_half_size = 0.0125
    cube = _Cube()
    _human_render_cameras = {"render_camera": _Camera()}


class FakeSceneEnv:
    """A fabricated six-joint env whose joints follow the action exactly, with a still cube and goal
    placed by the seed out of the SO-100's reach, so the scripted plan fails and holds. ``exposed``
    adds a fake task with a camera and a cube body, as the ManiSkill adapter's task has."""

    engine = "fake_fixture_no_simulator"
    version = "fixture-1"
    dt_ns = 50_000_000
    frames = ["joint_coordinates", "world"]

    def __init__(self, exposed: bool = True) -> None:
        self._restores = 0
        self._joints = [0.0] * 6
        self._object = [0.0, 0.0, 0.0125]
        self._target = [0.0, 0.0, 0.05]
        if exposed:
            self._task = _Task()
        self.action_spec = ActionSpec(
            representation="absolute_joint_position",
            labels=[f"j{i}" for i in range(6)],
            units=["rad"] * 6,
            frame_id="joint_coordinates",
            semantics="FABRICATED test controller",
            lower=[-3.0] * 6,
            upper=[3.0] * 6,
        )
        self.stream_specs = [
            StreamSpec(
                "joint_position", "state", "joint_coordinates", ["rad"] * 6, [6], "f8", "input"
            ),
            StreamSpec("object_position", "state", "world", ["m"] * 3, [3], "float64", "input"),
            StreamSpec("target_position", "state", "world", ["m"] * 3, [3], "float64", "input"),
        ]

    @property
    def state_restores(self) -> int:
        return self._restores

    def _packet(self) -> Packet:
        return {
            "joint_position": list(self._joints),
            "object_position": list(self._object),
            "target_position": list(self._target),
        }

    def reset(self, seed: int) -> Packet:
        offset = (seed % 7) * 0.01
        self._joints = [0.0] * 6
        # Far beyond the SO-100's reach, so planning fails and the arm holds still.
        self._object = [0.06 + offset, 0.04, 0.0125]
        self._target = [-0.1, -0.1 + offset, 0.05]
        return self._packet()

    def save_state(self) -> bytes:
        state = {"joints": self._joints, "object": self._object, "target": self._target}
        return json.dumps(state, sort_keys=True).encode("utf-8")

    def restore_state(self, state: bytes) -> Packet:
        self._restores += 1
        saved = json.loads(state.decode("utf-8"))
        self._joints = list(saved["joints"])
        self._object = list(saved["object"])
        self._target = list(saved["target"])
        return self._packet()

    def step(self, action: list[float]) -> Packet:
        self._joints = [float(value) for value in action]
        return self._packet()

    def render_rgb(self) -> Any:
        row, col = pixel(self._object[0], self._object[1])
        return draw((row - CUBE_PX // 2, col - CUBE_PX // 2), pixel(*self._target[:2]))

    def configuration(self) -> dict[str, Any]:
        return {"env_id": "PickCubeSO100-v1", "fixture": True}

    def stack_identity(self) -> dict[str, Any]:
        return {"fixture": "fake-scene-1"}

    def asset_manifest(self) -> dict[str, Any]:
        return json.loads(json.dumps(ASSETS))
