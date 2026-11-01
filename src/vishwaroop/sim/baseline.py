"""The scripted pick-and-place controller, the only policy in WO-001.

It plans once from the first packet it sees and then follows that plan in joint space. It reads
only ``joint_position``, ``object_position`` and ``target_position``, knows nothing of the cube's
yaw, and takes nothing from the outcome code or the environment's reward. Its settings can make it
fail on purpose, for failure data.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .env import Packet
from .so100_kinematics import jaw_direction, solve_tool_down

Joints = list[float]


@dataclass(frozen=True)
class PlanSettings:
    """All lengths are in metres, joint values in rad and durations in control steps."""

    grasp_height_m: float = 0.012
    approach_height_m: float = 0.05
    carry_height_m: float = 0.05
    place_height_m: float = 0.0135
    gripper_contact_rad: float = -0.8
    gripper_open_rad: float = -0.3
    gripper_closed_rad: float = -0.8
    wrist_roll_rad: float = 1.5708
    jaw_clearance_m: float = 0.008
    grasp_offset_xy_m: tuple[float, float] = (0.0, 0.0)
    place_offset_xy_m: tuple[float, float] = (0.0, 0.0)
    release: bool = True
    arm_noise_rad: float = 0.0
    stop_after_steps: int | None = None
    approach_steps: int = 35
    descend_steps: int = 20
    close_steps: int = 20
    lift_steps: int = 20
    carry_steps: int = 30
    lower_steps: int = 20
    open_steps: int = 10
    rise_steps: int = 15
    hold_steps: int = 15


class PlanningError(ValueError):
    """No joint solution exists for a waypoint of the plan."""


# A tool-down pose over the table in front of the base, from which the solver starts.
_SEED_ARM: tuple[float, float, float, float] = (0.0, 0.4, 0.2, 1.0)
_ARM_LIMITS: tuple[tuple[float, float], ...] = (
    (-2.0, 2.0),
    (-1.5708, 1.5708),
    (-1.5708, 1.5708),
    (-1.8, 1.8),
)


def _interpolate(start: Joints, end: Joints, steps: int) -> list[Joints]:
    return [
        [s + (e - s) * (i + 1) / steps for s, e in zip(start, end, strict=True)]
        for i in range(steps)
    ]


def plan_pick_and_place(packet: Packet, settings: PlanSettings) -> list[Joints]:
    """Turn the first packet into a list of joint targets. Raises ``PlanningError`` if unreachable.

    Arm poses are solved with the gripper at its contact angle, where the tool point is midway
    between the jaws as they touch the cube. So the plan keeps the arm pose and changes only the
    gripper to open or close. The fixed jaw starts ``jaw_clearance_m`` further out, so that it
    clears a yawed cube's corners on the way down, and comes back in as the gripper closes.
    """
    contact = settings.gripper_contact_rad

    def solve(x: float, y: float, z: float, seed: Joints) -> Joints:
        solved = solve_tool_down((x, y, z), seed, limits=_ARM_LIMITS)
        if solved is None:
            raise PlanningError(f"no joint solution for tool point {(x, y, z)}")
        return solved

    start = list(packet["joint_position"])
    obj = packet["object_position"]
    target = packet["target_position"]
    grasp_x = obj[0] + settings.grasp_offset_xy_m[0]
    grasp_y = obj[1] + settings.grasp_offset_xy_m[1]
    place_x = target[0] + settings.place_offset_xy_m[0]
    place_y = target[1] + settings.place_offset_xy_m[1]
    seed = [*_SEED_ARM, settings.wrist_roll_rad, contact]

    at_grasp = solve(grasp_x, grasp_y, settings.grasp_height_m, seed)
    jaw = jaw_direction(at_grasp)
    clear_x = -jaw[0] * settings.jaw_clearance_m
    clear_y = -jaw[1] * settings.jaw_clearance_m
    above_grasp = solve(grasp_x + clear_x, grasp_y + clear_y, settings.approach_height_m, at_grasp)
    beside_grasp = solve(grasp_x + clear_x, grasp_y + clear_y, settings.grasp_height_m, above_grasp)
    lifted = solve(grasp_x, grasp_y, settings.carry_height_m, at_grasp)
    above_place = solve(place_x, place_y, settings.carry_height_m, lifted)
    at_place = solve(place_x, place_y, settings.place_height_m, above_place)
    risen = solve(place_x, place_y, settings.approach_height_m, at_place)

    opened = settings.gripper_open_rad
    closed = settings.gripper_closed_rad
    final = opened if settings.release else closed

    def pose(arm: Joints, gripper: float) -> Joints:
        return [*arm[:5], gripper]

    waypoints: list[tuple[Joints, int]] = [
        (pose(above_grasp, opened), settings.approach_steps),
        (pose(beside_grasp, opened), settings.descend_steps),
        (pose(at_grasp, closed), settings.close_steps),
        (pose(lifted, closed), settings.lift_steps),
        (pose(above_place, closed), settings.carry_steps),
        (pose(at_place, closed), settings.lower_steps),
        (pose(at_place, final), settings.open_steps),
        (pose(risen, final), settings.rise_steps),
    ]
    plan: list[Joints] = []
    previous = start
    for waypoint, steps in waypoints:
        plan += _interpolate(previous, waypoint, steps)
        previous = waypoint
    plan += [list(previous) for _ in range(settings.hold_steps)]
    return plan


# Settings that fail in a known way, one family per name (evals/M0-protocol.md section 4). The
# nominal family fails only where the plan cannot reach, or the physics goes against it. Offsets
# point towards the base, because the far edge of the task area is already at the arm's limit.
VARIANTS: dict[str, PlanSettings] = {
    "nominal": PlanSettings(),
    "missed-grasp": PlanSettings(grasp_offset_xy_m=(-0.04, 0.0)),
    "no-release": PlanSettings(release=False),
    "wrong-place": PlanSettings(place_offset_xy_m=(-0.03, 0.0)),
    "noisy-actions": PlanSettings(arm_noise_rad=0.01),
    "early-release": PlanSettings(place_height_m=0.05),
    "timeout": PlanSettings(stop_after_steps=120),
    # Held out in dev: settings never used in train (evals/M0-dataset-plan.json).
    "dev-grasp-offset": PlanSettings(grasp_offset_xy_m=(-0.012, 0.0)),
    "dev-place-offset": PlanSettings(place_offset_xy_m=(-0.016, 0.0)),
    "dev-noisy-actions": PlanSettings(arm_noise_rad=0.02),
}

# Long enough for the rubric's 11 samples, when nothing can be planned.
UNREACHABLE_HOLD_STEPS = 15


class ScriptedPickPlace:
    """A policy for ``record_episode``: plans on its first call, then follows the plan.

    An unreachable waypoint is a real failure of this controller, so the arm holds still and the
    independent rubric labels the episode. ``planning_error`` says that this is what happened.
    """

    def __init__(self, settings: PlanSettings | None = None, noise_seed: int = 0) -> None:
        self._settings = settings or PlanSettings()
        self._noise_seed = noise_seed
        self._plan: list[Joints] = []
        self.planning_error: str | None = None

    def __call__(self, packet: Packet, step: int) -> list[float] | None:
        if step == 0:
            self.planning_error = None
            try:
                self._plan = self._perturbed(plan_pick_and_place(packet, self._settings))
            except PlanningError as exc:
                self.planning_error = str(exc)
                self._plan = [list(packet["joint_position"])] * UNREACHABLE_HOLD_STEPS
        return self._plan[step] if step < len(self._plan) else None

    def _perturbed(self, plan: list[Joints]) -> list[Joints]:
        """Cut the plan short, and add seeded noise to the arm joints, as the settings ask."""
        settings = self._settings
        if settings.stop_after_steps is not None:
            plan = plan[: settings.stop_after_steps]
        if settings.arm_noise_rad == 0.0:
            return plan
        rng = random.Random(self._noise_seed)  # noqa: S311 - simulated noise, not cryptography
        noisy: list[Joints] = []
        for joints in plan:
            arm = [
                min(high, max(low, value + rng.gauss(0.0, settings.arm_noise_rad)))
                for value, (low, high) in zip(joints[:4], _ARM_LIMITS, strict=True)
            ]
            noisy.append([*arm, *joints[4:]])
        return noisy
