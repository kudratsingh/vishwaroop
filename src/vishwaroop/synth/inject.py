"""ET-M3-1's six mismatch injections, as ``evals/M3-protocol-2.json`` freezes them.

Pure functions on frames (H x W x 3 uint8 arrays, row 0 at the top, offsets as (row, column) in
pixels) and candidate manifests (``checker.candidate_manifest``). Nothing here touches the
simulator: the camera projection for a goal-pixel shift and the seed + 500 render for an initial
render mismatch are passed in. Frames before the injection step are passed through unchanged (the
same array objects); every altered frame is a new array, so a source candidate is never modified.

Injection ``i`` of type ``t`` (1 to 6, ``i`` 0 to 9) is on seed ``10200 + 10 (t - 1) + i``. Its
``rng = random.Random(seed)`` first draws the injection step: ``rng.randrange(1, T)`` for every
type but 3, and for type 3 ``rng.choice`` of the size-checkable frames 1 to T - 1 in ascending
order; then the type's own draws in the frozen order. ``InjectionError`` means an injection could
not be built as frozen; the scorer counts it as not rejected.
"""

from __future__ import annotations

import copy
import math
import random
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .masks import Array, bounding_box, centroid, green_mask, red_mask

FIRST_SEED = 10200
TYPES = {
    1: "object_removed",
    2: "object_duplicated",
    3: "cube_resized",
    4: "goal_or_task_changed",
    5: "asset_hash_broken",
    6: "initial_render_mismatch",
}
PER_TYPE = 10
RING_NEAR = (1, 6)
RING_FAR = (6, 12)
RING_MIN_PIXELS = 20
DUPLICATE_OFFSETS = ((0, 60), (0, -60), (60, 0), (-60, 0), (60, 60), (-60, -60))
RESIZE_FACTORS = (0.6, 1.6)
GOAL_MOVE_M = (0.03, 0.06)
GOAL_MANIFEST_I = (0, 3, 6, 9)
TASK_I = (1, 4, 7)
GOAL_PIXELS_I = (2, 5, 8)
TASK_ID_I = (1, 7)  # i = 4 changes the version instead (see task_change)
WRONG_TASK_ID = "PickCube-v1"
RENDER_SEED_OFFSET = 500


class InjectionError(ValueError):
    """The injection cannot be built as frozen on this source candidate."""


def injection_seed(t: int, i: int) -> int:
    """``10200 + 10 (t - 1) + i`` for type ``t`` in 1 to 6 and ``i`` in 0 to 9."""
    if t not in TYPES or not 0 <= i < PER_TYPE:
        raise ValueError(f"no injection of type {t}, index {i}")
    return FIRST_SEED + PER_TYPE * (t - 1) + i


def injection_plan() -> list[tuple[int, int, int]]:
    """(type, i, seed) for all 60 injections, in seed order."""
    return [(t, i, injection_seed(t, i)) for t in sorted(TYPES) for i in range(PER_TYPE)]


def _round(value: float) -> int:
    """Round half up, so a pixel position is the same on every platform."""
    return math.floor(value + 0.5)


def _ring(shape: tuple[int, ...], box: tuple[int, int, int, int], near: int, far: int) -> Array:
    """Pixels whose Chebyshev distance outside ``box`` is ``near`` to ``far``, inclusive."""
    r0, r1, c0, c1 = box
    rows = np.arange(shape[0])[:, None]
    cols = np.arange(shape[1])[None, :]
    dr = np.maximum(np.maximum(r0 - rows, rows - r1), 0)
    dc = np.maximum(np.maximum(c0 - cols, cols - c1), 0)
    distance = np.maximum(dr, dc)
    return (distance >= near) & (distance <= far)


def ring_colour(frame: Array, mask: Array) -> Array:
    """The per-channel median of the non-red, non-green pixels 1 to 6 px outside the mask's bounding
    box, or 6 to 12 px if the near ring has fewer than 20; rounded half up to uint8."""
    box = bounding_box(mask)
    usable = ~(red_mask(frame) | green_mask(frame))
    chosen = None
    for near, far in (RING_NEAR, RING_FAR):
        chosen = _ring(frame.shape, box, near, far) & usable
        if int(chosen.sum()) >= RING_MIN_PIXELS:
            break
    assert chosen is not None
    if not chosen.any():
        raise InjectionError("no non-red, non-green pixel within 12 px of the bounding box")
    median = np.median(frame[chosen].astype(np.float64), axis=0)
    return np.floor(median + 0.5).astype(np.uint8)


def remove_object(frame: Array) -> Array:
    """Type 1 on one frame: every red-mask pixel replaced by the ring colour."""
    out = frame.copy()
    mask = red_mask(frame)
    if mask.any():
        out[mask] = ring_colour(frame, mask)
    return out


def choose_offset(frame: Array) -> tuple[int, int]:
    """Type 2's offset: the first whose destination bounding box lies in the image and holds no red
    or green pixel in this (the injection) frame."""
    mask = red_mask(frame)
    if not mask.any():
        raise InjectionError("no red pixel in the injection frame to duplicate")
    r0, r1, c0, c1 = bounding_box(mask)
    occupied = mask | green_mask(frame)
    height, width = mask.shape
    for dr, dc in DUPLICATE_OFFSETS:
        top, bottom, left, right = r0 + dr, r1 + dr, c0 + dc, c1 + dc
        if top < 0 or left < 0 or bottom >= height or right >= width:
            continue
        if not occupied[top : bottom + 1, left : right + 1].any():
            return dr, dc
    raise InjectionError("no duplicate offset has a free destination in the injection frame")


def duplicate_object(frame: Array, offset: tuple[int, int]) -> Array:
    """Type 2 on one frame: the red-mask pixels copied unchanged to ``offset``, clipped to the
    image."""
    out = frame.copy()
    rows, cols = np.nonzero(red_mask(frame))
    to_rows, to_cols = rows + offset[0], cols + offset[1]
    inside = (to_rows >= 0) & (to_rows < frame.shape[0]) & (to_cols >= 0)
    inside &= to_cols < frame.shape[1]
    out[to_rows[inside], to_cols[inside]] = frame[rows[inside], cols[inside]]
    return out


def resize_object(frame: Array, factor: float) -> Array:
    """Type 3 on one frame: the cube removed as in type 1, then its bounding-box patch resized by
    nearest neighbour about the mask's centroid, and only the resized mask's pixels pasted."""
    mask = red_mask(frame)
    if not mask.any():
        return frame.copy()
    out = remove_object(frame)
    centre = centroid(mask)
    assert centre is not None
    cy, cx = centre
    r0, r1, c0, c1 = bounding_box(mask)
    height, width = mask.shape
    top = max(0, math.floor(cy + (r0 - 0.5 - cy) * factor) - 1)
    bottom = min(height - 1, math.ceil(cy + (r1 + 0.5 - cy) * factor) + 1)
    left = max(0, math.floor(cx + (c0 - 0.5 - cx) * factor) - 1)
    right = min(width - 1, math.ceil(cx + (c1 + 0.5 - cx) * factor) + 1)
    rows, cols = np.mgrid[top : bottom + 1, left : right + 1]
    source_rows = np.floor(cy + (rows - cy) / factor + 0.5).astype(np.int64)
    source_cols = np.floor(cx + (cols - cx) / factor + 0.5).astype(np.int64)
    inside = (source_rows >= r0) & (source_rows <= r1) & (source_cols >= c0)
    inside &= source_cols <= c1
    keep = np.zeros_like(inside)
    keep[inside] = mask[source_rows[inside], source_cols[inside]]
    out[rows[keep], cols[keep]] = frame[source_rows[keep], source_cols[keep]]
    return out


def project(projection: Array, point: tuple[float, float, float]) -> tuple[float, float]:
    """The pixel (row, column) of a world point under a 3 x 4 OpenCV projection, intrinsic times
    world-to-camera extrinsic; columns are u and rows v."""
    matrix = np.asarray(projection, dtype=np.float64)
    if matrix.shape != (3, 4):
        raise InjectionError(f"a projection is 3 x 4, not {matrix.shape}")
    u, v, w = matrix @ np.array([*point, 1.0])
    if w <= 0:
        raise InjectionError("the goal is behind the camera")
    return float(v / w), float(u / w)


def goal_pixel_shift(
    projection: Array, goal: list[float], distance_m: float, angle_rad: float
) -> tuple[int, int]:
    """The image displacement, in whole pixels, of the goal moved ``distance_m`` along
    ``angle_rad`` in the world xy plane."""
    moved = (
        goal[0] + distance_m * math.cos(angle_rad),
        goal[1] + distance_m * math.sin(angle_rad),
        goal[2],
    )
    row0, col0 = project(projection, (goal[0], goal[1], goal[2]))
    row1, col1 = project(projection, moved)
    shift = (_round(row1 - row0), _round(col1 - col0))
    if shift == (0, 0):
        raise InjectionError("the goal move projects to no whole-pixel shift")
    return shift


def shift_goal_pixels(frame: Array, offset: tuple[int, int]) -> Array:
    """Type 4 (i = 2, 5, 8) on one frame: the green pixels filled with their ring colour, as type 1
    fills the cube, and pasted unchanged at ``offset``, clipped to the image."""
    mask = green_mask(frame)
    if not mask.any():
        return frame.copy()
    out = frame.copy()
    out[mask] = ring_colour(frame, mask)
    rows, cols = np.nonzero(mask)
    to_rows, to_cols = rows + offset[0], cols + offset[1]
    inside = (to_rows >= 0) & (to_rows < frame.shape[0]) & (to_cols >= 0)
    inside &= to_cols < frame.shape[1]
    out[to_rows[inside], to_cols[inside]] = frame[rows[inside], cols[inside]]
    return out


def task_change(manifest: dict[str, Any], i: int) -> tuple[str, str]:
    """Type 4 (i = 1, 4, 7): the task id set to 'PickCube-v1' for i = 1 and 7, the version changed
    for i = 4. Returns the field and its new value."""
    if i in TASK_ID_I:
        if manifest["task_id"] == WRONG_TASK_ID:
            raise InjectionError(f"the task id is already {WRONG_TASK_ID}")
        return "task_id", WRONG_TASK_ID
    return "task_version", f"{manifest['task_version']}-changed"


def break_hash(digest: str) -> str:
    """The digest with its first hex digit replaced by the next one, modulo 16."""
    first = int(digest[0], 16)
    return f"{(first + 1) % 16:x}{digest[1:]}"


@dataclass(frozen=True)
class Injection:
    """One injected candidate: its frames and manifest, and every draw that built it."""

    type: int
    i: int
    seed: int
    frames: list[Array]
    manifest: dict[str, Any]
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return TYPES[self.type]


def inject(
    t: int,
    i: int,
    frames: list[Array],
    manifest: dict[str, Any],
    *,
    projection: Array | None = None,
    other_render: Array | None = None,
    size_frames: int | None = None,
) -> Injection:
    """Build injection ``i`` of type ``t`` from its unmodified source candidate.

    ``frames`` are frames 0 to T and ``manifest`` the candidate manifest, on the injection's seed.
    Type 4 with i in 2, 5, 8 needs the human render camera's 3 x 4 ``projection``; type 6 needs
    ``other_render``, the snapshot render of seed + 500. Type 3 needs ``size_frames``, the source
    candidate's ``checker.size_checkable_frames``, and is not built when no frame 1 to T - 1 is
    size-checkable.
    """
    seed = injection_seed(t, i)
    if manifest["seed"] != seed:
        raise InjectionError(f"the source candidate is on seed {manifest['seed']}, not {seed}")
    last = len(frames) - 1
    if last < 2:
        raise InjectionError(f"a frame injection needs T >= 2, and this candidate has T = {last}")
    rng = random.Random(seed)  # noqa: S311 - the frozen draw order, not cryptography
    if t == 3:
        if size_frames is None:
            raise ValueError("a cube-resize injection needs the source's size-checkable frames")
        checkable = list(range(1, min(size_frames, last)))
        if not checkable:
            raise InjectionError(
                f"no size-checkable frame in 1 to {last - 1} (size-checkable frames: {size_frames})"
            )
        step = rng.choice(checkable)
    else:
        step = rng.randrange(1, last)
    detail: dict[str, Any] = {"step": step, "T": last}
    out_frames = list(frames)
    out_manifest = copy.deepcopy(manifest)

    def alter(edit: Any) -> None:
        for index in range(step, last + 1):
            out_frames[index] = edit(frames[index])

    if t == 1:
        alter(remove_object)
    elif t == 2:
        offset = choose_offset(frames[step])
        detail["offset"] = list(offset)
        alter(lambda frame: duplicate_object(frame, offset))
    elif t == 3:
        factor = rng.choice(RESIZE_FACTORS)
        detail["factor"] = factor
        alter(lambda frame: resize_object(frame, factor))
    elif t == 4 and i in GOAL_MANIFEST_I:
        distance = rng.uniform(*GOAL_MOVE_M)
        angle = rng.uniform(0.0, 2 * math.pi)
        goal = list(out_manifest["goal_position"])
        goal[0] += distance * math.cos(angle)
        goal[1] += distance * math.sin(angle)
        out_manifest["goal_position"] = goal
        detail.update(subtype="manifest_goal_moved", distance_m=distance, angle_rad=angle)
    elif t == 4 and i in TASK_I:
        name, value = task_change(out_manifest, i)
        out_manifest[name] = value
        detail.update(subtype="task_changed", field=name, value=value)
    elif t == 4:
        if projection is None:
            raise InjectionError("a goal-pixel shift needs the camera projection")
        distance = rng.uniform(*GOAL_MOVE_M)
        angle = rng.uniform(0.0, 2 * math.pi)
        shift = goal_pixel_shift(projection, manifest["goal_position"], distance, angle)
        detail.update(
            subtype="goal_pixels_shifted", distance_m=distance, angle_rad=angle, shift=list(shift)
        )
        alter(lambda frame: shift_goal_pixels(frame, shift))
    elif t == 5:
        hashes = list(out_manifest["asset_sha256s"])
        if not hashes:
            raise InjectionError("the manifest lists no asset sha256")
        index = rng.randrange(len(hashes))
        hashes[index] = break_hash(hashes[index])
        out_manifest["asset_sha256s"] = hashes
        detail.update(asset_index=index, n_assets=len(hashes))
    else:
        if other_render is None:
            raise InjectionError("an initial render mismatch needs the seed + 500 render")
        if other_render.shape != frames[0].shape or other_render.dtype != frames[0].dtype:
            raise InjectionError("the seed + 500 render differs in shape or type from frame 0")
        out_frames[0] = other_render.copy()
        detail["render_seed"] = seed + RENDER_SEED_OFFSET
    return Injection(t, i, seed, out_frames, out_manifest, detail)
