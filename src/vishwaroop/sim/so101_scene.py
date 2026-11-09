"""A minimal SO-101 scene in ManiSkill3, for throughput measurement only (WO-025).

The robot is TheRobotStudio's ``so101_new_calib.urdf`` (Apache-2.0), pinned by repository commit
and by the sha256 of every file this module loads. The files are fetched once into the robotics
cache by ``fetch_assets`` and verified on every load; a mismatch refuses. The pins live in
``config/so101-assets.json``. The scene is a ground plane, the arm, one 30 mm cube and an open bin
built from five boxes, with a fixed front camera and a camera beside the gripper's jaws. Its drive
gains are ManiSkill's SO-100 defaults, not identified from the real arm: the scene measures
stepping and rendering cost, and it is not the calibrated twin (docs/M2-twin-design-draft.md).

ManiSkill is imported lazily, so the CPU tier can import this module and test the pins.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from pathlib import Path
from typing import Any

# The pinned commit and the sha256 of each file the URDF loads (paths relative to Simulation/SO101).
PIN_FILE = Path(__file__).resolve().parents[3] / "config" / "so101-assets.json"
_PINS = json.loads(PIN_FILE.read_text(encoding="utf-8"))
ASSET_SHA256: dict[str, str] = _PINS["files"]
URDF_NAME = "so101_new_calib.urdf"
SO_ARM100_REPO: str = _PINS["repository"]
SO_ARM100_COMMIT: str = _PINS["commit"]
ENV_ID = "VishwaroopSO101Throughput-v1"
AGENT_UID = "so101_vishwaroop"
CAMERA_SHAPES = {"128x128": (128, 128), "480x640": (480, 640)}
REST_QPOS = (0.0, -1.5708, 1.5708, 0.66, 0.0, 0.0)
# Wrist camera on gripper_link: beside the jaws, looking along the jaws toward the tips (-z).
_WRIST_POSITION = (0.0, 0.04, -0.03)


class AssetError(ValueError):
    """The SO-101 files are missing or do not match their pinned hashes."""


def asset_dir() -> Path:
    """Where the pinned files live: ``$VISHWAROOP_SO101_ASSETS`` or the robotics cache."""
    override = os.environ.get("VISHWAROOP_SO101_ASSETS")
    if override:
        return Path(override)
    cache = Path.home() / ".cache" / "vishwaroop-robotics" / "assets"
    return cache / f"so-arm100-{SO_ARM100_COMMIT}" / "Simulation" / "SO101"


def verify_assets(root: Path) -> dict[str, str]:
    """Return the manifest after checking every pinned file; ``AssetError`` on any mismatch."""
    manifest = {}
    for name, expected in sorted(ASSET_SHA256.items()):
        path = root / name
        if not path.is_file():
            raise AssetError(f"missing {path}; run fetch_assets first")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise AssetError(f"{name} has sha256 {actual}, pinned {expected}")
        manifest[name] = actual
    return manifest


def fetch_assets(root: Path) -> dict[str, str]:
    """Download the pinned files from GitHub into ``root`` and verify them. Never overwrites."""
    base = f"https://raw.githubusercontent.com/{SO_ARM100_REPO}/{SO_ARM100_COMMIT}/Simulation/SO101"
    for name in sorted(ASSET_SHA256):
        path = root / name
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(f"{base}/{name}", timeout=60) as response:  # noqa: S310
            data = response.read()
        if hashlib.sha256(data).hexdigest() != ASSET_SHA256[name]:
            raise AssetError(f"downloaded {name} does not match its pinned sha256")
        with path.open("xb") as stream:
            stream.write(data)
    return verify_assets(root)


def register(root: Path | None = None) -> dict[str, str]:
    """Verify the assets and register the agent and the environment with ManiSkill, once."""
    root = asset_dir() if root is None else root
    manifest = verify_assets(root)
    if _REGISTERED:
        return manifest
    _register(root / URDF_NAME)
    _REGISTERED.append(True)
    return manifest


_REGISTERED: list[bool] = []


def _register(urdf: Path) -> None:  # pragma: no cover - needs ManiSkill; run by the throughput tool
    import numpy as np
    import sapien
    import torch
    from mani_skill.agents.base_agent import BaseAgent, Keyframe
    from mani_skill.agents.controllers import PDJointPosControllerConfig, deepcopy_dict
    from mani_skill.agents.registration import register_agent
    from mani_skill.envs.sapien_env import BaseEnv
    from mani_skill.sensors.camera import CameraConfig
    from mani_skill.utils import sapien_utils
    from mani_skill.utils.building import actors
    from mani_skill.utils.building.ground import build_ground
    from mani_skill.utils.registration import register_env
    from mani_skill.utils.structs.pose import Pose

    @register_agent()
    class SO101(BaseAgent):  # type: ignore[misc]
        uid = AGENT_UID
        urdf_path = str(urdf)
        keyframes = {"rest": Keyframe(qpos=np.array(REST_QPOS), pose=sapien.Pose())}

        @property
        def _controller_configs(self) -> Any:
            # ManiSkill's SO-100 position-drive defaults; not identified from the real arm.
            joints = [joint.name for joint in self.robot.active_joints]
            pd_joint_pos = PDJointPosControllerConfig(
                joints,
                lower=None,
                upper=None,
                stiffness=[1e3] * 6,
                damping=[1e2] * 6,
                force_limit=100,
                normalize_action=False,
            )
            return deepcopy_dict({"pd_joint_pos": pd_joint_pos})

        @property
        def _sensor_configs(self) -> Any:
            shape = self.scene_camera_shape  # set by the environment before loading
            pose = sapien.Pose(p=list(_WRIST_POSITION), q=[0.7071068, 0.0, 0.7071068, 0.0])
            return [
                CameraConfig(
                    "wrist",
                    pose,
                    shape[1],
                    shape[0],
                    np.pi / 2,
                    0.01,
                    10,
                    mount=self.robot.links_map["gripper_link"],
                )
            ]

    @register_env(ENV_ID, max_episode_steps=1_000_000)
    class SO101ThroughputEnv(BaseEnv):  # type: ignore[misc]
        SUPPORTED_ROBOTS = [AGENT_UID]

        def __init__(self, *args: Any, camera: str = "128x128", **kwargs: Any) -> None:
            if camera not in CAMERA_SHAPES:
                raise ValueError(f"camera must be one of {sorted(CAMERA_SHAPES)}")
            self.camera_shape = CAMERA_SHAPES[camera]
            super().__init__(*args, robot_uids=AGENT_UID, **kwargs)

        @property
        def _default_sensor_configs(self) -> Any:
            pose = sapien_utils.look_at(eye=[0.45, 0.0, 0.40], target=[0.15, 0.0, 0.0])
            height, width = self.camera_shape
            return [CameraConfig("front", pose, width, height, np.pi / 3, 0.01, 10)]

        @property
        def _default_human_render_camera_configs(self) -> Any:
            pose = sapien_utils.look_at(eye=[0.5, 0.4, 0.4], target=[0.15, 0.0, 0.05])
            return CameraConfig("render_camera", pose, 512, 512, 1, 0.01, 10)

        def _load_agent(self, options: dict[str, Any]) -> None:
            SO101.scene_camera_shape = self.camera_shape
            super()._load_agent(options, sapien.Pose())

        def _load_scene(self, options: dict[str, Any]) -> None:
            build_ground(self.scene)
            self.cube = actors.build_cube(
                self.scene,
                half_size=0.015,
                color=[1, 0, 0, 1],
                name="cube",
                initial_pose=sapien.Pose(p=[0.2, 0.0, 0.015]),
            )
            walls = [
                ([0.06, 0.06, 0.002], [0.0, 0.0, 0.002]),
                ([0.06, 0.002, 0.02], [0.0, 0.058, 0.02]),
                ([0.06, 0.002, 0.02], [0.0, -0.058, 0.02]),
                ([0.002, 0.06, 0.02], [0.058, 0.0, 0.02]),
                ([0.002, 0.06, 0.02], [-0.058, 0.0, 0.02]),
            ]
            builder = self.scene.create_actor_builder()
            for half, offset in walls:
                builder.add_box_collision(sapien.Pose(p=offset), half)
                builder.add_box_visual(
                    sapien.Pose(p=offset),
                    half,
                    material=sapien.render.RenderMaterial(base_color=[0.2, 0.3, 0.8, 1]),
                )
            builder.initial_pose = sapien.Pose(p=[0.2, 0.18, 0.0])
            self.bin = builder.build_static(name="bin")

        def _initialize_episode(self, env_idx: torch.Tensor, options: dict[str, Any]) -> None:
            with torch.device(self.device):
                count = len(env_idx)
                qpos = torch.tensor(REST_QPOS).repeat(count, 1)
                self.agent.reset(qpos)
                xyz = torch.zeros((count, 3))
                xyz[:, 0] = 0.2 + (torch.rand(count) - 0.5) * 0.08
                xyz[:, 1] = (torch.rand(count) - 0.5) * 0.08
                xyz[:, 2] = 0.015
                self.cube.set_pose(Pose.create_from_pq(xyz))

        def evaluate(self) -> dict[str, Any]:
            return {}

        def _get_obs_extra(self, info: dict[str, Any]) -> dict[str, Any]:
            return {}

        def compute_dense_reward(self, obs: Any, action: Any, info: dict[str, Any]) -> Any:
            return torch.zeros(self.num_envs, device=self.device)

        def compute_normalized_dense_reward(
            self, obs: Any, action: Any, info: dict[str, Any]
        ) -> Any:
            return self.compute_dense_reward(obs, action, info)
