"""ET-M3-1's deterministic scene-consistency checker, its tolerance pilot and its threshold.

Frozen in ``evals/M3-exit-tests.json``. A candidate is a candidate manifest and frames 0 to T. It
passes when every check holds:

- ``manifest``: the candidate manifest's fields equal the snapshot's;
- ``first_frame``: frame 0's mean absolute difference from the snapshot's saved render, over every
  pixel and channel in uint8 units, is at most the first-frame tolerance;
- ``cube_area``: in every frame, the red components whose centroids lie within the merge radius
  of the largest one's centroid have a total area within [a_lo, a_hi] x the snapshot render's cube
  area;
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
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
CHECKS = ("manifest", "frame_shape", "first_frame", "cube_area", "extra_red", "goal_centroid")
PILOT_SEEDS = tuple(range(10900, 10920))
CONTROL_SEEDS = tuple(range(10000, 10060))
INJECTIONS = 60
MAX_FALSE_REJECTIONS = 3
Z95 = 1.959964
PHYSICS_STATEMENT = (
    "Controls and injection sources are physics renders, so this does not estimate false "
    "rejection on generated frames (ET-M3-2 measures that)."
)


class PilotStopError(ValueError):
    """The pilot cannot set the tolerances by the frozen rule; the owner is told. ``observed``
    holds what the pilot saw."""

    def __init__(self, message: str, observed: dict[str, Any]) -> None:
        super().__init__(message)
        self.observed = observed


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
    """The checker's pilot-set tolerances."""

    a_lo: float
    a_hi: float
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
        a_lo, a_hi = (float(value) for value in data["cube_area_band"])
        if not (BAND_LIMITS[0] < a_lo <= a_hi < BAND_LIMITS[1]):
            raise ValueError(f"band [{a_lo}, {a_hi}] is outside the frozen limits {BAND_LIMITS}")
        return cls(
            a_lo=a_lo,
            a_hi=a_hi,
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
) -> CheckResult:
    """Apply every check to measured frames. ``first_difference`` is ``None`` when frame 0's shape
    differs from the render's, which fails ``frame_shape``."""
    result = CheckResult()
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
            if not tolerances.a_lo <= ratio <= tolerances.a_hi:
                result.fail(
                    "cube_area",
                    index,
                    f"area ratio {ratio:.4g} outside [{tolerances.a_lo}, {tolerances.a_hi}]",
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
) -> CheckResult:
    """Measure frames 0 to T and apply every check. ``render`` is the snapshot's saved render."""
    shapes = [tuple(frame.shape) for frame in frames]
    first = None
    if frames and tuple(frames[0].shape) == tuple(render.shape):
        first = first_frame_difference(frames[0], render)
    usable = [frame for frame in frames if tuple(frame.shape) == ref.render_shape]
    return evaluate(manifest, shapes, first, [measure(frame) for frame in usable], ref, tolerances)


@dataclass(frozen=True)
class PilotCandidate:
    """One pilot candidate's measurements: its snapshot render's, every frame's, and frame 0's
    difference from the snapshot render."""

    seed: int
    snapshot: FrameStats
    frames: tuple[FrameStats, ...]
    first_difference: float


def _widen_up(value: float) -> float:
    return value * (1 + WIDENING)


def _widen_down(value: float) -> float:
    return value * (1 - WIDENING)


def pilot_tolerances(candidates: Sequence[PilotCandidate]) -> dict[str, Any]:
    """The tolerances by the frozen rule: each the pilot's observed extreme widened by 10%.

    Upper extremes (the area ratio's maximum, the merge distance, the first-frame difference, the
    goal-centroid distance) are multiplied by 1.1 and the area ratio's minimum by 0.9. The minimum
    green count is the pilot's observed minimum. ``PilotStopError`` when the band is not inside
    0.36 < a_lo and a_hi < 2.56, or the pilot cannot measure a cube or goal on a snapshot render.
    """
    if not candidates:
        raise ValueError("the pilot has no candidates")
    observed: dict[str, Any] = {"candidates": len(candidates)}
    merge = max(
        (merge_distance(stats), item.seed, index)
        for item in candidates
        for index, stats in [(-1, item.snapshot), *enumerate(item.frames)]
    )
    radius = _widen_up(merge[0])
    observed["merge_distance_px"] = {"value": merge[0], "seed": merge[1], "frame": merge[2]}
    ratios = []
    for item in candidates:
        ref_area, _ = cube_area(item.snapshot, radius)
        if ref_area == 0:
            raise PilotStopError(f"seed {item.seed}: the snapshot render shows no cube", observed)
        for index, stats in enumerate(item.frames):
            ratios.append((cube_area(stats, radius)[0] / ref_area, item.seed, index))
    low, high = min(ratios), max(ratios)
    observed["area_ratio_min"] = {"value": low[0], "seed": low[1], "frame": low[2]}
    observed["area_ratio_max"] = {"value": high[0], "seed": high[1], "frame": high[2]}
    band = (_widen_down(low[0]), _widen_up(high[0]))
    observed["band"] = list(band)
    if not (BAND_LIMITS[0] < band[0] and band[1] < BAND_LIMITS[1]):
        raise PilotStopError(
            f"the widened band [{band[0]:.4g}, {band[1]:.4g}] is not inside 0.36 < a_lo and "
            "a_hi < 2.56, so no frozen band contains every pilot frame",
            observed,
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
            raise PilotStopError(f"seed {item.seed}: the snapshot render shows no goal", observed)
        for index, stats in enumerate(item.frames):
            if stats.green_count >= least_green and stats.green_centroid is not None:
                gaps.append((_distance(stats.green_centroid, centre), item.seed, index))
    gap = max(gaps)
    observed["goal_centroid_px"] = {"value": gap[0], "seed": gap[1], "frame": gap[2]}
    first = max((item.first_difference, item.seed) for item in candidates)
    observed["first_frame_difference"] = {"value": first[0], "seed": first[1]}
    return {
        "protocol_version": PROTOCOL_VERSION,
        "rule": (
            "ET-M3-1 tolerance pilot: each tolerance is the pilot's observed extreme widened by "
            "10%, the band subject to 0.36 < a_lo and a_hi < 2.56"
        ),
        "pilot_seeds": [item.seed for item in candidates],
        "widening": WIDENING,
        "masks": MASK_RULES,
        "cube_area_band": list(band),
        "band_limits": list(BAND_LIMITS),
        "merge_radius_px": radius,
        "first_frame_metric": FIRST_FRAME_METRIC,
        "first_frame_tolerance": _widen_up(first[0]),
        "goal_centroid_px": _widen_up(gap[0]),
        "min_green_pixels": green[0],
        "other_component_fraction": OTHER_COMPONENT_FRACTION,
        "observed": observed,
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
        "statement": PHYSICS_STATEMENT,
    }
