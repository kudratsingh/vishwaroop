"""ET-M3-1's deterministic scene-consistency checker, its tolerance pilot and its threshold.

Frozen in ``evals/M3-protocol-2.json`` (``m3-protocol-2``), which replaces the ET-M3-1 of
``evals/M3-exit-tests.json``. A candidate is a candidate manifest, frames 0 to T, and, for frame
eligibility only, its scene's initial joint and cube positions and its actions. It passes when
every check holds:

- ``manifest``: the candidate manifest's fields equal the snapshot's;
- ``first_frame``: frame 0's mean absolute difference from the snapshot's saved render, over every
  pixel and channel in uint8 units, is at most the first-frame tolerance;
- ``cube_area``: in every frame, the red components whose centroids lie within the merge radius
  of the largest one's centroid have a total area within the presence band [p_lo, p_hi] x the
  snapshot render's cube area (protocol-1's band, kept for every frame);
- ``cube_size``: in every size-checkable frame (``size_checkable_frames``), that area is within the
  size band [a_lo, a_hi]; a candidate with no size-checkable frame gets no ``cube_size`` check;
- ``extra_red``: in no frame does another red component of at least 0.25 x that area exist;
- ``goal_centroid``: in every frame with at least the pilot's minimum count of green pixels (and at
  least one), the green pixels' centroid is within the goal-centroid distance of the snapshot's.

The tolerances come from ``evals/M3-checker-tolerances.json``, pinned by the sha256 the caller
passes. The rules here are standard library only; ``measure`` and ``first_frame_difference`` need
numpy and scipy and import them when called. Distances are in pixels, areas in pixel counts.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..sim.so100_kinematics import arm_segments, segment_distance
from .protocol import PROTOCOL_VERSION

TOLERANCES_PATH = Path("evals/M3-checker-tolerances.json")
WIDENING = 0.10
BAND_LIMITS = (0.36, 2.56)
OTHER_COMPONENT_FRACTION = 0.25
FIRST_FRAME_METRIC = "mean_absolute_difference_uint8"
MASK_RULES = {
    "red": {"R_gt": 120, "G_lt": 60, "B_lt": 60},
    "green": {"G_gt": 120, "R_lt": 80, "B_lt": 80},
    "connectivity": 8,
}
CANDIDATE_FIELDS = (
    "task_id",
    "task_version",
    "seed",
    "asset_sha256s",
    "cube_half_size_m",
    "cube_colour",
    "goal_position",
)
CHECKS = (
    "manifest",
    "frame_shape",
    "first_frame",
    "cube_area",
    "cube_size",
    "extra_red",
    "goal_centroid",
)
PILOT_SEEDS = tuple(range(10300, 10320))
CONTROL_SEEDS = tuple(range(10400, 10460))
SIGHTLINE_CLEARANCE_M = 0.035
MAX_PILOT_CUBE_DISPLACEMENT_M = 0.005
PILOT_SIZE_PREMISE_BAND = (0.95, 1.05)
MAX_PILOT_SHORT_CANDIDATES = 2
INJECTIONS = 60
MAX_FALSE_REJECTIONS = 3
Z95 = 1.959964
PHYSICS_STATEMENT = (
    "Controls and injection sources are physics renders, so this does not estimate false "
    "rejection on generated frames (ET-M3-2 measures that)."
)


ZERO_SIZE_CHECKABLE_STATEMENT = (
    "A candidate with no size-checkable frame gets no cube_size check; every other check, the "
    "cube_area presence band in every frame included, still applies, and the candidate is "
    "reported as size not checked. A cube-resize source with no size-checkable frame 1 to T - 1 "
    "is replaced by the next seed from 10800 up that has one."
)
LIMITS_STATEMENT = (
    "The cube_size band runs only in the frames before the arm first nears the sightline, so a "
    "size error that starts later is caught only if it leaves the every-frame cube_area band. "
    "Passing ET-M3-1 does not show that the checker judges cube size while the cube is grasped, "
    "carried or placed; ET-M3-2's audit has to judge cube size in frames that were not "
    "size-checked."
)


class PilotStopError(ValueError):
    """The pilot cannot set the tolerances by the frozen rule; the owner is told. ``observed``
    holds what the pilot saw."""

    def __init__(self, message: str, observed: dict[str, Any]) -> None:
        super().__init__(message)
        self.observed = observed


def sightline_clearance(
    joints: Sequence[float], camera: Sequence[float], cube: Sequence[float]
) -> float:
    """The shortest distance, in m, from the arm's skeleton at ``joints`` to the sightline: the
    segment from the render camera's centre to the cube's initial centre."""
    eye = _point(camera, "camera position")
    centre = _point(cube, "initial cube position")
    return min(
        segment_distance(start, end, eye, centre) for start, end in arm_segments(list(joints))
    )


def _point(values: Sequence[float], name: str) -> tuple[float, float, float]:
    point = tuple(float(value) for value in values)
    if len(point) != 3 or not all(math.isfinite(value) for value in point):
        raise ValueError(f"the {name} is not 3 finite values: {values!r}")
    return point[0], point[1], point[2]


def size_checkable_frames(
    initial_joints: Sequence[float],
    initial_cube: Sequence[float],
    camera: Sequence[float],
    actions: Sequence[Sequence[float]],
) -> int:
    """How many leading frames are size-checkable: n, so that frames 0 to n - 1 are.

    Frame 0 is when the arm's skeleton at the initial joint positions is more than 0.035 m from
    the sightline (``sightline_clearance``); frame t >= 1 when frame t - 1 is and the skeleton at
    action t (the pd_joint_pos target of control step t, all six values) is too. Only joint
    values, the initial cube position and the camera's centre enter, never a frame, so an image
    edit cannot change n. The sightline ends at the cube's centre, so a clearance above 0.035 m
    also keeps the skeleton that far from the cube; the pilot checks in the simulator that the
    cube has not moved in these frames.
    """
    for count, joints in enumerate([initial_joints, *actions]):
        if sightline_clearance(joints, camera, initial_cube) <= SIGHTLINE_CLEARANCE_M:
            return count
    return len(actions) + 1


def camera_position(snapshot_manifest: dict[str, Any]) -> tuple[float, float, float]:
    """The human render camera's centre in the world frame, from the snapshot manifest's
    ``cam2world_gl``; refuses a snapshot whose camera is not exposed."""
    camera = snapshot_manifest.get("camera", {})
    if not camera.get("exposed"):
        raise ValueError("the snapshot records no render camera, so no frame is size-checkable")
    pose = camera["cam2world_gl"]
    return _point([pose[0][3], pose[1][3], pose[2][3]], "camera position")


def candidate_manifest(snapshot_manifest: dict[str, Any]) -> dict[str, Any]:
    """The candidate manifest's fields, copied from a snapshot manifest."""
    return {name: json.loads(json.dumps(snapshot_manifest[name])) for name in CANDIDATE_FIELDS}


@dataclass(frozen=True)
class FrameStats:
    """One frame's measurement: its red components as (area, centroid row, centroid column),
    largest first, and its green pixel count and centroid (row, column)."""

    red: tuple[tuple[int, float, float], ...]
    green_count: int
    green_centroid: tuple[float, float] | None

    def to_json(self) -> dict[str, Any]:
        return {
            "red": [list(item) for item in self.red],
            "green_count": self.green_count,
            "green_centroid": None if self.green_centroid is None else list(self.green_centroid),
        }


def measure(frame: Any) -> FrameStats:
    """Measure one H x W x 3 uint8 frame with the frozen masks. Needs numpy and scipy."""
    from .masks import centroid, components, green_mask, red_mask

    green = green_mask(frame)
    return FrameStats(
        red=tuple(components(red_mask(frame))),
        green_count=int(green.sum()),
        green_centroid=centroid(green),
    )


def first_frame_difference(frame: Any, render: Any) -> float:
    """Mean absolute difference, in uint8 units over every pixel and channel. Shapes must match."""
    import numpy as np

    if frame.shape != render.shape:
        raise ValueError(f"frame shape {frame.shape} differs from the render's {render.shape}")
    return float(np.abs(frame.astype(np.int16) - render.astype(np.int16)).mean())


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def merge_distance(stats: FrameStats) -> float:
    """The largest distance from the largest red component's centroid to another's, 0 if there is
    at most one component."""
    if len(stats.red) < 2:
        return 0.0
    centre = stats.red[0][1:]
    return max(_distance(centre, other[1:]) for other in stats.red[1:])


def cube_area(stats: FrameStats, merge_radius: float) -> tuple[int, int]:
    """(merged area, largest area of a red component outside the merge radius); (0, 0) with no red.

    The merged area is the total over components whose centroids lie within ``merge_radius`` of the
    largest component's centroid, that component included.
    """
    if not stats.red:
        return 0, 0
    centre = stats.red[0][1:]
    merged = 0
    outside = 0
    for area, row, col in stats.red:
        if _distance(centre, (row, col)) <= merge_radius:
            merged += area
        else:
            outside = max(outside, area)
    return merged, outside


@dataclass(frozen=True)
class Tolerances:
    """The checker's pilot-set tolerances: the size band [a_lo, a_hi] for size-checkable frames,
    the presence band [p_lo, p_hi] for every frame, and the rest."""

    a_lo: float
    a_hi: float
    p_lo: float
    p_hi: float
    merge_radius_px: float
    first_frame_tolerance: float
    goal_centroid_px: float
    min_green_pixels: int

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Tolerances:
        if data.get("protocol_version") != PROTOCOL_VERSION:
            raise ValueError(f"tolerances are for {data.get('protocol_version')}, not ours")
        if data.get("masks") != MASK_RULES:
            raise ValueError("the tolerances file's mask rules are not the frozen ones")
        if data.get("first_frame_metric") != FIRST_FRAME_METRIC:
            raise ValueError("the tolerances file's first-frame metric is not the checker's")
        if data.get("other_component_fraction") != OTHER_COMPONENT_FRACTION:
            raise ValueError("the tolerances file's other-component fraction is not 0.25")
        if data.get("sightline_clearance_m") != SIGHTLINE_CLEARANCE_M:
            raise ValueError("the tolerances file's sightline clearance is not 0.035 m")
        for name in ("size_band", "presence_band"):
            if not isinstance(data.get(name), list) or len(data[name]) != 2:
                raise ValueError(f"the tolerances file has no two-value {name}")
        a_lo, a_hi = (float(value) for value in data["size_band"])
        if not (BAND_LIMITS[0] < a_lo <= a_hi < BAND_LIMITS[1]):
            raise ValueError(f"band [{a_lo}, {a_hi}] is outside the frozen limits {BAND_LIMITS}")
        p_lo, p_hi = (float(value) for value in data["presence_band"])
        if not 0 < p_lo <= p_hi:
            raise ValueError(f"presence band [{p_lo}, {p_hi}] does not exclude a missing cube")
        return cls(
            a_lo=a_lo,
            a_hi=a_hi,
            p_lo=p_lo,
            p_hi=p_hi,
            merge_radius_px=float(data["merge_radius_px"]),
            first_frame_tolerance=float(data["first_frame_tolerance"]),
            goal_centroid_px=float(data["goal_centroid_px"]),
            min_green_pixels=int(data["min_green_pixels"]),
        )


def load_tolerances(path: Path, expected_sha256: str) -> Tolerances:
    """Read the tolerances file, refused unless its sha256 is ``expected_sha256``."""
    raw = Path(path).read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise ValueError(f"{path} has sha256 {actual}, not the pinned {expected_sha256}")
    return Tolerances.from_json(json.loads(raw))


@dataclass(frozen=True)
class Reference:
    """What a candidate is checked against, from its scene's snapshot."""

    manifest: dict[str, Any]
    cube_area: int
    goal_centroid: tuple[float, float] | None
    render_shape: tuple[int, ...]


def reference(
    snapshot_manifest: dict[str, Any],
    render_stats: FrameStats,
    render_shape: tuple[int, ...],
    tolerances: Tolerances,
) -> Reference:
    """The reference for a scene: its candidate fields, and the snapshot render's cube area and
    goal centroid under the tolerances' merge radius."""
    area, _ = cube_area(render_stats, tolerances.merge_radius_px)
    return Reference(
        manifest=candidate_manifest(snapshot_manifest),
        cube_area=area,
        goal_centroid=render_stats.green_centroid,
        render_shape=tuple(render_shape),
    )


@dataclass
class CheckResult:
    """A checker verdict: ``failed`` maps each failed check to its first failing frame (``None``
    for whole-candidate checks) and a short reason."""

    failed: dict[str, dict[str, Any]] = field(default_factory=dict)
    size_checkable_frames: int = 0
    frames: int = 0

    @property
    def passed(self) -> bool:
        return not self.failed

    def fail(self, check: str, frame: int | None, reason: str) -> None:
        if check not in self.failed:
            self.failed[check] = {"frame": frame, "reason": reason, "frames": 0}
        self.failed[check]["frames"] += 1

    def to_json(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "size_checkable_frames": self.size_checkable_frames,
            "frames": self.frames,
            "failed_checks": [name for name in CHECKS if name in self.failed],
            "failures": {name: self.failed[name] for name in CHECKS if name in self.failed},
        }


def evaluate(
    manifest: dict[str, Any],
    frame_shapes: Sequence[tuple[int, ...]],
    first_difference: float | None,
    stats: Sequence[FrameStats],
    ref: Reference,
    tolerances: Tolerances,
    size_frames: int,
) -> CheckResult:
    """Apply every check to measured frames. ``first_difference`` is ``None`` when frame 0's shape
    differs from the render's, which fails ``frame_shape``. ``size_frames`` is
    ``size_checkable_frames`` for the candidate: the presence band applies in every frame, and the
    size band in frames 0 to ``size_frames - 1`` only (in none when it is 0)."""
    if isinstance(size_frames, bool) or not isinstance(size_frames, int) or size_frames < 0:
        raise ValueError(f"size_frames is a non-negative integer, not {size_frames!r}")
    result = CheckResult(size_checkable_frames=min(size_frames, len(stats)), frames=len(stats))
    differing = sorted(
        name for name in CANDIDATE_FIELDS if manifest.get(name) != ref.manifest.get(name)
    )
    if set(manifest) != set(CANDIDATE_FIELDS):
        differing.append("field set")
    if differing:
        result.fail("manifest", None, f"differs from the snapshot in {', '.join(differing)}")
    if not stats:
        result.fail("frame_shape", None, "no frames")
    for index, shape in enumerate(frame_shapes):
        if tuple(shape) != ref.render_shape:
            result.fail("frame_shape", index, f"shape {tuple(shape)} is not {ref.render_shape}")
    if first_difference is not None and first_difference > tolerances.first_frame_tolerance:
        result.fail(
            "first_frame",
            0,
            f"mean absolute difference {first_difference:.6g} > {tolerances.first_frame_tolerance}",
        )
    if ref.cube_area <= 0:
        result.fail("cube_area", None, "the snapshot render shows no cube")
    if ref.goal_centroid is None:
        result.fail("goal_centroid", None, "the snapshot render shows no goal")
    least_green = max(tolerances.min_green_pixels, 1)
    for index, frame in enumerate(stats):
        if ref.cube_area > 0:
            merged, outside = cube_area(frame, tolerances.merge_radius_px)
            ratio = merged / ref.cube_area
            if not tolerances.p_lo <= ratio <= tolerances.p_hi:
                result.fail(
                    "cube_area",
                    index,
                    f"area ratio {ratio:.4g} outside [{tolerances.p_lo}, {tolerances.p_hi}]",
                )
            if index < size_frames and not tolerances.a_lo <= ratio <= tolerances.a_hi:
                result.fail(
                    "cube_size",
                    index,
                    f"area ratio {ratio:.4g} outside [{tolerances.a_lo}, {tolerances.a_hi}] in a "
                    "size-checkable frame",
                )
            if outside >= OTHER_COMPONENT_FRACTION * ref.cube_area:
                result.fail("extra_red", index, f"another red component of {outside} px")
        if (
            ref.goal_centroid is not None
            and frame.green_count >= least_green
            and frame.green_centroid is not None
        ):
            gap = _distance(frame.green_centroid, ref.goal_centroid)
            if gap > tolerances.goal_centroid_px:
                result.fail(
                    "goal_centroid",
                    index,
                    f"goal centroid {gap:.4g} px from the snapshot's, "
                    f"> {tolerances.goal_centroid_px}",
                )
    return result


def check_candidate(
    manifest: dict[str, Any],
    frames: Sequence[Any],
    ref: Reference,
    render: Any,
    tolerances: Tolerances,
    size_frames: int,
) -> CheckResult:
    """Measure frames 0 to T and apply every check. ``render`` is the snapshot's saved render and
    ``size_frames`` the candidate's ``size_checkable_frames``."""
    shapes = [tuple(frame.shape) for frame in frames]
    first = None
    if frames and tuple(frames[0].shape) == tuple(render.shape):
        first = first_frame_difference(frames[0], render)
    usable = [frame for frame in frames if tuple(frame.shape) == ref.render_shape]
    if len(usable) != len(frames):
        size_frames = 0  # frame indices no longer line up; frame_shape fails the candidate anyway
    measured = [measure(frame) for frame in usable]
    return evaluate(manifest, shapes, first, measured, ref, tolerances, size_frames)


@dataclass(frozen=True)
class PilotCandidate:
    """One pilot candidate's measurements: its snapshot render's, every frame's, frame 0's
    difference from the snapshot render, its ``size_checkable_frames``, the simulator's cube
    displacement from its initial position at every frame (frame 0's is 0), and the sightline
    clearance of the simulator's actual joint positions at every frame (for the record)."""

    seed: int
    snapshot: FrameStats
    frames: tuple[FrameStats, ...]
    first_difference: float
    size_frames: int
    cube_displacement_m: tuple[float, ...]
    actual_clearance_m: tuple[float, ...] = ()


def _widen_up(value: float) -> float:
    return value * (1 + WIDENING)


def _widen_down(value: float) -> float:
    return value * (1 - WIDENING)


def _extreme(values: Sequence[tuple[float, int, int]], pick: Any) -> dict[str, Any] | None:
    if not values:
        return None
    value, seed, frame = pick(values)
    return {"value": value, "seed": seed, "frame": frame}


def pilot_tolerances(candidates: Sequence[PilotCandidate]) -> dict[str, Any]:
    """The tolerances by the frozen rule: each the pilot's observed extreme widened by 10%.

    Upper extremes (the area ratios' maxima, the merge distance, the first-frame difference, the
    goal-centroid distance) are multiplied by 1.1 and the area ratios' minima by 0.9. The size
    band's extremes are over size-checkable frames only, the presence band's and the others' over
    every frame. The minimum green count is the pilot's observed minimum.

    Every stop condition is evaluated, and ``PilotStopError`` lists all that hold, so that the
    owner is told: more than 2 candidates without a size-checkable frame 1 to T - 1; the
    simulator's cube more than 0.005 m from its start in a size-checkable frame; a size-checkable
    frame's area ratio outside [0.95, 1.05]; the size band not inside 0.36 < a_lo and
    a_hi < 2.56; a pilot frame showing no cube, so the presence band cannot exclude a missing one;
    no size-checkable frame at all; a snapshot render showing no cube or no goal.
    """
    if not candidates:
        raise ValueError("the pilot has no candidates")
    stops: list[str] = []
    observed: dict[str, Any] = {"candidates": len(candidates), "stops": stops}
    observed["size_checkable"] = size_checkable_summary(
        [(item.size_frames, len(item.frames)) for item in candidates]
    )
    observed["size_checkable_by_seed"] = {
        str(item.seed): {
            "size_checkable_frames": min(item.size_frames, len(item.frames)),
            "frames": len(item.frames),
        }
        for item in candidates
    }
    short = [item.seed for item in candidates if min(item.size_frames, len(item.frames) - 1) < 2]
    observed["without_size_checkable_frame_1_to_T_minus_1"] = short
    if len(short) > MAX_PILOT_SHORT_CANDIDATES:
        stops.append(
            f"{len(short)} candidates (seeds {short}) have no size-checkable frame 1 to T - 1, "
            f"more than {MAX_PILOT_SHORT_CANDIDATES}"
        )
    moved = max(
        (max(item.cube_displacement_m[: item.size_frames], default=0.0), item.seed)
        for item in candidates
    )
    observed["max_cube_displacement_in_size_checkable_frames_m"] = {
        "value": moved[0],
        "seed": moved[1],
    }
    if moved[0] > MAX_PILOT_CUBE_DISPLACEMENT_M:
        stops.append(
            f"seed {moved[1]}: the cube moved {moved[0]:.4g} m in a size-checkable frame, "
            f"more than {MAX_PILOT_CUBE_DISPLACEMENT_M} m"
        )
    actual = [
        (value, item.seed, index)
        for item in candidates
        for index, value in enumerate(item.actual_clearance_m[: item.size_frames])
    ]
    observed["min_actual_joint_clearance_in_size_checkable_frames_m"] = _extreme(actual, min)
    merge = max(
        (merge_distance(stats), item.seed, index)
        for item in candidates
        for index, stats in [(-1, item.snapshot), *enumerate(item.frames)]
    )
    radius = _widen_up(merge[0])
    observed["merge_distance_px"] = {"value": merge[0], "seed": merge[1], "frame": merge[2]}
    every: list[tuple[float, int, int]] = []
    checkable: list[tuple[float, int, int]] = []
    for item in candidates:
        ref_area, _ = cube_area(item.snapshot, radius)
        if ref_area == 0:
            stops.append(f"seed {item.seed}: the snapshot render shows no cube")
            continue
        for index, stats in enumerate(item.frames):
            ratio = (cube_area(stats, radius)[0] / ref_area, item.seed, index)
            every.append(ratio)
            if index < item.size_frames:
                checkable.append(ratio)
    observed["area_ratio_min"] = _extreme(every, min)
    observed["area_ratio_max"] = _extreme(every, max)
    observed["size_checkable_area_ratio_min"] = _extreme(checkable, min)
    observed["size_checkable_area_ratio_max"] = _extreme(checkable, max)
    presence = (_widen_down(min(every)[0]), _widen_up(max(every)[0])) if every else (0.0, 0.0)
    size = (
        (_widen_down(min(checkable)[0]), _widen_up(max(checkable)[0])) if checkable else (0.0, 0.0)
    )
    observed["presence_band"] = list(presence)
    observed["size_band"] = list(size)
    if every and presence[0] <= 0:
        low = min(every)
        stops.append(
            f"seed {low[1]} frame {low[2]} shows no cube, so the presence band cannot exclude a "
            "missing cube"
        )
    if not checkable:
        stops.append("no pilot frame is size-checkable")
    else:
        outside = [
            r
            for r in checkable
            if not PILOT_SIZE_PREMISE_BAND[0] <= r[0] <= PILOT_SIZE_PREMISE_BAND[1]
        ]
        observed["size_checkable_frames_outside_premise_band"] = len(outside)
        if outside:
            worst = max(outside, key=lambda r: abs(r[0] - 1))
            stops.append(
                f"{len(outside)} size-checkable pilot frames have an area ratio outside "
                f"{list(PILOT_SIZE_PREMISE_BAND)} (worst {worst[0]:.4g}, seed {worst[1]} frame "
                f"{worst[2]}), so the cube's size is not knowable there"
            )
        if not (BAND_LIMITS[0] < size[0] and size[1] < BAND_LIMITS[1]):
            stops.append(
                f"the widened size band [{size[0]:.4g}, {size[1]:.4g}] is not inside 0.36 < a_lo "
                "and a_hi < 2.56"
            )
    green = min(
        (stats.green_count, item.seed, index)
        for item in candidates
        for index, stats in enumerate(item.frames)
    )
    observed["min_green_pixels"] = {"value": green[0], "seed": green[1], "frame": green[2]}
    least_green = max(green[0], 1)
    gaps = [(0.0, -1, -1)]
    for item in candidates:
        centre = item.snapshot.green_centroid
        if centre is None:
            stops.append(f"seed {item.seed}: the snapshot render shows no goal")
            continue
        for index, stats in enumerate(item.frames):
            if stats.green_count >= least_green and stats.green_centroid is not None:
                gaps.append((_distance(stats.green_centroid, centre), item.seed, index))
    gap = max(gaps)
    observed["goal_centroid_px"] = {"value": gap[0], "seed": gap[1], "frame": gap[2]}
    first = max((item.first_difference, item.seed) for item in candidates)
    observed["first_frame_difference"] = {"value": first[0], "seed": first[1]}
    if stops:
        raise PilotStopError("; ".join(stops), observed)
    return {
        "protocol_version": PROTOCOL_VERSION,
        "rule": (
            "ET-M3-1 tolerance pilot (m3-protocol-2): each tolerance is the pilot's observed "
            "extreme widened by 10%; the size band over size-checkable frames, subject to "
            "0.36 < a_lo and a_hi < 2.56; the presence band over every frame"
        ),
        "pilot_seeds": [item.seed for item in candidates],
        "widening": WIDENING,
        "sightline_clearance_m": SIGHTLINE_CLEARANCE_M,
        "masks": MASK_RULES,
        "size_band": list(size),
        "presence_band": list(presence),
        "band_limits": list(BAND_LIMITS),
        "merge_radius_px": radius,
        "first_frame_metric": FIRST_FRAME_METRIC,
        "first_frame_tolerance": _widen_up(first[0]),
        "goal_centroid_px": _widen_up(gap[0]),
        "min_green_pixels": green[0],
        "other_component_fraction": OTHER_COMPONENT_FRACTION,
        "observed": observed,
    }


def size_checkable_summary(counts: Sequence[tuple[int, int]]) -> dict[str, Any]:
    """How often the size check runs, over (size-checkable frames, frames) per candidate: the
    candidates with none and with none in 1 to T - 1, the minimum, median and maximum count, and
    the share of all frames checked."""
    if not counts:
        return {"candidates": 0}
    checked = sorted(min(size, frames) for size, frames in counts)
    total = sum(frames for _, frames in counts)
    return {
        "candidates": len(counts),
        "with_none": sum(1 for size in checked if size == 0),
        "with_none_in_1_to_T_minus_1": sum(
            1 for size, frames in counts if min(size, frames - 1) < 2
        ),
        "min": checked[0],
        "median": statistics.median(checked),
        "max": checked[-1],
        "share_of_frames_checked": sum(checked) / total if total else 0.0,
    }


def credited(source_passed: bool, injected_passed: bool | None) -> bool:
    """An injection counts as rejected only when its unmodified source passes every check and the
    injected candidate fails at least one. ``None`` (not built) is never credited."""
    return source_passed and injected_passed is False


def wilson(count: int, total: int) -> tuple[float, float]:
    """The Wilson 95% interval for ``count`` of ``total``."""
    if total <= 0:
        raise ValueError("no trials")
    share = count / total
    centre = share + Z95 * Z95 / (2 * total)
    spread = Z95 * math.sqrt(share * (1 - share) / total + Z95 * Z95 / (4 * total * total))
    denominator = 1 + Z95 * Z95 / total
    return (centre - spread) / denominator, (centre + spread) / denominator


def verdict(
    controls: Sequence[dict[str, Any]], injections: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    """The frozen threshold: all 60 injections rejected under the credit rule, and at most 3 of the
    60 controls falsely rejected.

    ``controls`` items carry ``seed``, ``passed`` and ``failed_checks``. ``injections`` items carry
    ``type``, ``name``, ``seed``, ``source_passed``, ``injected_passed`` (``None`` if not built) and
    ``failed_checks``.
    """
    rejected = [
        item for item in injections if credited(item["source_passed"], item["injected_passed"])
    ]
    false = [item for item in controls if not item["passed"]]
    by_type: dict[str, dict[str, int]] = {}
    by_check: dict[str, int] = {}
    for item in injections:
        cell = by_type.setdefault(item["name"], {"injected": 0, "rejected": 0})
        cell["injected"] += 1
        if credited(item["source_passed"], item["injected_passed"]):
            cell["rejected"] += 1
            for check in item["failed_checks"]:
                by_check[check] = by_check.get(check, 0) + 1
    interval = list(wilson(len(false), len(controls))) if controls else None
    sources = [item["source"] for item in injections if "source" in item]
    size_check = {
        "controls": size_checkable_summary(
            [
                (item["size_checkable_frames"], item["frames"])
                for item in controls
                if "frames" in item
            ]
        ),
        "injection_sources": size_checkable_summary(
            [
                (item["size_checkable_frames"], item["frames"])
                for item in sources
                if "frames" in item
            ]
        ),
        "cube_resized_steps": [
            {
                "seed": item["seed"],
                "frozen_seed": item.get("frozen_seed", item["seed"]),
                "skipped_seeds": item.get("skipped_seeds", []),
                "T": item.get("source", {}).get("T"),
                **{k: v for k, v in item.get("detail", {}).items() if k in ("step", "T")},
            }
            for item in injections
            if item["type"] == 3
        ],
    }
    passed = (
        len(injections) == INJECTIONS
        and len(rejected) == INJECTIONS
        and len(controls) == len(CONTROL_SEEDS)
        and len(false) <= MAX_FALSE_REJECTIONS
    )
    return {
        "passed": passed,
        "injections": len(injections),
        "injections_rejected": len(rejected),
        "injections_not_credited": [
            {key: item[key] for key in ("type", "name", "seed", "source_passed", "injected_passed")}
            for item in injections
            if not credited(item["source_passed"], item["injected_passed"])
        ],
        "rejections_by_type": by_type,
        "rejections_by_check": by_check,
        "controls": len(controls),
        "false_rejections": len(false),
        "false_rejection_wilson95": interval,
        "false_rejected_controls": [
            {"seed": item["seed"], "failed_checks": item["failed_checks"]} for item in false
        ],
        "size_check": size_check,
        "zero_size_checkable": ZERO_SIZE_CHECKABLE_STATEMENT,
        "limits": LIMITS_STATEMENT,
        "statement": PHYSICS_STATEMENT,
    }
