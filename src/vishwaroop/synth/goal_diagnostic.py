"""A ledgered diagnostic for drafting m3-protocol-4's goal check, on spent pilot seeds only.

    python -m vishwaroop.synth.goal_diagnostic

Run it from the repository root, in the robotics environment, at a clean commit. It re-renders the
unmodified episodes of the three spent ET-M3-1 pilot sequences, each exactly as its run built it:
m3-protocol-1's (10900 to 10919), m3-protocol-2's (10300 to 10319) and m3-protocol-3's (10920 to
10939, whose frame 114 of seed 10936 set protocol-3's goal-centroid tolerance and tripped its
stop 9). It asks two questions.

1. Does partial occlusion of the goal cause the goal-centroid drift? For every frame it records the
   goal's visibility v (the frame's green-mask pixel count over the snapshot render's) and the
   drift (the distance of the frame's green centroid from the snapshot render's), and it saves
   seed 10936 frame 114 and the snapshot render as images.
2. Does an eligibility rule "check the goal centroid only in frames with v >= theta" separate
   normal drift from a 0.03 m goal shift? For each candidate theta it takes the largest drift over
   eligible frames, widens it by 10% as the pilot rule does, and compares it with (a) the smallest
   unrounded image displacement of a 0.03 m goal move on any scene, over directions every 1 degree
   (protocol-3's stop 9), and (b) the drift a type-4 goal-pixel shift of 0.03 m would leave in each
   eligible frame, over the same 360 directions with the whole-pixel shift the injection applies:
   computed (the frame's drift vector plus the shift) and, in the direction worst for that frame,
   by applying ``inject.shift_goal_pixels`` to the frame and measuring it.

It also records, per episode and threshold, whether the final frame is eligible and the longest run
of ineligible frames. It writes ``goal_diagnostic.json`` and the images into a new run directory
and nothing into ``evals/``, and it touches no unused seed.

Exit codes: 0 done, 2 refused, 3 simulator not run.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..sim.env import ManiSkillPickCube, SimulatorUnavailableError
from ..sim.runlog import ledgered_run, require_code_root
from .checker import WIDENING, measure
from .et_m3_1 import _task
from .operators import et_m3_1_episodes
from .snapshot import projection_matrix, render_episode, take_snapshot

SEQUENCES = {
    "protocol-1 pilot": tuple(range(10900, 10920)),
    "protocol-2 pilot": tuple(range(10300, 10320)),
    "protocol-3 pilot": tuple(range(10920, 10940)),
}
THRESHOLDS = (0.0, 0.5, 0.7, 0.8, 0.9, 0.95, 0.99)
CANDIDATE = 0.9
BINS = (0.0, 0.25, 0.5, 0.7, 0.8, 0.9, 0.95, 1.0)
GOAL_MOVE_M = 0.03
DIRECTIONS_DEG = tuple(range(360))
FOCUS = (10936, 114)
RESULT = "goal_diagnostic.json"
IMAGES = "images"


def shift_vectors(projection: Any, goal: Sequence[float]) -> list[tuple[float, float]]:
    """The unrounded image displacement (row, column) of the goal moved 0.03 m in world xy, one per
    direction every 1 degree."""
    from .inject import project

    row0, col0 = project(projection, (goal[0], goal[1], goal[2]))
    out = []
    for degrees in DIRECTIONS_DEG:
        angle = math.radians(degrees)
        moved = (
            goal[0] + GOAL_MOVE_M * math.cos(angle),
            goal[1] + GOAL_MOVE_M * math.sin(angle),
            goal[2],
        )
        row1, col1 = project(projection, moved)
        out.append((row1 - row0, col1 - col0))
    return out


def whole_pixels(vector: tuple[float, float]) -> tuple[int, int]:
    """Round half up, as ``inject.goal_pixel_shift`` does."""
    return math.floor(vector[0] + 0.5), math.floor(vector[1] + 0.5)


def injected_drift(
    drift: tuple[float, float], shifts: Sequence[tuple[int, int]]
) -> tuple[float, int]:
    """The smallest drift left after adding each whole-pixel shift to a frame's drift vector, and
    the index of that shift (valid while the shifted goal is not clipped by the image edge)."""
    best = min(
        (math.hypot(drift[0] + dr, drift[1] + dc), index) for index, (dr, dc) in enumerate(shifts)
    )
    return best[0], best[1]


def bin_of(value: float) -> str:
    """The visibility bin label of v, e.g. '[0.9, 0.95)', with the last bin open above."""
    for low, high in itertools.pairwise(BINS):
        if low <= value < high:
            return f"[{low}, {high})"
    return f">= {BINS[-1]}"


def longest_ineligible(eligible: Sequence[bool]) -> dict[str, int]:
    """The longest run of consecutive ineligible frames: its length and first frame (-1 if none)."""
    best, start, length, begin = 0, -1, 0, 0
    for index, ok in enumerate(eligible):
        if not ok:
            if length == 0:
                begin = index
            length += 1
            if length > best:
                best, start = length, begin
        else:
            length = 0
    return {"length": best, "start": start}


def _save_png(array: Any, path: Path) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(array).save(path)


def run_episodes(env: Any, task: tuple[str, str, int], images: Path) -> list[dict[str, Any]]:
    import numpy as np

    from .inject import shift_goal_pixels

    episodes = []
    for group, seeds in SEQUENCES.items():
        for episode in et_m3_1_episodes(seeds):
            print(f"{group} seed {episode.seed} {episode.kind}", file=sys.stderr, flush=True)
            snapshot = take_snapshot(env, episode.seed, task[0], task[1])
            rendered = render_episode(env, snapshot, episode, task[2])
            ref = measure(snapshot.render)
            if ref.green_centroid is None or ref.green_count == 0:
                raise ValueError(f"seed {episode.seed}: the snapshot render shows no goal")
            centre = ref.green_centroid
            exact = shift_vectors(
                projection_matrix(snapshot.manifest), snapshot.manifest["goal_position"]
            )
            rounded = [whole_pixels(vector) for vector in exact]
            frames = []
            for index, frame in enumerate(rendered.frames):
                stats = measure(frame)
                row: dict[str, Any] = {"green": stats.green_count}
                if stats.green_centroid is not None:
                    vector = (
                        stats.green_centroid[0] - centre[0],
                        stats.green_centroid[1] - centre[1],
                    )
                    row["drift"] = math.hypot(*vector)
                    drift, worst = injected_drift(vector, rounded)
                    row["injected_drift_computed"] = drift
                    shifted = measure(shift_goal_pixels(frame, rounded[worst]))
                    row["injected_shift"] = list(rounded[worst])
                    row["injected_green"] = shifted.green_count
                    row["injected_drift_measured"] = (
                        None
                        if shifted.green_centroid is None
                        else math.hypot(
                            shifted.green_centroid[0] - centre[0],
                            shifted.green_centroid[1] - centre[1],
                        )
                    )
                frames.append(row)
                if (episode.seed, index) == FOCUS:
                    _save_png(np.asarray(frame), images / f"seed-{episode.seed}-frame-{index}.png")
                    _save_png(
                        np.asarray(snapshot.render), images / f"seed-{episode.seed}-snapshot.png"
                    )
            episodes.append(
                {
                    "group": group,
                    "seed": episode.seed,
                    "kind": episode.kind,
                    "T": rendered.steps,
                    "reference_green": ref.green_count,
                    "reference_centroid": list(centre),
                    "shift_min_exact_px": min(math.hypot(*vector) for vector in exact),
                    "shift_min_rounded_px": min(math.hypot(*vector) for vector in rounded),
                    "frames": frames,
                }
            )
    return episodes


def _visibility(episode: dict[str, Any], row: dict[str, Any]) -> float:
    return float(row["green"]) / float(episode["reference_green"])


def summarize(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Drift by visibility bin, the largest drifts, and, per threshold, the separation figures."""
    rows = [
        (episode, index, row)
        for episode in episodes
        for index, row in enumerate(episode["frames"])
        if "drift" in row
    ]
    bins: dict[str, dict[str, Any]] = {}
    for episode, index, row in rows:
        cell = bins.setdefault(bin_of(_visibility(episode, row)), {"frames": 0, "max_drift": None})
        cell["frames"] += 1
        if cell["max_drift"] is None or row["drift"] > cell["max_drift"]["value"]:
            cell["max_drift"] = {"value": row["drift"], "seed": episode["seed"], "frame": index}
    top = sorted(rows, key=lambda item: -item[2]["drift"])[:15]
    shift_min = min((e["shift_min_exact_px"], e["seed"]) for e in episodes)
    by_threshold: dict[str, Any] = {}
    for theta in THRESHOLDS:
        eligible = [item for item in rows if _visibility(item[0], item[2]) >= theta]
        worst = max(eligible, key=lambda item: item[2]["drift"]) if eligible else None
        tolerance = (1 + WIDENING) * worst[2]["drift"] if worst else 0.0
        computed = min(eligible, key=lambda item: item[2]["injected_drift_computed"], default=None)
        measured = [
            item
            for item in eligible
            if item[2]["injected_drift_measured"] is not None
            and item[2]["injected_green"] >= theta * item[0]["reference_green"]
        ]
        lowest = min(measured, key=lambda item: item[2]["injected_drift_measured"], default=None)
        finals = []
        runs = []
        for episode in episodes:
            ok = [
                "drift" in row and _visibility(episode, row) >= theta for row in episode["frames"]
            ]
            finals.append((ok[-1], episode["seed"]))
            runs.append((longest_ineligible(ok), episode["seed"]))
        longest = max(runs, key=lambda item: item[0]["length"])
        by_threshold[str(theta)] = {
            "eligible_frames": len(eligible),
            "eligible_share": len(eligible) / sum(len(e["frames"]) for e in episodes),
            "max_eligible_drift": None
            if worst is None
            else {
                "value": worst[2]["drift"],
                "seed": worst[0]["seed"],
                "frame": worst[1],
                "visibility": _visibility(worst[0], worst[2]),
            },
            "tolerance_widened": tolerance,
            "smallest_shift_exact_px": {"value": shift_min[0], "seed": shift_min[1]},
            "stop_9_would_hold": tolerance >= shift_min[0],
            "min_injected_drift_computed": None
            if computed is None
            else {
                "value": computed[2]["injected_drift_computed"],
                "seed": computed[0]["seed"],
                "frame": computed[1],
            },
            "eligible_frames_a_shift_could_pass_computed": sum(
                1 for item in eligible if item[2]["injected_drift_computed"] <= tolerance
            ),
            "min_injected_drift_measured_still_eligible": None
            if lowest is None
            else {
                "value": lowest[2]["injected_drift_measured"],
                "seed": lowest[0]["seed"],
                "frame": lowest[1],
            },
            "injected_frames_made_ineligible": len(eligible) - len(measured),
            "episodes_final_frame_ineligible": [seed for ok, seed in finals if not ok],
            "longest_ineligible_run": {**longest[0], "seed": longest[1]},
        }
    return {
        "episodes": len(episodes),
        "frames_with_green": len(rows),
        "frames_without_green": sum(len(e["frames"]) for e in episodes) - len(rows),
        "visibility_max": max(_visibility(e, r) for e, _, r in rows),
        "reference_green_range": [
            min(e["reference_green"] for e in episodes),
            max(e["reference_green"] for e in episodes),
        ],
        "drift_by_visibility_bin": bins,
        "largest_drifts": [
            {
                "seed": e["seed"],
                "frame": index,
                "drift": row["drift"],
                "visibility": _visibility(e, row),
            }
            for e, index, row in top
        ],
        "by_threshold": by_threshold,
    }


def focus(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    seed, index = FOCUS
    episode = next(e for e in episodes if e["seed"] == seed)
    row = episode["frames"][index]
    return {
        "seed": seed,
        "frame": index,
        "green": row["green"],
        "reference_green": episode["reference_green"],
        "visibility": _visibility(episode, row),
        "drift": row.get("drift"),
        "images": [f"{IMAGES}/seed-{seed}-frame-{index}.png", f"{IMAGES}/seed-{seed}-snapshot.png"],
    }


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    try:
        require_code_root()
        found = sorted(Path("runs").glob(f"*/{RESULT}*"))
        if found:
            raise ValueError(f"already run in {found[0]}")
        task = _task()
        env = ManiSkillPickCube(env_id=task[0], max_episode_steps=task[2], render=True)
        with ledgered_run(
            purpose=(
                "WO-021: goal-check diagnostic for drafting m3-protocol-4, spent pilot seeds only"
            ),
            config={"thresholds": list(THRESHOLDS), "candidate": CANDIDATE, "focus": list(FOCUS)},
            seeds={f"{group} first": seeds[0] for group, seeds in SEQUENCES.items()},
            env_lock={"stack": env.stack_identity()},
        ) as record:
            if record.dirty:
                raise ValueError("commit first, so the code note stays true")
            episodes = run_episodes(env, task, record.directory / IMAGES)
            report = {
                "run": record.directory.name,
                "code": record.code_note,
                "label": (
                    "measured, simulation; diagnostic on spent pilot seeds, not an exit-test result"
                ),
                "focus": focus(episodes),
                "summary": summarize(episodes),
                "summary_by_group": {
                    group: summarize([e for e in episodes if e["group"] == group])
                    for group in SEQUENCES
                },
                "episodes": episodes,
            }
            text = json.dumps(report, indent=1, sort_keys=True, allow_nan=False) + "\n"
            (record.directory / RESULT).write_text(text, encoding="utf-8")
            record.note = "goal diagnostic written"
            print(record.directory)
    except SimulatorUnavailableError as exc:
        print(f"not run: {exc}", file=sys.stderr)
        return 3
    except (ValueError, OSError, KeyError) as exc:
        print(f"refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
