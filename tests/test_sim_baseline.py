"""The scripted plan, without a simulator. Packets here are FABRICATED, with realistic numbers."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

from vishwaroop.sim.baseline import (
    VARIANTS,
    PlanningError,
    PlanSettings,
    ScriptedPickPlace,
    plan_pick_and_place,
)
from vishwaroop.sim.so100_kinematics import tool_point

ROOT = Path(__file__).resolve().parents[1]
REST = [0.034, -0.009, 0.0007, 1.579, 1.555, 0.0]
JOINT_LIMITS = [(-2.0, 2.0), (-1.5708, 1.5708), (-1.5708, 1.5708), (-1.8, 1.8), (-3.14, 3.14)]


def _packet(obj: tuple[float, float] = (-0.46, 0.02), goal: tuple[float, float] = (-0.44, -0.03)):
    return {
        "joint_position": list(REST),
        "object_position": [obj[0], obj[1], 0.0125],
        "target_position": [goal[0], goal[1], 0.07],
    }


def test_the_plan_fits_the_frozen_episode_length() -> None:
    assert len(plan_pick_and_place(_packet(), PlanSettings())) <= 200


def test_the_plan_starts_near_the_current_pose_and_moves_in_small_steps() -> None:
    plan = plan_pick_and_place(_packet(), PlanSettings())
    previous = REST
    for joints in plan:
        assert max(abs(a - b) for a, b in zip(joints, previous, strict=True)) < 0.2
        previous = joints


def test_every_arm_target_is_inside_the_joint_limits() -> None:
    for joints in plan_pick_and_place(_packet(), PlanSettings()):
        for value, (low, high) in zip(joints, JOINT_LIMITS, strict=False):
            assert low <= value <= high


def test_nominal_plan_visits_the_cube_and_ends_above_the_target() -> None:
    settings = PlanSettings()
    packet = _packet()
    plan = plan_pick_and_place(packet, settings)
    at_contact = [[*joints[:5], settings.gripper_contact_rad] for joints in plan]
    nearest = min(math.dist(tool_point(j), packet["object_position"]) for j in at_contact)
    assert nearest <= 0.001
    end = tool_point(at_contact[-1])
    assert math.dist(end[:2], packet["target_position"][:2]) <= 0.001
    assert end[2] == pytest.approx(settings.approach_height_m, abs=0.001)


def test_no_release_never_opens_after_closing() -> None:
    settings = VARIANTS["no-release"]
    plan = plan_pick_and_place(_packet(), settings)
    assert plan[-1][5] == settings.gripper_closed_rad


def test_nominal_ends_open() -> None:
    settings = VARIANTS["nominal"]
    assert plan_pick_and_place(_packet(), settings)[-1][5] == settings.gripper_open_rad


def test_offset_variants_move_the_right_waypoints() -> None:
    settings = VARIANTS["wrong-place"]
    packet = _packet()
    plan = plan_pick_and_place(packet, settings)
    end = tool_point([*plan[-1][:5], settings.gripper_contact_rad])
    assert math.dist(end[:2], packet["target_position"][:2]) == pytest.approx(
        math.hypot(*settings.place_offset_xy_m), abs=0.001
    )


def test_the_failure_offsets_stay_reachable_for_targets_at_the_far_edge() -> None:
    far = _packet(obj=(-0.43, 0.04), goal=(-0.43, 0.04))
    assert plan_pick_and_place(far, VARIANTS["wrong-place"])
    assert plan_pick_and_place(far, VARIANTS["missed-grasp"])


def test_unreachable_plan_raises() -> None:
    with pytest.raises(PlanningError):
        plan_pick_and_place(_packet(obj=(0.5, 0.5)), PlanSettings())


def test_an_unreachable_episode_holds_still_and_says_why() -> None:
    policy = ScriptedPickPlace(PlanSettings())
    packet = _packet(obj=(0.5, 0.5))
    first = policy(packet, 0)
    assert first == REST
    assert policy.planning_error is not None
    steps = [policy(packet, step) for step in range(1, 40)]
    assert steps[-1] is None
    held = [step for step in steps if step is not None]
    assert all(step == REST for step in held)
    # Enough for the rubric's 11 samples to be judged rather than called insufficient.
    assert len(held) + 2 >= 11


def test_a_new_episode_clears_the_last_planning_error() -> None:
    policy = ScriptedPickPlace()
    policy(_packet(obj=(0.5, 0.5)), 0)
    assert policy.planning_error is not None
    policy(_packet(), 0)
    assert policy.planning_error is None


def test_the_policy_ends_after_its_plan() -> None:
    policy = ScriptedPickPlace()
    packet = _packet()
    length = len(plan_pick_and_place(packet, PlanSettings()))
    assert policy(packet, 0) is not None
    assert policy(packet, length - 1) is not None
    assert policy(packet, length) is None


def test_the_controller_loads_no_outcome_or_replay_code() -> None:
    code = (
        "import json, sys; import vishwaroop.sim.baseline; "
        "print(json.dumps(sorted(m for m in sys.modules if m.startswith('vishwaroop'))))"
    )
    done = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    loaded = json.loads(done.stdout)
    assert "vishwaroop.sim.baseline" in loaded
    assert [name for name in loaded if "outcome" in name or "replay" in name] == []


def test_noise_is_seeded_bounded_and_leaves_the_gripper_alone() -> None:
    settings = VARIANTS["noisy-actions"]
    packet = _packet()
    clean = plan_pick_and_place(packet, settings)

    def actions(seed: int) -> list[list[float]]:
        policy = ScriptedPickPlace(settings, noise_seed=seed)
        return [action for step in range(len(clean)) if (action := policy(packet, step))]

    assert actions(5) == actions(5)
    assert actions(5) != actions(6)
    noisy = actions(5)
    assert noisy != clean
    for joints, plain in zip(noisy, clean, strict=True):
        assert joints[4:] == plain[4:]
        assert max(abs(a - b) for a, b in zip(joints[:4], plain[:4], strict=True)) < 0.1
        for value, (low, high) in zip(joints[:4], JOINT_LIMITS, strict=False):
            assert low <= value <= high


def test_the_timeout_family_ends_early() -> None:
    policy = ScriptedPickPlace(VARIANTS["timeout"])
    packet = _packet()
    assert policy(packet, 0) is not None
    assert policy(packet, 119) is not None
    assert policy(packet, 120) is None
    assert VARIANTS["timeout"].stop_after_steps == 120


def test_early_release_opens_at_carrying_height() -> None:
    settings = VARIANTS["early-release"]
    assert settings.place_height_m == settings.carry_height_m
    assert plan_pick_and_place(_packet(), settings)[-1][5] == settings.gripper_open_rad


def test_a_reference_stream_cannot_change_the_plan() -> None:
    plain = plan_pick_and_place(_packet(), PlanSettings())
    told = {**_packet(), "object_grasped": [1.0]}
    assert plan_pick_and_place(told, PlanSettings()) == plain


def test_the_failure_families_are_far_enough_off_to_fail_by_design() -> None:
    target_radius_m = 0.015625
    cube_half_width_m = 0.0125
    assert VARIANTS["nominal"].grasp_offset_xy_m == (0.0, 0.0)
    assert VARIANTS["nominal"].place_offset_xy_m == (0.0, 0.0)
    assert VARIANTS["nominal"].release is True
    assert math.hypot(*VARIANTS["missed-grasp"].grasp_offset_xy_m) > 2 * cube_half_width_m
    assert math.hypot(*VARIANTS["wrong-place"].place_offset_xy_m) > target_radius_m
    assert VARIANTS["no-release"].release is False
