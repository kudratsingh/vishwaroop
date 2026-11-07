"""m3-protocol-2's size-checkable frames, the pilot's added stops and the zero-frame rule, on
FABRICATED joint values and measurements. Standard library only, so these run on the CPU tier."""

from __future__ import annotations

import itertools
import json
import math
import random
from pathlib import Path
from typing import Any

import pytest

from vishwaroop.sim.so100_kinematics import arm_segments, fingertips, segment_distance
from vishwaroop.synth.checker import (
    SIGHTLINE_CLEARANCE_M,
    ZERO_SIZE_CHECKABLE_STATEMENT,
    FrameStats,
    PilotCandidate,
    PilotStopError,
    Tolerances,
    camera_position,
    evaluate,
    pilot_tolerances,
    reference,
    sightline_clearance,
    size_checkable_frames,
    size_checkable_summary,
    verdict,
)

ROOT = Path(__file__).resolve().parents[1]
SHAPE = (512, 512, 3)
CUBE = FrameStats(red=((600, 300.0, 200.0),), green_count=400, green_centroid=(150.0, 350.0))
SMALL = FrameStats(red=((216, 300.0, 200.0),), green_count=400, green_centroid=(150.0, 350.0))
TWICE = FrameStats(
    red=((600, 300.0, 200.0), (600, 300.0, 300.0)), green_count=400, green_centroid=(150.0, 350.0)
)
HOME = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
MEDIUM = FrameStats(red=((420, 300.0, 200.0),), green_count=400, green_centroid=(150.0, 350.0))
GONE = FrameStats(red=(), green_count=400, green_centroid=(150.0, 350.0))
TOL = Tolerances(
    a_lo=0.9,
    a_hi=1.1,
    p_lo=0.5,
    p_hi=2.0,
    merge_radius_px=30.0,
    first_frame_tolerance=0.5,
    goal_centroid_px=3.0,
    min_green_pixels=100,
)
MANIFEST = {
    "task_id": "PickCubeSO100-v1",
    "task_version": "m0-1",
    "seed": 10400,
    "asset_sha256s": ["a" * 64],
    "cube_half_size_m": 0.0125,
    "cube_colour": "red",
    "goal_position": [0.0, 0.1, 0.1],
}


def run(frames: list[FrameStats], size_frames: int) -> Any:
    ref = reference(MANIFEST, CUBE, SHAPE, TOL)
    return evaluate(dict(MANIFEST), [SHAPE] * len(frames), 0.0, frames, ref, TOL, size_frames)


def test_the_frozen_numbers() -> None:
    frozen = json.loads((ROOT / "evals/M3-protocol-2.json").read_text(encoding="utf-8"))
    assert frozen["protocol_version"] == "m3-protocol-2"
    assert "0.035 m" in frozen["ET-M3-1"]["size_checkable_frames"]
    assert SIGHTLINE_CLEARANCE_M == 0.035
    assert "10300 to 10319" in frozen["ET-M3-1"]["tolerance_pilot"]
    assert "10400 to 10459" in frozen["ET-M3-1"]["controls"]
    assert "10200 + 10 x (t - 1) + i" in frozen["ET-M3-1"]["injections"]


def test_the_size_band_applies_only_in_size_checkable_frames() -> None:
    assert run([CUBE, CUBE, MEDIUM], 2).passed
    failed = run([CUBE, MEDIUM, CUBE], 2).to_json()
    assert failed["failed_checks"] == ["cube_size"]
    assert failed["failures"]["cube_size"]["frame"] == 1
    assert failed["size_checkable_frames"] == 2 and failed["frames"] == 3


def test_the_presence_band_applies_in_every_frame() -> None:
    for size_frames in (0, 1, 3):
        result = run([CUBE, CUBE, GONE], size_frames).to_json()
        assert "cube_area" in result["failed_checks"]
        assert result["failures"]["cube_area"]["frame"] == 2
    assert run([CUBE, SMALL], 1).to_json()["failed_checks"] == ["cube_area"]


def test_a_candidate_with_no_size_checkable_frame_gets_no_size_check_only() -> None:
    result = run([CUBE, MEDIUM], 0).to_json()
    assert result["passed"] and result["size_checkable_frames"] == 0
    assert "gets no cube_size check" in ZERO_SIZE_CHECKABLE_STATEMENT


def test_the_other_checks_still_apply_in_every_frame() -> None:
    assert run([CUBE, CUBE, TWICE], 1).to_json()["failed_checks"] == ["extra_red"]


def test_size_frames_must_be_a_count() -> None:
    for bad in (-1, True, 1.0):
        with pytest.raises(ValueError, match="size_frames"):
            run([CUBE], bad)  # type: ignore[arg-type]


def _brute_force(p1: Any, q1: Any, p2: Any, q2: Any, n: int = 200) -> float:
    def at(p: Any, q: Any, s: float) -> tuple[float, ...]:
        return tuple(a + (b - a) * s for a, b in zip(p, q, strict=True))

    return min(
        math.dist(at(p1, q1, i / n), at(p2, q2, j / n)) for i in range(n + 1) for j in range(n + 1)
    )


def test_segment_distance_matches_brute_force() -> None:
    rng = random.Random(0)
    for _ in range(25):
        points = [tuple(rng.uniform(-1, 1) for _ in range(3)) for _ in range(4)]
        exact = segment_distance(*points)  # type: ignore[arg-type]
        assert exact <= _brute_force(*points) + 1e-12
        assert exact == pytest.approx(_brute_force(*points), abs=0.02)
    assert segment_distance((0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)) == pytest.approx(1.0)
    assert segment_distance((0, 0, 0), (0, 0, 0), (0, 0, 2), (0, 0, 2)) == pytest.approx(2.0)


def test_the_skeleton_ends_at_the_jaw_tips() -> None:
    segments = arm_segments(HOME)
    fixed, moving = fingertips(HOME)
    assert len(segments) == 8
    assert segments[-3][1] == fixed
    assert math.dist(segments[-1][1], moving) < 1e-12
    for before, after in itertools.pairwise(segments[:6]):
        assert before[1] == after[0]


def test_frames_are_checkable_until_the_arm_first_nears_the_sightline() -> None:
    cube = fingertips(HOME)[0]
    camera = (cube[0] + 1.0, cube[1], cube[2] + 1.0)
    far = [0.0, -1.2, 1.2, 0.0, 0.0, 0.0]
    assert sightline_clearance(far, camera, cube) > SIGHTLINE_CLEARANCE_M
    assert sightline_clearance(HOME, camera, cube) <= SIGHTLINE_CLEARANCE_M
    assert size_checkable_frames(far, cube, camera, [far, far]) == 3
    assert size_checkable_frames(far, cube, camera, [far, HOME, far]) == 2
    assert size_checkable_frames(HOME, cube, camera, [far, far]) == 0


def test_the_rule_reads_no_frame() -> None:
    import inspect

    parameters = inspect.signature(size_checkable_frames).parameters
    assert list(parameters) == ["initial_joints", "initial_cube", "camera", "actions"]


def test_camera_position_needs_an_exposed_camera() -> None:
    pose = [[1, 0, 0, 0.3], [0, 1, 0, -0.2], [0, 0, 1, 0.5], [0, 0, 0, 1]]
    assert camera_position({"camera": {"exposed": True, "cam2world_gl": pose}}) == (0.3, -0.2, 0.5)
    with pytest.raises(ValueError, match="no render camera"):
        camera_position({"camera": {"exposed": False}})
    with pytest.raises(ValueError, match="finite"):
        sightline_clearance(HOME, (math.nan, 0, 0), (0, 0, 0))


def _pilot(size_frames: int, moved: float = 0.0, moved_at: int = 1) -> list[PilotCandidate]:
    frames = (CUBE, CUBE, CUBE, SMALL)
    displacement = tuple(moved if k == moved_at else 0.0 for k in range(len(frames)))
    return [
        PilotCandidate(10300, CUBE, frames, 0.1, size_frames, displacement),
        PilotCandidate(10301, CUBE, frames, 0.1, 3, (0.0,) * 4),
    ]


def test_the_pilot_band_ignores_frames_that_are_not_size_checkable() -> None:
    result = pilot_tolerances(_pilot(3))
    assert result["size_band"] == pytest.approx([0.9, 1.1])
    assert result["presence_band"] == pytest.approx([0.324, 1.1])
    assert result["sightline_clearance_m"] == SIGHTLINE_CLEARANCE_M
    summary = result["observed"]["size_checkable"]
    assert summary["min"] == 3 and summary["with_none"] == 0
    assert summary["share_of_frames_checked"] == pytest.approx(6 / 8)


def test_the_pilot_stops_when_more_than_two_candidates_lack_a_checkable_frame() -> None:
    frames = (CUBE, CUBE, CUBE, CUBE)
    short = [PilotCandidate(10300 + k, CUBE, frames, 0.1, 1, (0.0,) * 4) for k in range(3)]
    full = PilotCandidate(10310, CUBE, frames, 0.1, 4, (0.0,) * 4)
    assert pilot_tolerances([*short[:2], full])
    with pytest.raises(PilotStopError, match="more than 2") as stop:
        pilot_tolerances([*short, full])
    assert stop.value.observed["without_size_checkable_frame_1_to_T_minus_1"] == [
        10300,
        10301,
        10302,
    ]


def test_the_pilot_stops_when_a_checkable_frame_is_not_full_size() -> None:
    frames = (CUBE, MEDIUM, CUBE, CUBE)
    with pytest.raises(PilotStopError, match="not knowable"):
        pilot_tolerances([PilotCandidate(10300, CUBE, frames, 0.1, 3, (0.0,) * 4)])
    assert pilot_tolerances([PilotCandidate(10300, CUBE, frames, 0.1, 1, (0.0,) * 4)])


def test_the_pilot_reports_every_stop_that_holds() -> None:
    frames = (CUBE, MEDIUM, CUBE, CUBE)
    moved = (0.0, 0.01, 0.0, 0.0)
    with pytest.raises(PilotStopError) as stop:
        pilot_tolerances([PilotCandidate(10300, CUBE, frames, 0.1, 3, moved)])
    reasons = " ".join(stop.value.observed["stops"])
    assert "moved" in reasons and "not knowable" in reasons


def test_the_pilot_stops_when_the_cube_moves_in_a_checkable_frame() -> None:
    with pytest.raises(PilotStopError, match="moved"):
        pilot_tolerances(_pilot(3, moved=0.006, moved_at=2))
    assert pilot_tolerances(_pilot(3, moved=0.006, moved_at=3))  # not size-checkable: no stop
    assert pilot_tolerances(_pilot(3, moved=0.005, moved_at=2))


def test_the_size_check_summary() -> None:
    summary = size_checkable_summary([(0, 10), (1, 10), (5, 10), (20, 10)])
    assert summary == {
        "candidates": 4,
        "with_none": 1,
        "with_none_in_1_to_T_minus_1": 2,
        "min": 0,
        "median": 3.0,
        "max": 10,
        "share_of_frames_checked": pytest.approx(16 / 40),
    }
    assert size_checkable_summary([]) == {"candidates": 0}


def test_the_verdict_reports_how_often_the_size_check_ran() -> None:
    controls = [
        {
            "seed": 10400 + n,
            "passed": True,
            "failed_checks": [],
            "size_checkable_frames": 20,
            "frames": 100,
        }
        for n in range(60)
    ]
    injections = [
        {
            "type": t,
            "name": f"t{t}",
            "seed": 10200 + 10 * (t - 1) + i,
            "source_passed": True,
            "injected_passed": False,
            "failed_checks": ["x"],
            "detail": {"step": 3, "T": 99},
            "source": {"size_checkable_frames": 20, "frames": 100},
        }
        for t in range(1, 7)
        for i in range(10)
    ]
    result = verdict(controls, injections)
    assert result["passed"]
    assert result["size_check"]["controls"]["share_of_frames_checked"] == pytest.approx(0.2)
    assert len(result["size_check"]["cube_resized_steps"]) == 10
    assert result["size_check"]["cube_resized_steps"][0] == {"seed": 10220, "step": 3, "T": 99}
