"""ET-M3-1's deterministic scene-consistency checker, its tolerance pilot and its threshold.

Frozen in ``evals/M3-protocol-4.json`` (``m3-protocol-4``), which replaces the ET-M3-1 of
``evals/M3-exit-tests.json``. A candidate is a candidate manifest, frames 0 to T, and, for frame
eligibility only, its scene's initial joint and cube positions and its actions. For a frame, r is
its merged red area (the red components whose centroids lie within the merge radius of the largest
one's centroid) over the snapshot render's merged cube area, compared unrounded; the frame shows the
cube when r >= 0.02, shows no cube when r = 0, and its visibility is uncertain otherwise
(``visibility``). A candidate passes when every check holds:

- ``manifest``: the candidate manifest's fields equal the snapshot's;
- ``frame_shape``: every frame has the render's shape;
- ``first_frame``: frame 0's mean absolute difference from the snapshot's saved render, over every
  pixel and channel in uint8 units, is at most the first-frame tolerance;
- ``cube_size``: in every size-checkable frame (``size_checkable_frames``), r is within the size
  band [a_lo, a_hi]; a candidate with no size-checkable frame gets no ``cube_size`` check;
- ``cube_presence``: the final frame T shows the cube (r >= 0.02); a final frame that shows no cube
  or whose visibility is uncertain fails. No other frame has a presence requirement, and no frame
  outside the size-checkable ones has an upper area bound;
- ``extra_red``: in no frame does another red component of at least 0.25 x that area exist;
- ``goal_envelope``: in every frame with at least one green pixel, the green centroid's distance
  from p is at most the frame's goal envelope E = rho(min(v_g, 1)) r_g + 1.5 px (``goal_geometry``,
  ``goal_envelope_px``), v_g being the frame's green count over the goal's projected disc area;
- ``goal_final``: the final frame T has v_g >= 0.4; a final frame below it, or with no green, fails.

The goal's projected centre p and radius r_g come from the snapshot manifest only. A snapshot render
with no cube fails ``cube_size`` and ``cube_presence``, and one with no green pixel fails
``goal_envelope`` and ``goal_final``. The tolerances come from
``evals/M3-checker-tolerances-p4.json``, pinned by the sha256 the caller passes. The rules here
are standard library only; ``measure`` and ``first_frame_difference`` need numpy and scipy and
import them when called. Distances are in pixels, areas in pixel counts.
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

TOLERANCES_PATH = Path("evals/M3-checker-tolerances-p4.json")
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
    "cube_size",
    "cube_presence",
    "extra_red",
    "goal_envelope",
    "goal_final",
)
PILOT_SEEDS = tuple(range(10940, 10960))
CONTROL_SEEDS = tuple(range(10320, 10380))
PRESENCE_FLOOR = 0.02
SHOWS, NO_CUBE, UNCERTAIN = "shows the cube", "no cube", "uncertain"
SMALLEST_DUPLICATE_OFFSET_PX = 60.0  # min(hypot(*offset)) over inject.DUPLICATE_OFFSETS
GOAL_MOVE_MIN_M = 0.03  # inject.GOAL_MOVE_M[0]
GOAL_SHIFT_DIRECTIONS_DEG = tuple(range(360))
GOAL_RADIUS_M = 0.0125 * 1.25  # mani_skill 3.0.1 PickCube "so100" goal_thresh: the goal sphere
GOAL_MARGIN_PX = 1.5
GOAL_FINAL_FLOOR = 0.4
# The PickCube table's collision box (mani_skill 3.0.1 TableSceneBuilder): its top at z = 0 over
# x in [-0.7245, 0.4845] and y in [-1.209, 1.209]. For reporting only.
TABLE_TOP_X_M = (-0.12 - 1.209 / 2, -0.12 + 1.209 / 2)
TABLE_TOP_Y_M = (-2.418 / 2, 2.418 / 2)
RESTING_TOLERANCE_M = 0.005  # reporting only: a resting cube's centre is its half size above z = 0
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
    "A candidate with no size-checkable frame (n = 0) gets no cube_size check and still gets "
    "cube_presence and every other check; it is reported as size not checked. A cube-resize "
    "source with no size-checkable frame 1 to T - 1 is replaced by the next seed from 10260 up "
    "(to 10299) that has one."
)
UNCERTAIN_STATEMENT = (
    "A frame shows the cube when r >= 0.02, shows no cube when r = 0, and its visibility is "
    "uncertain when 0 < r < 0.02. Before the arm is first commanded near the camera-to-cube "
    "sightline, cube_size needs the whole cube at its size, so a missing or uncertain cube fails "
    "there. After that, a frame that shows no cube or is uncertain is accepted without deciding "
    "whether the cube is hidden or missing. At the final frame the cube must be seen: uncertain "
    "visibility counts as not seen and fails. A cube legitimately hidden at the final frame, or "
    "knocked off the table or out of view, is rejected, which the checker cannot tell from removal."
)
LIMITS_STATEMENT = (
    "A cube that disappears after the size-checkable frames and reappears before the end is not "
    "caught by cube_presence, and a size error after those frames is not caught by cube_size; an "
    "enlarged cube is caught only in size-checkable frames. ET-M3-1 shows that the checker catches "
    "a removal that persists to the end, a duplicate, and a resize that starts before the arm "
    "approaches. ET-M3-2 has to judge presence and size in the frames between. For the goal: a "
    "goal change undone before the final frame is caught only in frames where enough of the goal "
    "shows; a lasting change is judged at frame T, but is certain to be caught there only at or "
    "above the scene's guarantee level, so between v_g 0.4 and that level a lasting 0.03 m move "
    "whose moved-toward side is hidden at T can pass; extra green can pull a moved goal's centroid "
    "back. ET-M3-2 has to audit lasting goal shifts with the goal partly occluded in the final "
    "frame, temporary disappearances and late resizes."
)
GOAL_STATEMENT = (
    "The goal is judged against its projected centre and disc from the snapshot manifest, not the "
    "snapshot render. Every frame with green must have its green centroid within rho(min(v_g, 1)) "
    "r_g + 1.5 px of the projected centre, and the final frame must show v_g >= 0.4 of the goal. "
    "Hiding the goal at T fails; a lasting change is judged at T."
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


def visibility(ratio: float) -> str:
    """Whether a frame with merged-area ratio ``ratio`` (unrounded) shows the cube (r >= 0.02),
    shows no cube (r = 0), or has uncertain visibility (0 < r < 0.02)."""
    if ratio >= PRESENCE_FLOOR:
        return SHOWS
    if ratio == 0:
        return NO_CUBE
    return UNCERTAIN


def table_placement(position: Sequence[float], half_size_m: float) -> dict[str, Any]:
    """For reporting only: whether the cube centre is over the table top (within its xy footprint,
    z > 0, held or resting), whether it rests on it (also z within 0.005 m of the half size), and
    its height above the table top."""
    x, y, z = _point(position, "cube position")
    over = (
        TABLE_TOP_X_M[0] <= x <= TABLE_TOP_X_M[1] and TABLE_TOP_Y_M[0] <= y <= TABLE_TOP_Y_M[1]
    ) and z > 0
    return {
        "over_table": over,
        "resting_on_table": over and abs(z - half_size_m) <= RESTING_TOLERANCE_M,
        "height_above_table_top_m": z,
    }


def goal_geometry(snapshot_manifest: dict[str, Any]) -> tuple[tuple[float, float], float]:
    """The goal's projected centre p (row, column) and projected radius r_g (px), from the snapshot
    manifest's goal position and render camera only.

    With (x, y, z) = intrinsic_cv @ extrinsic_cv @ (goal, 1), p = (y / z, x / z), with no half-pixel
    correction; d is the norm of extrinsic_cv @ (goal, 1); r_g = f_x tan(asin(R / d)) with f_x =
    intrinsic_cv[0][0] and R the goal sphere's radius. Refuses an unexposed camera."""
    camera = snapshot_manifest.get("camera", {})
    if not camera.get("exposed"):
        raise ValueError(
            "the snapshot records no render camera, so the goal's projection is unknown"
        )
    k, pose = camera["intrinsic_cv"], camera["extrinsic_cv"]
    goal = _point(snapshot_manifest["goal_position"], "goal position")
    local = [
        sum(float(pose[i][j]) * goal[j] for j in range(3)) + float(pose[i][3]) for i in range(3)
    ]
    x, y, z = (sum(float(k[i][j]) * local[j] for j in range(3)) for i in range(3))
    distance = math.sqrt(sum(value * value for value in local))
    if z <= 0 or distance <= GOAL_RADIUS_M:
        raise ValueError("the goal is behind or at the camera")
    radius = float(k[0][0]) * math.tan(math.asin(GOAL_RADIUS_M / distance))
    return (y / z, x / z), radius


def segment_rho(fraction: float) -> float:
    """rho(f): the largest distance, in units of the radius, from a disc's centre to the centroid
    of a region covering ``fraction`` of the disc, which is the circular segment of that area;
    0 for f >= 1 (and 1 for f <= 0). Bisection on (theta - sin theta) / (2 pi) = f."""
    if fraction >= 1:
        return 0.0
    if fraction <= 0:
        return 1.0
    low, high = 0.0, 2 * math.pi
    for _ in range(80):
        theta = (low + high) / 2
        if (theta - math.sin(theta)) / (2 * math.pi) < fraction:
            low = theta
        else:
            high = theta
    theta = (low + high) / 2
    return 4 * math.sin(theta / 2) ** 3 / (3 * (theta - math.sin(theta)))


def goal_visibility(green_count: int, radius_px: float) -> float:
    """v_g: a frame's green-mask pixel count over the goal's projected disc area pi r_g^2."""
    return green_count / (math.pi * radius_px * radius_px)


def goal_envelope_px(visible: float, radius_px: float) -> float:
    """E = rho(min(v_g, 1)) r_g + 1.5 px."""
    return segment_rho(min(visible, 1.0)) * radius_px + GOAL_MARGIN_PX


def goal_frame(
    stats: FrameStats, centre: tuple[float, float], radius_px: float
) -> list[float | None]:
    """A frame's goal record, [v_g, the green centroid's distance from p, E], with the distance
    and E ``None`` when the frame has no green pixel (the record is written without NaN)."""
    seen = goal_visibility(stats.green_count, radius_px)
    if stats.green_count < 1 or stats.green_centroid is None:
        return [seen, None, None]
    return [seen, _distance(stats.green_centroid, centre), goal_envelope_px(seen, radius_px)]


def guarantee_level(radius_px: float, smallest_shift_px: float) -> float | None:
    """For reporting only: the smallest v with 2 (rho(v) r_g + 1.5) < s_min, s_min the scene's
    smallest whole-pixel 0.03 m goal shift; a final frame at or above it certainly catches a
    lasting 0.03 m move. ``None`` when even a fully visible goal would not (3 px >= s_min)."""
    if smallest_shift_px <= 2 * GOAL_MARGIN_PX:
        return None
    low, high = 0.0, 1.0
    for _ in range(60):
        middle = (low + high) / 2
        if 2 * goal_envelope_px(middle, radius_px) < smallest_shift_px:
            high = middle
        else:
            low = middle
    return high


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
    and the rest. There is no presence band; the presence floor 0.02 is frozen, not pilot-set."""

    a_lo: float
    a_hi: float
    merge_radius_px: float
    first_frame_tolerance: float

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
        if data.get("presence_floor") != PRESENCE_FLOOR:
            raise ValueError("the tolerances file's presence floor is not 0.02")
        if "presence_band" in data:
            raise ValueError("m3-protocol-4 sets no presence band, and the tolerances file has one")
        for name in ("goal_centroid_px", "min_green_pixels"):
            if name in data:
                raise ValueError(f"m3-protocol-4 sets no {name}, and the tolerances file has one")
        frozen_goal = {
            "goal_radius_m": GOAL_RADIUS_M,
            "goal_margin_px": GOAL_MARGIN_PX,
            "goal_final_floor": GOAL_FINAL_FLOOR,
        }
        for name, value in frozen_goal.items():
            if data.get(name) != value:
                raise ValueError(f"the tolerances file's {name} is not the frozen {value}")
        if not isinstance(data.get("size_band"), list) or len(data["size_band"]) != 2:
            raise ValueError("the tolerances file has no two-value size_band")
        a_lo, a_hi = (float(value) for value in data["size_band"])
        if not (BAND_LIMITS[0] < a_lo <= a_hi < BAND_LIMITS[1]):
            raise ValueError(f"band [{a_lo}, {a_hi}] is outside the frozen limits {BAND_LIMITS}")
        return cls(
            a_lo=a_lo,
            a_hi=a_hi,
            merge_radius_px=float(data["merge_radius_px"]),
            first_frame_tolerance=float(data["first_frame_tolerance"]),
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
    render_green: int
    goal_centre: tuple[float, float]
    goal_radius_px: float
    render_shape: tuple[int, ...]


def reference(
    snapshot_manifest: dict[str, Any],
    render_stats: FrameStats,
    render_shape: tuple[int, ...],
    tolerances: Tolerances,
) -> Reference:
    """The reference for a scene: its candidate fields, the snapshot render's cube area under the
    tolerances' merge radius and its green count, and the goal's projected centre and radius from
    the snapshot manifest (``goal_geometry``)."""
    area, _ = cube_area(render_stats, tolerances.merge_radius_px)
    centre, radius = goal_geometry(snapshot_manifest)
    return Reference(
        manifest=candidate_manifest(snapshot_manifest),
        cube_area=area,
        render_green=render_stats.green_count,
        goal_centre=centre,
        goal_radius_px=radius,
        render_shape=tuple(render_shape),
    )


@dataclass
class CheckResult:
    """A checker verdict: ``failed`` maps each failed check to its first failing frame (``None``
    for whole-candidate checks) and a short reason."""

    failed: dict[str, dict[str, Any]] = field(default_factory=dict)
    size_checkable_frames: int = 0
    frames: int = 0
    final_ratio: float | None = None
    longest_unseen_run: dict[str, int] | None = None
    final_goal_visibility: float | None = None
    max_goal_excess: dict[str, Any] | None = None
    goal_frames: list[list[float | None]] = field(default_factory=list)

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
            "final_ratio": self.final_ratio,
            "final_visibility": None if self.final_ratio is None else visibility(self.final_ratio),
            "longest_unseen_run": self.longest_unseen_run,
            "final_goal_visibility": self.final_goal_visibility,
            "max_goal_excess": self.max_goal_excess,
            "goal_frames": self.goal_frames,
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
    ``size_checkable_frames`` for the candidate: the size band applies in frames 0 to
    ``size_frames - 1`` only (in none when it is 0). ``cube_presence`` reads the final frame T only,
    which is ``stats[-1]`` when frame T has the render's shape (``check_candidate`` measures only
    such frames); otherwise frame T is not measured and ``cube_presence`` and ``goal_final`` fail
    with ``frame_shape``. ``goal_envelope`` reads every measured frame with a green pixel. The
    final frame's r and v_g, the longest run of frames with r < 0.02 and the largest goal excess
    (distance from p minus E) are recorded when every frame was measured."""
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
        result.fail("cube_size", None, "the snapshot render shows no cube")
        result.fail("cube_presence", None, "the snapshot render shows no cube")
    if ref.render_green <= 0:
        result.fail("goal_envelope", None, "the snapshot render shows no goal")
        result.fail("goal_final", None, "the snapshot render shows no goal")
    excess: tuple[float, int, float] | None = None
    ratios: list[float] = []
    for index, frame in enumerate(stats):
        if ref.cube_area > 0:
            merged, outside = cube_area(frame, tolerances.merge_radius_px)
            ratio = merged / ref.cube_area
            ratios.append(ratio)
            if index < size_frames and not tolerances.a_lo <= ratio <= tolerances.a_hi:
                result.fail(
                    "cube_size",
                    index,
                    f"area ratio {ratio:.4g} outside [{tolerances.a_lo}, {tolerances.a_hi}] in a "
                    "size-checkable frame",
                )
            if outside >= OTHER_COMPONENT_FRACTION * ref.cube_area:
                result.fail("extra_red", index, f"another red component of {outside} px")
        row = goal_frame(frame, ref.goal_centre, ref.goal_radius_px)
        result.goal_frames.append(row)
        if frame.green_count >= 1 and frame.green_centroid is not None:
            seen = goal_visibility(frame.green_count, ref.goal_radius_px)
            envelope = goal_envelope_px(seen, ref.goal_radius_px)
            gap = _distance(frame.green_centroid, ref.goal_centre)
            if excess is None or gap - envelope > excess[0]:
                excess = (gap - envelope, index, seen)
            if gap > envelope:
                result.fail(
                    "goal_envelope",
                    index,
                    f"green centroid {gap:.4g} px from the projected goal, > envelope "
                    f"{envelope:.4g} px (v_g {seen:.4g})",
                )
    final_measured = (
        bool(stats) and bool(frame_shapes) and tuple(frame_shapes[-1]) == ref.render_shape
    )
    if ref.cube_area > 0:
        if not final_measured:
            result.fail("cube_presence", None, "the final frame was not measured")
        elif visibility(ratios[-1]) != SHOWS:
            result.fail(
                "cube_presence",
                len(frame_shapes) - 1,
                f"the final frame's area ratio {ratios[-1]:.4g} is below {PRESENCE_FLOOR} "
                f"({visibility(ratios[-1])})",
            )
    if ref.render_green > 0:
        if not final_measured:
            result.fail("goal_final", None, "the final frame was not measured")
        else:
            final_seen = goal_visibility(stats[-1].green_count, ref.goal_radius_px)
            if final_seen < GOAL_FINAL_FLOOR:
                result.fail(
                    "goal_final",
                    len(frame_shapes) - 1,
                    f"the final frame shows v_g {final_seen:.4g} of the goal, below "
                    f"{GOAL_FINAL_FLOOR}",
                )
    if len(stats) == len(frame_shapes) and final_measured:
        if ratios:
            result.final_ratio = ratios[-1]
            result.longest_unseen_run = longest_unseen_run(ratios)
        result.final_goal_visibility = goal_visibility(stats[-1].green_count, ref.goal_radius_px)
        if excess is not None:
            result.max_goal_excess = {"value": excess[0], "frame": excess[1], "v_g": excess[2]}
    return result


def longest_unseen_run(ratios: Sequence[float]) -> dict[str, int]:
    """The longest run of consecutive frames with r < 0.02 (no cube or uncertain), as its length
    and first frame; length 0 and start -1 when every frame shows the cube."""
    best = (0, -1)
    start = -1
    for index, ratio in enumerate(ratios):
        if ratio < PRESENCE_FLOOR:
            if start < 0:
                start = index
            if index - start + 1 > best[0]:
                best = (index - start + 1, start)
        else:
            start = -1
    return {"length": best[0], "start": best[1]}


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
    displacement from its initial position at every frame (frame 0's is 0), the sightline
    clearance of the simulator's actual joint positions at every frame (for the record), the goal's
    projected centre and radius (``goal_geometry``), and the whole-pixel image shift of a 0.03 m
    goal move for each direction every 1 degree in xy, as a type-4 goal-pixel injection applies it
    (``None`` or empty if not measured, which stops the pilot)."""

    seed: int
    snapshot: FrameStats
    frames: tuple[FrameStats, ...]
    first_difference: float
    size_frames: int
    cube_displacement_m: tuple[float, ...]
    actual_clearance_m: tuple[float, ...] = ()
    goal: tuple[tuple[float, float], float] | None = None
    goal_shifts: tuple[tuple[int, int], ...] = ()


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

    Upper extremes (the size-checkable area ratios' maximum, the merge distance, the first-frame
    difference) are multiplied by 1.1 and the size-checkable area ratios' minimum by 0.9. The size
    band's extremes are over size-checkable frames only; the merge radius and first-frame
    tolerance are taken over every frame. No presence band is set, and nothing of the goal check is
    pilot-set (the 1.5 px margin and the 0.4 floor are frozen).

    Every stop condition of ``evals/M3-protocol-4.json`` is evaluated, and ``PilotStopError``
    lists all that hold, so that the owner is told: (1) more than 2 of the candidates without a
    size-checkable frame 1 to T - 1; (2) the simulator's cube more than 0.005 m from its start in a
    size-checkable frame; (3) a size-checkable frame's area ratio outside [0.95, 1.05]; (4) the
    widened size band not inside 0.36 < a_lo and a_hi < 2.56; (5) no size-checkable frame at all;
    (6) a snapshot render showing no cube or no goal; (7) a candidate's final frame not showing the
    cube (r < 0.02); (8) the merge radius 60 px or more; (9) a frame with green whose centroid is
    farther from p than its goal envelope, or a final frame with v_g < 0.4 (or a candidate whose
    goal geometry was not measured); (10) a final frame where, for some direction, the centroid
    plus the whole-pixel 0.03 m shift stays within the frame's envelope (or no shifts measured).
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
            f"(1) {len(short)} candidates (seeds {short}) have no size-checkable frame 1 to T - 1, "
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
            f"(2) seed {moved[1]}: the cube moved {moved[0]:.4g} m in a size-checkable frame, "
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
    observed["merge_radius_px"] = radius
    if radius >= SMALLEST_DUPLICATE_OFFSET_PX:
        stops.append(
            f"(8) the merge radius {radius:.4g} px is {SMALLEST_DUPLICATE_OFFSET_PX:g} px or more, "
            "the smallest duplicate offset, so a duplicate could merge with the cube"
        )
    every: list[tuple[float, int, int]] = []
    checkable: list[tuple[float, int, int]] = []
    finals: dict[str, dict[str, Any]] = {}
    for item in candidates:
        ref_area, _ = cube_area(item.snapshot, radius)
        if ref_area == 0:
            stops.append(f"(6) seed {item.seed}: the snapshot render shows no cube")
            continue
        ratios = [cube_area(stats, radius)[0] / ref_area for stats in item.frames]
        for index, value in enumerate(ratios):
            every.append((value, item.seed, index))
            if index < item.size_frames:
                checkable.append((value, item.seed, index))
        if ratios:
            finals[str(item.seed)] = {
                "final_ratio": ratios[-1],
                "final_visibility": visibility(ratios[-1]),
                "longest_unseen_run": longest_unseen_run(ratios),
            }
            if visibility(ratios[-1]) != SHOWS:
                stops.append(
                    f"(7) seed {item.seed}: the final frame {len(ratios) - 1} does not show the "
                    f"cube (area ratio {ratios[-1]:.4g} < {PRESENCE_FLOOR})"
                )
    observed["final_frames"] = finals
    observed["area_ratio_min"] = _extreme(every, min)
    observed["area_ratio_max"] = _extreme(every, max)
    observed["size_checkable_area_ratio_min"] = _extreme(checkable, min)
    observed["size_checkable_area_ratio_max"] = _extreme(checkable, max)
    size = (
        (_widen_down(min(checkable)[0]), _widen_up(max(checkable)[0])) if checkable else (0.0, 0.0)
    )
    observed["size_band"] = list(size)
    if not checkable:
        stops.append("(5) no pilot frame is size-checkable")
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
                f"(3) {len(outside)} size-checkable pilot frames have an area ratio outside "
                f"{list(PILOT_SIZE_PREMISE_BAND)} (worst {worst[0]:.4g}, seed {worst[1]} frame "
                f"{worst[2]}), so the cube's size is not knowable there"
            )
        if not (BAND_LIMITS[0] < size[0] and size[1] < BAND_LIMITS[1]):
            stops.append(
                f"(4) the widened size band [{size[0]:.4g}, {size[1]:.4g}] is not inside "
                "0.36 < a_lo and a_hi < 2.56"
            )
    excesses: list[tuple[float, int, int, float]] = []
    goal_finals: dict[str, dict[str, Any]] = {}
    for item in candidates:
        if item.snapshot.green_count <= 0 or item.snapshot.green_centroid is None:
            stops.append(f"(6) seed {item.seed}: the snapshot render shows no goal")
        if item.goal is None:
            stops.append(f"(9) seed {item.seed}: its goal geometry was not measured")
            continue
        goal_centre, goal_radius = item.goal
        for index, stats in enumerate(item.frames):
            if stats.green_count >= 1 and stats.green_centroid is not None:
                seen = goal_visibility(stats.green_count, goal_radius)
                gap = _distance(stats.green_centroid, goal_centre)
                excesses.append((gap - goal_envelope_px(seen, goal_radius), item.seed, index, seen))
        last = item.frames[-1]
        final_seen = goal_visibility(last.green_count, goal_radius)
        row: dict[str, Any] = {"v_g": final_seen, "projected_radius_px": goal_radius}
        if final_seen < GOAL_FINAL_FLOOR:
            stops.append(
                f"(9) seed {item.seed}: the final frame shows v_g {final_seen:.4g} of the goal, "
                f"below {GOAL_FINAL_FLOOR}"
            )
        if not item.goal_shifts:
            stops.append(f"(10) seed {item.seed}: no goal-move shifts were measured")
        elif last.green_centroid is not None:
            envelope = goal_envelope_px(final_seen, goal_radius)
            margin = min(
                math.hypot(
                    last.green_centroid[0] + dr - goal_centre[0],
                    last.green_centroid[1] + dc - goal_centre[1],
                )
                - envelope
                for dr, dc in item.goal_shifts
            )
            smallest = min(math.hypot(dr, dc) for dr, dc in item.goal_shifts)
            row.update(
                shifted_margin_px=margin,
                smallest_shift_px=smallest,
                guarantee_level=guarantee_level(goal_radius, smallest),
            )
            if margin <= 0:
                stops.append(
                    f"(10) seed {item.seed}: a whole-pixel 0.03 m goal shift leaves the final "
                    f"frame's centroid {-margin:.4g} px inside its envelope, so a type-4 "
                    "goal-pixel injection could pass at frame T"
                )
        goal_finals[str(item.seed)] = row
    worst_excess = max(excesses) if excesses else None
    observed["goal_max_excess_px"] = (
        None
        if worst_excess is None
        else {
            "value": worst_excess[0],
            "seed": worst_excess[1],
            "frame": worst_excess[2],
            "v_g": worst_excess[3],
        }
    )
    if worst_excess is not None and worst_excess[0] > 0:
        beyond = [item for item in excesses if item[0] > 0]
        stops.append(
            f"(9) {len(beyond)} pilot frames have the green centroid outside the goal envelope "
            f"(worst {worst_excess[0]:.4g} px beyond, seed {worst_excess[1]} frame "
            f"{worst_excess[2]}, v_g {worst_excess[3]:.4g})"
        )
    observed["goal_final_frames"] = goal_finals
    finals_seen = [(row["v_g"], seed) for seed, row in goal_finals.items()]
    observed["goal_final_v_g_min"] = (
        None if not finals_seen else {"value": min(finals_seen)[0], "seed": min(finals_seen)[1]}
    )
    margins = [
        (row["shifted_margin_px"], seed)
        for seed, row in goal_finals.items()
        if "shifted_margin_px" in row
    ]
    observed["goal_final_shifted_margin_min_px"] = (
        None if not margins else {"value": min(margins)[0], "seed": min(margins)[1]}
    )
    first = max((item.first_difference, item.seed) for item in candidates)
    observed["first_frame_difference"] = {"value": first[0], "seed": first[1]}
    if stops:
        raise PilotStopError("; ".join(stops), observed)
    return {
        "protocol_version": PROTOCOL_VERSION,
        "rule": (
            "ET-M3-1 tolerance pilot (m3-protocol-4): each tolerance is the pilot's observed "
            "extreme widened by 10%; the size band over size-checkable frames, subject to "
            "0.36 < a_lo and a_hi < 2.56; the merge radius and first-frame tolerance over every "
            "frame; no presence band (the presence floor 0.02 is frozen) and no goal tolerance "
            "(the goal envelope's 1.5 px margin and the 0.4 final floor are frozen)"
        ),
        "pilot_seeds": [item.seed for item in candidates],
        "widening": WIDENING,
        "sightline_clearance_m": SIGHTLINE_CLEARANCE_M,
        "masks": MASK_RULES,
        "size_band": list(size),
        "presence_floor": PRESENCE_FLOOR,
        "band_limits": list(BAND_LIMITS),
        "merge_radius_px": radius,
        "first_frame_metric": FIRST_FRAME_METRIC,
        "first_frame_tolerance": _widen_up(first[0]),
        "goal_radius_m": GOAL_RADIUS_M,
        "goal_margin_px": GOAL_MARGIN_PX,
        "goal_final_floor": GOAL_FINAL_FLOOR,
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


def visibility_summary(candidates: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """For reporting: how many candidates' final frames show no cube or are uncertain, how many
    show less than 0.4 of the goal, and how many show 0.4 or more but less than their scene's
    guarantee level; and each candidate's final r, final visibility, longest run of frames with
    r < 0.02, final v_g, largest goal excess, guarantee level and, where recorded, the simulator's
    final cube position (``final_cube``)."""
    keys = (
        "final_ratio",
        "final_visibility",
        "longest_unseen_run",
        "final_goal_visibility",
        "max_goal_excess",
        "goal_guarantee_level",
        "final_cube",
    )
    rows = [
        {"seed": item.get("seed"), **{key: item.get(key) for key in keys}} for item in candidates
    ]
    return {
        "candidates": len(rows),
        "final_no_cube": sum(1 for row in rows if row["final_visibility"] == NO_CUBE),
        "final_uncertain": sum(1 for row in rows if row["final_visibility"] == UNCERTAIN),
        "final_not_measured": sum(1 for row in rows if row["final_visibility"] is None),
        "final_goal_below_floor": sum(
            1
            for row in rows
            if row["final_goal_visibility"] is not None
            and row["final_goal_visibility"] < GOAL_FINAL_FLOOR
        ),
        "final_goal_below_guarantee_level": [
            {
                "seed": row["seed"],
                "final_goal_visibility": row["final_goal_visibility"],
                "goal_guarantee_level": row["goal_guarantee_level"],
            }
            for row in rows
            if row["final_goal_visibility"] is not None
            and row["goal_guarantee_level"] is not None
            and GOAL_FINAL_FLOOR <= row["final_goal_visibility"] < row["goal_guarantee_level"]
        ],
        "per_candidate": rows,
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
    ``failed_checks``. Controls and sources may also carry the ``CheckResult.to_json`` and
    ``final_cube`` fields that ``visibility_summary`` reports.
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
    sources = [{**item["source"], "seed": item["seed"]} for item in injections if "source" in item]
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
        "visibility": {
            "controls": visibility_summary(controls),
            "injection_sources": visibility_summary(sources),
        },
        "zero_size_checkable": ZERO_SIZE_CHECKABLE_STATEMENT,
        "uncertain_visibility": UNCERTAIN_STATEMENT,
        "goal_check": GOAL_STATEMENT,
        "limits": LIMITS_STATEMENT,
        "statement": PHYSICS_STATEMENT,
    }
