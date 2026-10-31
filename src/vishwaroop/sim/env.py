"""The simulator interface, and the ManiSkill3 adapter that implements it.

Everything else in this package works against ``SimEnv``, so its logic can be tested on the CPU tier
with a fake. ``ManiSkillPickCube`` imports the simulator only when constructed. **It has not run:**
it was written from the ``mani_skill`` 3.0.1 source, and no episode has been produced with it.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

JOINT_STREAM = "joint_position"
Packet = dict[str, list[float]]


class SimulatorUnavailableError(RuntimeError):
    """The simulator stack is absent, or cannot start on this machine."""


@dataclass(frozen=True)
class StreamSpec:
    """One contract-v1 stream declaration. ``role`` is input, supervision_only or reference_only."""

    name: str
    kind: str
    frame_id: str
    units: list[str]
    shape: list[int]
    dtype: str
    role: str

    def to_manifest(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ActionSpec:
    """The action meaning. ``labels``, ``units``, ``lower`` and ``upper`` align by index."""

    representation: str
    labels: list[str]
    units: list[str]
    frame_id: str
    semantics: str
    lower: list[float]
    upper: list[float]

    def to_manifest(self) -> dict[str, Any]:
        return asdict(self)


@runtime_checkable
class SimEnv(Protocol):
    """A simulator that can save its initial state and replay actions from it.

    A ``Packet`` maps each declared stream name to its flat values, in that stream's units. Time
    advances by ``dt_ns`` per ``step``. ``state_restores`` counts every ``restore_state`` call, so a
    replay can show that state was restored once per repeat and never during an episode.
    """

    engine: str
    version: str
    dt_ns: int
    frames: list[str]
    action_spec: ActionSpec
    stream_specs: list[StreamSpec]

    @property
    def state_restores(self) -> int: ...

    def reset(self, seed: int) -> Packet: ...

    def save_state(self) -> bytes: ...

    def restore_state(self, state: bytes) -> Packet: ...

    def step(self, action: list[float]) -> Packet: ...

    def configuration(self) -> dict[str, Any]: ...

    def stack_identity(self) -> dict[str, Any]: ...

    def asset_manifest(self) -> dict[str, Any]: ...


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    return value.detach().cpu().numpy().tolist()


class ManiSkillPickCube:
    """``PickCubeSO100-v1`` on CPU physics (ADR-0004). Simulated SO-100; no transfer claim. Not run.

    Joint positions are in rad, positions in metres in the world frame. Initial state is saved as
    JSON, never pickled.
    """

    engine = "maniskill3"
    frames = ["joint_coordinates", "world"]

    def __init__(self, env_id: str = "PickCubeSO100-v1", max_episode_steps: int = 200) -> None:
        try:
            import gymnasium
            import mani_skill
            import mani_skill.envs
            import numpy
            import sapien
            import torch
        except ImportError as exc:
            raise SimulatorUnavailableError(f"robotics environment missing: {exc}") from exc
        self._torch = torch
        self._seed = 0
        self._restores = 0
        self._steps = 0
        self._stepped = False
        self._max_episode_steps = max_episode_steps
        self._env_id = env_id
        self._package_dir = Path(mani_skill.__file__).resolve().parent
        self.version = str(mani_skill.__version__)
        self._versions = {
            "mani_skill": self.version,
            "sapien": str(sapien.__version__),
            "torch": str(torch.__version__),
            "gymnasium": str(gymnasium.__version__),
            "numpy": str(numpy.__version__),
            "python": sys.version.split()[0],
            "platform": f"{platform.system()} {platform.machine()}",
        }
        try:
            self._env = gymnasium.make(
                env_id,
                obs_mode="state_dict",
                control_mode="pd_joint_pos",
                render_mode=None,
                render_backend="none",
                sim_backend="physx_cpu",
                max_episode_steps=max_episode_steps,
            )
        except RuntimeError as exc:
            raise SimulatorUnavailableError(f"simulator would not start: {exc}") from exc
        self._task = self._env.unwrapped
        self.dt_ns = int(1_000_000_000 / self._task.control_freq)
        joints = [joint.name for joint in self._task.agent.robot.get_active_joints()]
        self.action_spec = ActionSpec(
            representation="absolute_joint_position",
            labels=joints,
            units=["rad"] * len(joints),
            frame_id="joint_coordinates",
            semantics="ManiSkill3 pd_joint_pos targets for the simulated SO-100",
            lower=[float(v) for v in self._env.action_space.low.flatten()],
            upper=[float(v) for v in self._env.action_space.high.flatten()],
        )
        self.stream_specs = [
            StreamSpec(
                JOINT_STREAM,
                "state",
                "joint_coordinates",
                ["rad"] * len(joints),
                [len(joints)],
                "float64",
                "input",
            ),
            StreamSpec("object_position", "state", "world", ["m"] * 3, [3], "float64", "input"),
            StreamSpec("target_position", "state", "world", ["m"] * 3, [3], "float64", "input"),
            StreamSpec(
                "object_grasped", "other", "world", ["bool"], [1], "float64", "reference_only"
            ),
        ]

    @property
    def state_restores(self) -> int:
        return self._restores

    def _packet(self) -> Packet:
        """Read state. Contacts persist from the last physics step, so until a step has run since
        the last reset or restore, the cube is reported as not grasped: it starts on the table."""
        task = self._task
        grasped = self._stepped and bool(task.agent.is_grasping(task.cube)[0])
        return {
            JOINT_STREAM: [float(v) for v in task.agent.robot.get_qpos()[0]],
            "object_position": [float(v) for v in task.cube.pose.p[0]],
            "target_position": [float(v) for v in task.goal_site.pose.p[0]],
            "object_grasped": [float(grasped)],
        }

    def reset(self, seed: int) -> Packet:
        self._seed = seed
        self._steps = 0
        self._stepped = False
        self._env.reset(seed=seed)
        return self._packet()

    def save_state(self) -> bytes:
        state = _to_jsonable(self._task.get_state_dict())
        return json.dumps({"seed": self._seed, "state": state}, sort_keys=True).encode("utf-8")

    def _to_tensors(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._to_tensors(item) for key, item in value.items()}
        return self._torch.as_tensor(value, dtype=self._torch.float32)

    def restore_state(self, state: bytes) -> Packet:
        saved = json.loads(state.decode("utf-8"))
        self._restores += 1
        self._steps = 0
        self._stepped = False
        self._env.reset(seed=saved["seed"])
        self._task.set_state_dict(self._to_tensors(saved["state"]))
        return self._packet()

    def step(self, action: list[float]) -> Packet:
        if self._steps >= self._max_episode_steps:
            raise RuntimeError(f"episode passed its limit of {self._max_episode_steps} steps")
        self._steps += 1
        self._stepped = True
        command = self._torch.as_tensor(action, dtype=self._torch.float32).unsqueeze(0)
        self._env.step(command)
        return self._packet()

    def configuration(self) -> dict[str, Any]:
        return {
            "env_id": self._env_id,
            "embodiment_id": "maniskill3_so100",
            "control_mode": "pd_joint_pos",
            "sim_backend": "physx_cpu",
            "control_dt_ns": self.dt_ns,
            "max_episode_steps": self._max_episode_steps,
            "calibration": "none: simulation",
            "preprocessing": "none: state observations",
        }

    def stack_identity(self) -> dict[str, Any]:
        return dict(self._versions)

    def asset_manifest(self) -> dict[str, Any]:
        assets = self._package_dir / "assets" / "robots" / "so100"
        files = sorted(path for path in assets.rglob("*") if path.is_file())
        return {
            "robot": "so100",
            "files": {
                str(path.relative_to(assets)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in files
            },
        }
