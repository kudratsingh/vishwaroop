"""m3-protocol-3's size-checkable frames (kept from m3-protocol-2), its final-frame presence rule,
the pilot's stops and the zero-frame rule, on FABRICATED joint values and measurements. Standard
library only, so these run on the CPU tier."""

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
    CONTROL_SEEDS,
    NO_CUBE,
    PILOT_SEEDS,
    PRESENCE_FLOOR,
    SHOWS,
    SIGHTLINE_CLEARANCE_M,
    TOLERANCES_PATH,
    UNCERTAIN,
    UNCERTAIN_STATEMENT,
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
    visibility,
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
FAINT = FrameStats(red=((11, 300.0, 200.0),), green_count=400, green_centroid=(150.0, 350.0))
FLOOR = FrameStats(red=((12, 300.0, 200.0),), green_count=400, green_centroid=(150.0, 350.0))
BIG = FrameStats(red=((1800, 300.0, 200.0),), green_count=400, green_centroid=(150.0, 350.0))
TOL = Tolerances(
    a_lo=0.9,
    a_hi=1.1,
    merge_radius_px=30.0,
    first_frame_tolerance=0.5,
    goal_centroid_px=3.0,
    min_green_pixels=100,
)
MANIFEST = {
    "task_id": "PickCubeSO100-v1",
    "task_version": "m0-1",
    "seed": 10580,
    "asset_sha256s": ["a" * 64],
    "cube_half_size_m": 0.0125,
    "cube_colour": "red",
    "goal_position": [0.0, 0.1, 0.1],
}


def run(frames: list[FrameStats], size_frames: int) -> Any:
    ref = reference(MANIFEST, CUBE, SHAPE, TOL)
    return evaluate(dict(MANIFEST), [SHAPE] * len(frames), 0.0, frames, ref, TOL, size_frames)


def test_the_frozen_numbers() -> None:
    frozen = json.loads((ROOT / "evals/M3-protocol-3.json").read_text(encoding="utf-8"))
    rule = frozen["ET-M3-1"]
    assert frozen["protocol_version"] == "m3-protocol-3"
    assert "0.035 m" in rule["size_checkable_frames"]
    assert SIGHTLINE_CLEARANCE_M == 0.035
    assert "r >= 0.02" in rule["visibility"] and PRESENCE_FLOOR == 0.02
    assert "10920 to 10939" in rule["tolerance_pilot"]
    assert tuple(range(10920, 10940)) == PILOT_SEEDS
    assert "10580 to 10639" in rule["controls"] and tuple(range(10580, 10640)) == CONTROL_SEEDS
    assert "10520 + 10 x (t - 1) + i" in rule["injections"]
    assert "evals/M3-checker-tolerances-p3.json" in rule["tolerance_pilot"]
    assert Path("evals/M3-checker-tolerances-p3.json") == TOLERANCES_PATH
    assert "No presence band is set" in rule["tolerance_pilot"]


def test_visibility_classes() -> None:
    assert visibility(0.0) == NO_CUBE
    assert visibility(1e-9) == UNCERTAIN
    assert visibility(0.0199999) == UNCERTAIN
    assert visibility(0.02) == SHOWS
    assert visibility(12 / 600) == SHOWS
    assert visibility(3.0) == SHOWS


def test_the_size_band_applies_only_in_size_checkable_frames() -> None:
    assert run([CUBE, CUBE, MEDIUM], 2).passed
    failed = run([CUBE, MEDIUM, CUBE], 2).to_json()
    assert failed["failed_checks"] == ["cube_size"]
    assert failed["failures"]["cube_size"]["frame"] == 1
    assert failed["size_checkable_frames"] == 2 and failed["frames"] == 3


def test_the_final_frame_must_show_the_cube() -> None:
    for size_frames in (0, 1, 2):
        result = run([CUBE, CUBE, GONE], size_frames).to_json()
        assert result["failed_checks"] == ["cube_presence"]
        assert result["failures"]["cube_presence"]["frame"] == 2
        assert result["final_visibility"] == NO_CUBE
    assert run([CUBE, CUBE, GONE], 3).to_json()["failed_checks"] == ["cube_size", "cube_presence"]
    uncertain = run([CUBE, CUBE, FAINT], 1).to_json()
    assert uncertain["failed_checks"] == ["cube_presence"]
    assert uncertain["final_visibility"] == UNCERTAIN
    assert run([CUBE, CUBE, FLOOR], 1).passed


def test_no_presence_requirement_before_the_final_frame_after_the_checkable_ones() -> None:
    result = run([CUBE, GONE, FAINT, GONE, SMALL], 1).to_json()
    assert result["passed"]
    assert result["final_ratio"] == pytest.approx(216 / 600)
    assert result["longest_unseen_run"] == {"length": 3, "start": 1}
    assert run([CUBE, CUBE], 1).to_json()["longest_unseen_run"] == {"length": 0, "start": -1}


def test_no_upper_area_bound_outside_the_checkable_frames() -> None:
    assert run([CUBE, BIG, BIG], 1).passed
    assert run([CUBE, BIG, BIG], 2).to_json()["failed_checks"] == ["cube_size"]


def test_a_snapshot_render_without_a_cube_fails_size_and_presence() -> None:
    ref = reference(MANIFEST, GONE, SHAPE, TOL)
    result = evaluate(dict(MANIFEST), [SHAPE] * 2, 0.0, [CUBE, CUBE], ref, TOL, 0).to_json()
    assert result["failed_checks"] == ["cube_size", "cube_presence"]
    assert result["final_ratio"] is None


def test_an_unmeasured_final_frame_fails_presence() -> None:
    ref = reference(MANIFEST, CUBE, SHAPE, TOL)
    shapes = [SHAPE, (256, 256, 3)]
    result = evaluate(dict(MANIFEST), shapes, 0.0, [CUBE], ref, TOL, 0).to_json()
    assert result["failed_checks"] == ["frame_shape", "cube_presence"]
    empty = evaluate(dict(MANIFEST), [], None, [], ref, TOL, 0).to_json()
    assert "cube_presence" in empty["failed_checks"]


def test_a_candidate_with_no_size_checkable_frame_gets_no_size_check_only() -> None:
    result = run([CUBE, MEDIUM], 0).to_json()
    assert result["passed"] and result["size_checkable_frames"] == 0
    assert "gets no cube_size check" in ZERO_SIZE_CHECKABLE_STATEMENT
    assert run([CUBE, GONE], 0).to_json()["failed_checks"] == ["cube_presence"]
    assert "still gets cube_presence" in ZERO_SIZE_CHECKABLE_STATEMENT
    assert "uncertain visibility counts as not seen" in UNCERTAIN_STATEMENT


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


def candidate(
    seed: int,
    frames: tuple[FrameStats, ...],
    size_frames: int,
    moved: tuple[float, ...] | None = None,
    shift: float | None = 50.0,
    snapshot: FrameStats = CUBE,
) -> PilotCandidate:
    displacement = moved if moved is not None else (0.0,) * len(frames)
    return PilotCandidate(
        seed, snapshot, frames, 0.1, size_frames, displacement, goal_shift_min_px=shift
    )


def _pilot(size_frames: int, moved: float = 0.0, moved_at: int = 1) -> list[PilotCandidate]:
    frames = (CUBE, CUBE, CUBE, SMALL)
    displacement = tuple(moved if k == moved_at else 0.0 for k in range(len(frames)))
    return [candidate(10920, frames, size_frames, displacement), candidate(10921, frames, 3)]


def test_the_pilot_band_ignores_frames_that_are_not_size_checkable() -> None:
    result = pilot_tolerances(_pilot(3))
    assert result["size_band"] == pytest.approx([0.9, 1.1])
    assert "presence_band" not in result and result["presence_floor"] == PRESENCE_FLOOR
    assert result["protocol_version"] == "m3-protocol-3"
    assert Tolerances.from_json(result).a_lo == pytest.approx(0.9)
    assert result["sightline_clearance_m"] == SIGHTLINE_CLEARANCE_M
    summary = result["observed"]["size_checkable"]
    assert summary["min"] == 3 and summary["with_none"] == 0
    assert summary["share_of_frames_checked"] == pytest.approx(6 / 8)


def test_the_pilot_stops_when_more_than_two_candidates_lack_a_checkable_frame() -> None:
    frames = (CUBE, CUBE, CUBE, CUBE)
    short = [candidate(10920 + k, frames, 1) for k in range(3)]
    full = candidate(10930, frames, 4)
    assert pilot_tolerances([*short[:2], full])
    with pytest.raises(PilotStopError, match=r"\(1\).*more than 2") as stop:
        pilot_tolerances([*short, full])
    assert stop.value.observed["without_size_checkable_frame_1_to_T_minus_1"] == [
        10920,
        10921,
        10922,
    ]


def test_the_pilot_stops_when_a_checkable_frame_is_not_full_size() -> None:
    frames = (CUBE, MEDIUM, CUBE, CUBE)
    with pytest.raises(PilotStopError, match=r"\(3\).*not knowable"):
        pilot_tolerances([candidate(10920, frames, 3)])
    assert pilot_tolerances([candidate(10920, frames, 1)])


def test_the_pilot_reports_every_stop_that_holds() -> None:
    frames = (CUBE, MEDIUM, CUBE, CUBE)
    moved = (0.0, 0.01, 0.0, 0.0)
    with pytest.raises(PilotStopError) as stop:
        pilot_tolerances([candidate(10920, (*frames, GONE), 3, (*moved, 0.0), shift=None)])
    reasons = " ".join(stop.value.observed["stops"])
    for number in ("(2)", "(3)", "(7)", "(9)"):
        assert number in reasons
    assert "moved" in reasons and "not knowable" in reasons


def test_the_pilot_stops_when_a_final_frame_does_not_show_the_cube() -> None:
    for last in (GONE, FAINT):
        with pytest.raises(PilotStopError, match=r"\(7\) seed 10921: the final frame 3") as stop:
            pilot_tolerances(
                [candidate(10920, (CUBE,) * 4, 4), candidate(10921, (CUBE,) * 3 + (last,), 1)]
            )
        finals = stop.value.observed["final_frames"]
        assert finals["10921"]["final_visibility"] == visibility(
            last.red[0][0] / 600 if last.red else 0.0
        )
        assert finals["10920"]["final_visibility"] == SHOWS
    hidden_then_seen = (CUBE, GONE, GONE, FLOOR)
    result = pilot_tolerances([candidate(10920, hidden_then_seen, 1)])
    assert result["observed"]["final_frames"]["10920"]["longest_unseen_run"] == {
        "length": 2,
        "start": 1,
    }


def test_the_pilot_stops_when_the_merge_radius_reaches_the_duplicate_offset() -> None:
    def split(gap: float) -> FrameStats:
        return FrameStats(
            red=((500, 300.0, 200.0), (100, 300.0, 200.0 + gap)),
            green_count=400,
            green_centroid=(150.0, 350.0),
        )

    assert pilot_tolerances([candidate(10920, (CUBE, CUBE, split(54.0)), 1)])
    with pytest.raises(PilotStopError, match=r"\(8\) the merge radius 60.5"):
        pilot_tolerances([candidate(10920, (CUBE, CUBE, split(55.0)), 1)])


def test_the_pilot_stops_when_a_goal_shift_could_pass() -> None:
    off = FrameStats(red=((600, 300.0, 200.0),), green_count=400, green_centroid=(150.0, 355.0))
    frames = (CUBE, off, CUBE)
    result = pilot_tolerances([candidate(10920, frames, 1, shift=5.51)])
    assert result["goal_centroid_px"] == pytest.approx(5.5)
    assert result["observed"]["goal_shift_min_px"] == {"value": 5.51, "seed": 10920}
    with pytest.raises(PilotStopError, match=r"\(9\) the goal-centroid distance 5.5 px"):
        pilot_tolerances([candidate(10920, frames, 1, shift=5.5)])
    with pytest.raises(PilotStopError, match=r"\(9\) seeds \[10921\]"):
        pilot_tolerances([candidate(10920, frames, 1), candidate(10921, frames, 1, shift=None)])


def test_the_pilot_stops_on_a_snapshot_without_cube_or_goal() -> None:
    no_goal = FrameStats(red=CUBE.red, green_count=0, green_centroid=None)
    with pytest.raises(PilotStopError) as stop:
        pilot_tolerances(
            [
                candidate(10920, (CUBE,) * 3, 1, snapshot=GONE),
                candidate(10921, (CUBE,) * 3, 1, snapshot=no_goal),
            ]
        )
    reasons = stop.value.observed["stops"]
    assert "(6) seed 10920: the snapshot render shows no cube" in reasons
    assert "(6) seed 10921: the snapshot render shows no goal" in reasons


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
            "seed": 10580 + n,
            "passed": True,
            "failed_checks": [],
            "size_checkable_frames": 20,
            "frames": 100,
            "final_ratio": [1.0, 0.01, 0.0][n % 3],
            "final_visibility": [SHOWS, UNCERTAIN, NO_CUBE][n % 3],
            "longest_unseen_run": {"length": 0, "start": -1},
            "final_cube": {"on_table": True},
        }
        for n in range(60)
    ]
    injections = [
        {
            "type": t,
            "name": f"t{t}",
            "seed": 10520 + 10 * (t - 1) + i,
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
    assert result["size_check"]["cube_resized_steps"][0] == {
        "seed": 10540,
        "frozen_seed": 10540,
        "skipped_seeds": [],
        "step": 3,
        "T": 99,
    }
    shown = result["visibility"]["controls"]
    assert (shown["final_no_cube"], shown["final_uncertain"]) == (20, 20)
    assert shown["per_candidate"][1]["seed"] == 10581
    assert shown["per_candidate"][1]["final_cube"] == {"on_table": True}
    sources = result["visibility"]["injection_sources"]
    assert sources["final_not_measured"] == 60
    assert sources["per_candidate"][0]["seed"] == 10520
    assert "uncertain" in result["uncertain_visibility"]
    assert "ET-M3-2 has to judge presence and size" in result["limits"]


def test_every_pinned_file_has_its_pinned_sha256() -> None:
    import hashlib

    from vishwaroop.synth.et_m3_1 import FROZEN

    for path, expected in FROZEN.items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, path
    frozen = json.loads((ROOT / "evals/M3-protocol-3.json").read_text(encoding="utf-8"))
    for path, expected in frozen["builds_on"].items():
        assert FROZEN[Path(path)] == expected, path
    assert Path("evals/M3-protocol-3.json") in FROZEN
