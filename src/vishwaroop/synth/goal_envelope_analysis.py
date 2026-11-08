"""A ledgered analysis, without simulation, for drafting m3-protocol-4's goal check.

    python -m vishwaroop.synth.goal_envelope_analysis

It reads two kinds of recorded inputs, each pinned below:
- the per-frame goal measurements of the ledgered diagnostic run ``20261108T044845Z_616d515d``
  (``goal_rule_diagnostic``: 60 spent pilot episodes, green counts and centroids, projected goal
  centres and 0.03 m shift vectors);
- the snapshot manifests the three spent pilot runs wrote.

It evaluates two goal checks on the 60 unmodified episodes and on computed type-4 goal-pixel shifts.

1. **The owner's 90% candidate.** A frame is eligible when its green count is at least 0.9 times
   the goal's full count. That full count is either the snapshot render's count or the goal
   sphere's projected area. Eligible frames are then checked against a pilot-style tolerance: the
   largest normal drift, widened by 10%.
2. **An occlusion envelope.** The goal's projected radius r (pixels) and centre p come from the
   manifest: goal position, camera pose and intrinsics, and the task's goal-sphere radius. The
   goal's visibility is w = green count / (pi r^2). Any region covering a fraction f of a disc has
   its centroid within rho(f) r of the centre, where rho is the centroid distance of the circular
   segment of area fraction f. So a frame's green centroid must lie within rho(min(w, 1)) r + m of
   p.

For a 0.03 m goal move (every 1 degree, the whole-pixel shift type 4 applies) at each injection step
1 to T - 1, the analysis records:
- whether the shifted frames from that step to T would all stay inside the check;
- whether the final frame shows enough of the goal.

Shifts are computed: the frame's centroid plus the shift, ignoring clipping at the image edge. The
first diagnostic measured that these agree with applied shifts.

It writes ``goal_envelope_analysis.json`` into a new run directory and nothing into ``evals/``. It
simulates nothing.

Exit codes: 0 done, 2 refused.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

from ..sim.runlog import ledgered_run, require_code_root
from .checker import WIDENING

DIAGNOSTIC = Path("runs/20261108T044845Z_616d515d/goal_rule_diagnostic.json")
PILOT_RUNS = (
    "20261107T083058Z_83f404c3",  # m3-protocol-1 pilot, 10900-10919
    "20261107T113546Z_783f6d54",  # m3-protocol-2 pilot, 10300-10319
    "20261108T040245Z_f9f36234",  # m3-protocol-3 pilot, 10920-10939
)
GOAL_RADIUS_M = 0.0125 * 1.25  # mani_skill 3.0.1 PickCube "so100" goal_thresh: the goal sphere
CANDIDATE_THETA = 0.9
MARGINS_PX = (1.0, 1.5, 2.0)
PROPOSED_MARGIN_PX = 1.5
FLOORS = (0.3, 0.4, 0.5)
PROPOSED_FLOOR = 0.4
OCCLUDED_SNAPSHOT = 1.05  # a scene whose frames show > 1.05 x the snapshot's green count
FOCUS = (10936, 114)
RESULT = "goal_envelope_analysis.json"


def segment_rho(fraction: float) -> float:
    """The largest distance, in units of the radius, from a disc's centre to the centroid of a
    region covering ``fraction`` of the disc: the circular segment of that area. 0 at 1 or more."""
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


def projected_radius_px(manifest: dict[str, Any]) -> float:
    """The goal sphere's projected radius: f_x tan(asin(R / d)), d the camera-to-goal distance."""
    camera = manifest["camera"]
    pose, k = camera["extrinsic_cv"], camera["intrinsic_cv"]
    goal = [float(value) for value in manifest["goal_position"]]
    local = [sum(pose[i][j] * goal[j] for j in range(3)) + pose[i][3] for i in range(3)]
    distance = math.sqrt(sum(value * value for value in local))
    return float(k[0][0]) * math.tan(math.asin(GOAL_RADIUS_M / distance))


def whole_pixels(vector: list[float]) -> tuple[int, int]:
    return math.floor(vector[0] + 0.5), math.floor(vector[1] + 0.5)


def _load_manifests() -> dict[int, dict[str, Any]]:
    out = {}
    for run in PILOT_RUNS:
        for path in sorted(Path("runs", run, "snapshots").glob("seed-*/snapshot.json")):
            manifest = json.loads(path.read_text(encoding="utf-8"))
            out[int(manifest["seed"])] = manifest
    return out


def _frames(episode: dict[str, Any], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    radius = projected_radius_px(manifest)
    area = math.pi * radius * radius
    centre = episode["projected_centre"]
    rows = []
    for row in episode["frames"]:
        item: dict[str, Any] = {"w": row["green"] / area, "green": row["green"]}
        if row["centroid"] is not None:
            item["d"] = (row["centroid"][0] - centre[0], row["centroid"][1] - centre[1])
            item["envelope"] = segment_rho(min(item["w"], 1.0)) * radius
        rows.append(item)
    return rows


def _caught(frame: dict[str, Any], shift: tuple[int, int], margin: float) -> bool:
    if "d" not in frame:
        return False
    moved = math.hypot(frame["d"][0] + shift[0], frame["d"][1] + shift[1])
    return bool(moved > float(frame["envelope"]) + margin)


def envelope_rule(
    prepared: list[tuple[dict[str, Any], list[dict[str, Any]]]], margin: float, floor: float
) -> dict[str, Any]:
    """The envelope check in every frame with green, with the final frame required to show w >=
    ``floor``: normal candidates rejected, and the share of (step, direction) shifts that pass."""
    normal_rejected = []
    passing = 0
    total = 0
    worst: tuple[float, int, int] | None = None
    for episode, frames in prepared:
        outside = [f for f in frames if "d" in f and math.hypot(*f["d"]) > f["envelope"] + margin]
        final_ok = frames[-1]["w"] >= floor and "d" in frames[-1]
        if outside or not final_ok:
            normal_rejected.append(episode["seed"])
        steps = episode["T"]
        for vector in episode["shift_exact"]:
            shift = whole_pixels(vector)
            caught = [_caught(f, shift, margin) for f in frames]
            last = max((i for i, flag in enumerate(caught) if flag), default=-1)
            for step in range(1, steps):
                total += 1
                if step > last and final_ok:
                    passing += 1
                    if worst is None:
                        worst = (frames[-1]["w"], episode["seed"], step)
    return {
        "margin_px": margin,
        "final_floor": floor,
        "normal_candidates_rejected": normal_rejected,
        "shift_step_direction_triples": total,
        "triples_that_pass": passing,
        "first_passing": None
        if worst is None
        else {"final_w": worst[0], "seed": worst[1], "step": worst[2]},
    }


def theta_rule(
    episodes: list[dict[str, Any]],
    prepared: list[tuple[dict[str, Any], list[dict[str, Any]]]],
    normaliser: str,
) -> dict[str, Any]:
    """The 90% candidate with a pilot-style tolerance, against snapshot or projected-area counts."""
    eligible = []
    finals_ineligible = []
    tails = []
    for episode, frames in prepared:
        full = episode["reference_green"] if normaliser == "snapshot" else None
        ok = []
        for frame in frames:
            w = frame["green"] / full if full else frame["w"]
            ok.append("d" in frame and w >= CANDIDATE_THETA)
        if not ok[-1]:
            finals_ineligible.append(episode["seed"])
        last = max((i for i, flag in enumerate(ok) if flag), default=-1)
        steps = episode["T"]
        tails.append(sum(1 for s in range(1, steps) if s > last) / max(steps - 1, 1))
        if normaliser == "snapshot":
            centre = episode["reference_centroid"]
            drifts = [
                (
                    row["centroid"][0] - centre[0],
                    row["centroid"][1] - centre[1],
                )
                for row, flag in zip(episode["frames"], ok, strict=True)
                if flag
            ]
        else:
            drifts = [frame["d"] for frame, flag in zip(frames, ok, strict=True) if flag]
        shifts = [whole_pixels(vector) for vector in episode["shift_exact"]]
        for drift in drifts:
            injected = min(math.hypot(drift[0] + a, drift[1] + b) for a, b in shifts)
            eligible.append((math.hypot(*drift), injected, episode["seed"]))
    largest = max(eligible)
    tolerance = (1 + WIDENING) * largest[0]
    shift_min = min(e["shift_min_exact_px"] for e in episodes)
    return {
        "normaliser": normaliser,
        "theta": CANDIDATE_THETA,
        "eligible_frames": len(eligible),
        "max_normal_drift": {"value": largest[0], "seed": largest[2]},
        "tolerance_widened": tolerance,
        "smallest_shift_exact_px": shift_min,
        "stop_9_margin_px": shift_min - tolerance,
        "min_drift_left_by_a_shift": min(item[1] for item in eligible),
        "eligible_frames_a_shift_could_pass": sum(1 for item in eligible if item[1] <= tolerance),
        "episodes_final_frame_ineligible": finals_ineligible,
        "mean_share_of_injection_steps_with_no_eligible_frame_after": statistics.fmean(tails),
    }


def analyse(episodes: list[dict[str, Any]], manifests: dict[int, dict[str, Any]]) -> dict[str, Any]:
    prepared = [(episode, _frames(episode, manifests[episode["seed"]])) for episode in episodes]
    fills = []
    for episode, frames in prepared:
        occluded = max(f["green"] for f in frames) / episode["reference_green"] > OCCLUDED_SNAPSHOT
        fills.append((frames[0]["w"], occluded, episode["seed"]))
    clean = sorted(value for value, occluded, _ in fills if not occluded)
    slack = sorted(
        (math.hypot(*f["d"]) - f["envelope"], f["w"], episode["seed"], index)
        for episode, frames in prepared
        for index, f in enumerate(frames)
        if "d" in f
    )
    bins: dict[str, dict[str, int]] = {}
    edges = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
    for episode, frames in prepared:
        shifts = [whole_pixels(vector) for vector in episode["shift_exact"]]
        for f in frames:
            if "d" not in f:
                continue
            label = next(
                (f"[{lo}, {hi})" for lo, hi in itertools.pairwise(edges) if lo <= f["w"] < hi),
                ">= 1.0",
            )
            cell = bins.setdefault(label, {"frames": 0, **{f"pass_m{m}": 0 for m in MARGINS_PX}})
            cell["frames"] += 1
            for margin in MARGINS_PX:
                if not all(_caught(f, shift, margin) for shift in shifts):
                    cell[f"pass_m{margin}"] += 1
    finals = sorted((frames[-1]["w"], episode["seed"]) for episode, frames in prepared)
    final_gap = []
    for episode, frames in prepared:
        f = frames[-1]
        gaps = [
            math.hypot(f["d"][0] + a, f["d"][1] + b) - f["envelope"]
            for a, b in (whole_pixels(v) for v in episode["shift_exact"])
        ]
        final_gap.append((min(gaps), episode["seed"], f["w"]))
    focus_episode, focus_frames = next(
        (e, frames) for e, frames in prepared if e["seed"] == FOCUS[0]
    )
    focus_frame = focus_frames[FOCUS[1]]
    return {
        "fill_fraction_unoccluded_snapshots": {
            "scenes": len(clean),
            "min": clean[0],
            "median": statistics.median(clean),
            "max": clean[-1],
        },
        "occluded_snapshots": [
            {"seed": seed, "snapshot_w": value} for value, occluded, seed in fills if occluded
        ],
        "focus": {
            "seed": FOCUS[0],
            "frame": FOCUS[1],
            "w": focus_frame["w"],
            "offset_from_projected_px": math.hypot(*focus_frame["d"]),
            "envelope_px": focus_frame["envelope"],
            "snapshot_w": focus_frames[0]["w"],
            "projected_radius_px": projected_radius_px(manifests[focus_episode["seed"]]),
        },
        "envelope_premise": {
            "frames_with_green": len(slack),
            "max_slack_px": {
                "value": slack[-1][0],
                "w": slack[-1][1],
                "seed": slack[-1][2],
                "frame": slack[-1][3],
            },
        },
        "frames_where_some_shift_stays_inside_by_w": bins,
        "final_frames": {
            "lowest_w": finals[:8],
            "below_floor": {str(floor): [s for w, s in finals if w < floor] for floor in FLOORS},
            "smallest_gap_of_a_shift_beyond_envelope_px": sorted(final_gap)[:6],
        },
        "theta_90_snapshot": theta_rule(episodes, prepared, "snapshot"),
        "theta_90_projected_area": theta_rule(episodes, prepared, "area"),
        "envelope_rules": [
            envelope_rule(prepared, margin, floor) for margin in MARGINS_PX for floor in FLOORS
        ],
    }


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    try:
        require_code_root()
        found = sorted(Path("runs").glob(f"*/{RESULT}*"))
        if found:
            raise ValueError(f"already run in {found[0]}")
        raw = DIAGNOSTIC.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        with ledgered_run(
            purpose="WO-021: goal-envelope analysis for drafting m3-protocol-4 (no simulation)",
            config={
                "diagnostic": str(DIAGNOSTIC),
                "diagnostic_sha256": digest,
                "pilot_runs": list(PILOT_RUNS),
                "goal_radius_m": GOAL_RADIUS_M,
                "proposed": {"margin_px": PROPOSED_MARGIN_PX, "final_floor": PROPOSED_FLOOR},
            },
            seeds={},
            env_lock={"simulation": "none"},
        ) as record:
            if record.dirty:
                raise ValueError("commit first, so the code note stays true")
            episodes = json.loads(raw)["episodes"]
            report = {
                "run": record.directory.name,
                "code": record.code_note,
                "inputs": {"diagnostic": str(DIAGNOSTIC), "sha256": digest},
                "label": (
                    "computed from measured simulation records of spent pilot seeds; in-sample, "
                    "not an exit-test result"
                ),
                **analyse(episodes, _load_manifests()),
            }
            text = json.dumps(report, indent=1, sort_keys=True, allow_nan=False) + "\n"
            (record.directory / RESULT).write_text(text, encoding="utf-8")
            record.note = "goal-envelope analysis written"
            print(record.directory)
    except (ValueError, OSError, KeyError) as exc:
        print(f"refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
