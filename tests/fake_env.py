"""A FABRICATED deterministic environment and controller for CPU-tier tests. Not a simulator.

It stands in for ``SimEnv`` so the export, replay and negative-test logic can run without physics.
Nothing measured here says anything about ManiSkill3, or about any robot.
"""

from __future__ import annotations

import json
from typing import Any

from vishwaroop.sim.env import ActionSpec, Packet, StreamSpec

REST_HEIGHT = 0.0125
GRASP_RADIUS = 0.01


class FakeArmEnv:
    """A tool point moved directly by x, y, z targets, plus a gripper command above 0.5 for closed.

    The object follows the tool while grasped and drops to the table when released. The seed picks
    the object and target positions. ``drift`` adds a repeat-dependent offset, to imitate a
    simulator that does not reproduce. ``forces_state`` restores state on every step, to imitate a
    replay that forces intermediate states.
    """

    engine = "fake_fixture_no_simulator"
    version = "fixture-1"
    dt_ns = 50_000_000
    frames = ["joint_coordinates", "world"]

    def __init__(self, drift: float = 0.0, forces_state: bool = False) -> None:
        self._drift = drift
        self._forces_state = forces_state
        self._restores = 0
        self._tool = [0.0, 0.0, 0.1]
        self._gripper = 0.0
        self._object = [0.0, 0.0, REST_HEIGHT]
        self._target = [0.0, 0.0, REST_HEIGHT]
        self._grasped = False
        self.action_spec = ActionSpec(
            representation="absolute_joint_position",
            labels=["tool_x", "tool_y", "tool_z", "gripper"],
            units=["m", "m", "m", "unitless"],
            frame_id="joint_coordinates",
            semantics="FABRICATED test controller; not a real platform or limit",
            lower=[-1.0, -1.0, -1.0, 0.0],
            upper=[1.0, 1.0, 1.0, 1.0],
        )
        self.stream_specs = [
            StreamSpec(
                "joint_position", "state", "joint_coordinates", ["m"] * 4, [4], "float64", "input"
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
        return {
            "joint_position": [*self._tool, self._gripper],
            "object_position": list(self._object),
            "target_position": list(self._target),
            "object_grasped": [1.0 if self._grasped else 0.0],
        }

    def reset(self, seed: int) -> Packet:
        offset = (seed % 10) * 0.01
        self._tool = [0.0, 0.0, 0.1]
        self._gripper = 0.0
        self._object = [0.1 + offset, 0.0, REST_HEIGHT]
        self._target = [-0.1, offset, REST_HEIGHT]
        self._grasped = False
        return self._packet()

    def save_state(self) -> bytes:
        state = {
            "tool": self._tool,
            "gripper": self._gripper,
            "object": self._object,
            "target": self._target,
            "grasped": self._grasped,
        }
        return json.dumps(state, sort_keys=True).encode("utf-8")

    def _load(self, state: bytes) -> None:
        saved = json.loads(state.decode("utf-8"))
        self._tool = list(saved["tool"])
        self._gripper = float(saved["gripper"])
        self._object = list(saved["object"])
        self._target = list(saved["target"])
        self._grasped = bool(saved["grasped"])

    def restore_state(self, state: bytes) -> Packet:
        self._restores += 1
        self._load(state)
        return self._packet()

    def step(self, action: list[float]) -> Packet:
        if self._forces_state:
            self._restores += 1
        self._tool = [float(v) for v in action[:3]]
        self._tool[0] += self._drift * self._restores
        self._gripper = float(action[3])
        closed = self._gripper > 0.5
        near = all(
            abs(t - o) <= GRASP_RADIUS for t, o in zip(self._tool, self._object, strict=True)
        )
        if closed and (self._grasped or near):
            self._grasped = True
            self._object = list(self._tool)
        elif self._grasped:
            self._grasped = False
            self._object = [self._tool[0], self._tool[1], REST_HEIGHT]
        return self._packet()

    def configuration(self) -> dict[str, Any]:
        return {"fixture": "FABRICATED; not a simulator configuration"}

    def stack_identity(self) -> dict[str, Any]:
        return {"fixture": "FABRICATED; no stack"}

    def asset_manifest(self) -> dict[str, Any]:
        return {"fixture": "FABRICATED; no assets"}


def _path(start: list[float], end: list[float], steps: int, gripper: float) -> list[list[float]]:
    return [
        [*(s + (e - s) * (i + 1) / steps for s, e in zip(start, end, strict=True)), gripper]
        for i in range(steps)
    ]


def scripted_plan(
    seed: int, *, release: bool = True, target_miss: float = 0.0
) -> list[list[float]]:
    """A plan that picks up the object and sets it on the target. Options make it fail."""
    env = FakeArmEnv()
    start = env.reset(seed)
    home = start["joint_position"][:3]
    obj = start["object_position"]
    target = start["target_position"]
    above_obj = [obj[0], obj[1], 0.08]
    above_target = [target[0] + target_miss, target[1], 0.08]
    low_target = [target[0] + target_miss, target[1], REST_HEIGHT]
    plan = _path(home, above_obj, 3, 0.0)
    plan += _path(above_obj, obj, 3, 0.0)
    plan += _path(obj, obj, 1, 1.0)
    plan += _path(obj, above_obj, 3, 1.0)
    plan += _path(above_obj, above_target, 3, 1.0)
    plan += _path(above_target, low_target, 3, 1.0)
    final_gripper = 0.0 if release else 1.0
    plan += _path(low_target, above_target, 3, final_gripper)
    plan += _path(above_target, above_target, 12, final_gripper)
    return plan


def plan_policy(plan: list[list[float]]) -> Any:
    """A policy that follows a fixed plan and then ends the episode."""

    def policy(_: Packet, step: int) -> list[float] | None:
        return plan[step] if step < len(plan) else None

    return policy
