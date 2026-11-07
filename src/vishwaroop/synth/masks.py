"""ET-M3-1's colour masks and connected components, on H x W x 3 uint8 frames.

The rules are frozen in ``evals/M3-exit-tests.json``: red is R > 120, G < 60, B < 60; green is
G > 120, R < 80, B < 80; components use 8-connectivity. Rows and columns are pixel indices, row 0 at
the top. Needs numpy and scipy (pinned in ``config/robotics-requirements.macos.v2.txt``).
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy import ndimage

Array = Any  # numpy arrays; the CPU tier's type checker has no numpy stubs

RED_RULE = {"R_gt": 120, "G_lt": 60, "B_lt": 60}
GREEN_RULE = {"G_gt": 120, "R_lt": 80, "B_lt": 80}
CONNECTIVITY = 8
_EIGHT = np.ones((3, 3), dtype=bool)


def _channels(frame: Array) -> tuple[Array, Array, Array]:
    if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
        raise ValueError(f"a frame is H x W x 3 uint8, not {frame.shape} {frame.dtype}")
    return frame[..., 0], frame[..., 1], frame[..., 2]


def red_mask(frame: Array) -> Array:
    """Boolean H x W: R > 120, G < 60, B < 60."""
    r, g, b = _channels(frame)
    return (r > RED_RULE["R_gt"]) & (g < RED_RULE["G_lt"]) & (b < RED_RULE["B_lt"])


def green_mask(frame: Array) -> Array:
    """Boolean H x W: G > 120, R < 80, B < 80."""
    r, g, b = _channels(frame)
    return (g > GREEN_RULE["G_gt"]) & (r < GREEN_RULE["R_lt"]) & (b < GREEN_RULE["B_lt"])


def components(mask: Array) -> list[tuple[int, float, float]]:
    """The mask's 8-connected components as (area, centroid row, centroid column), largest first,
    ties broken by centroid row then column so the order is deterministic."""
    labels, count = ndimage.label(mask, structure=_EIGHT)
    if count == 0:
        return []
    flat = labels.ravel()
    rows, cols = np.indices(labels.shape)
    areas = np.bincount(flat, minlength=count + 1)[1:]
    row_sums = np.bincount(flat, weights=rows.ravel(), minlength=count + 1)[1:]
    col_sums = np.bincount(flat, weights=cols.ravel(), minlength=count + 1)[1:]
    found = [
        (int(area), float(row / area), float(col / area))
        for area, row, col in zip(areas, row_sums, col_sums, strict=True)
    ]
    return sorted(found, key=lambda item: (-item[0], item[1], item[2]))


def bounding_box(mask: Array) -> tuple[int, int, int, int]:
    """(first row, last row, first column, last column), inclusive. Refuses an empty mask."""
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    if rows.size == 0:
        raise ValueError("an empty mask has no bounding box")
    return int(rows[0]), int(rows[-1]), int(cols[0]), int(cols[-1])


def centroid(mask: Array) -> tuple[float, float] | None:
    """The mean (row, column) of the mask's pixels, or ``None`` if it has none."""
    rows, cols = np.nonzero(mask)
    if rows.size == 0:
        return None
    return float(rows.mean()), float(cols.mean())
