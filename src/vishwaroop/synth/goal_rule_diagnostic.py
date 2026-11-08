"""A second ledgered goal-check diagnostic for drafting m3-protocol-4, on spent pilot seeds only.

    python -m vishwaroop.synth.goal_rule_diagnostic

The first pass (``goal_diagnostic``, run ``20261108T044149Z_1a94815d``) found two sources of
goal-centroid drift: a goal partly hidden in the frame, and a goal partly hidden in the snapshot
render itself, which biases the reference centroid and count. This pass re-renders the same 60
unmodified episodes (the spent ET-M3-1 pilot sequences of m3-protocol-1, -2 and -3, each exactly as
its run built it) and compares eligibility rules for the goal check:

- ``snapshot_v``: frames whose green count is at least theta x the snapshot render's, drift
  measured from the snapshot render's green centroid (the owner's candidate, theta = 0.9);
- ``projected_v``: the same frames, drift measured from the goal's projected centre (the frozen
  manifest's goal position through the render camera's projection);
- ``geometric_c``: frames where the arm's skeleton (``so100_kinematics.arm_segments``) at the
  commanded joints of this and the previous control step is more than c from the sightline from
  the camera's centre to the goal's centre; drift from the projected centre. Only joint values and
  the manifest enter, so an image edit cannot change which frames are checked. In those frames
  the goal's visibility v is recorded, to see whether "the goal must be seen" can be required.

For each rule it reports the largest normal drift over eligible frames widened by 10% (the pilot
rule), the smallest unrounded image displacement of a 0.03 m goal move on any scene over directions
every 1 degree (protocol-3's stop 9), the smallest drift a whole-pixel 0.03 m shift would leave in
an eligible frame (computed: the frame's drift vector plus the shift), how many eligible frames a
shift could pass in, how often the final frame is eligible, and the share of type-4 injection steps
(``randrange(1, T)``) after which no frame is eligible. It writes ``goal_rule_diagnostic.json``
into a new run directory and nothing into ``evals/``, and it touches no unused seed.

Exit codes: 0 done, 2 refused, 3 simulator not run.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

from ..sim.env import ManiSkillPickCube, SimulatorUnavailableError
from ..sim.runlog import ledgered_run, require_code_root
from .checker import WIDENING, camera_position, measure, sightline_clearance
from .et_m3_1 import _task
from .goal_diagnostic import SEQUENCES, injected_drift, shift_vectors, whole_pixels
from .operators import et_m3_1_episodes
from .snapshot import projection_matrix, render_episode, take_snapshot

VISIBILITY_THRESHOLDS = (0.5, 0.7, 0.8, 0.9, 0.95)
CLEARANCES_M = (0.02, 0.03, 0.04, 0.05, 0.07, 0.1)
GOAL_RADIUS_M = 0.0125 * 1.25  # mani_skill 3.0.1 PickCube so100 goal_thresh, the goal sphere
PRESENCE_FLOORS = (0.5, 0.8, 0.9)
RESULT = "goal_rule_diagnostic.json"


def run_episodes(env: Any, task: tuple[str, str, int]) -> list[dict[str, Any]]:
    from .inject import project

    episodes = []
    for group, seeds in SEQUENCES.items():
        for episode in et_m3_1_episodes(seeds):
            print(f"{group} seed {episode.seed} {episode.kind}", file=sys.stderr, flush=True)
            snapshot = take_snapshot(env, episode.seed, task[0], task[1])
            rendered = render_episode(env, snapshot, episode, task[2])
            ref = measure(snapshot.render)
            if ref.green_centroid is None:
                raise ValueError(f"seed {episode.seed}: the snapshot render shows no goal")
            projection = projection_matrix(snapshot.manifest)
            goal = [float(value) for value in snapshot.manifest["goal_position"]]
            camera = camera_position(snapshot.manifest)
            centre = project(projection, (goal[0], goal[1], goal[2]))
            exact = shift_vectors(projection, goal)
            commanded = [rendered.initial_joints, *rendered.actions]
            command_clearance = [sightline_clearance(q, camera, goal) for q in commanded]
            actual_clearance = [
                sightline_clearance(q, camera, goal) for q in rendered.joint_positions
            ]
            frames = []
            for index, frame in enumerate(rendered.frames):
                stats = measure(frame)
                frames.append(
                    {
                        "green": stats.green_count,
                        "centroid": None
                        if stats.green_centroid is None
                        else list(stats.green_centroid),
                        "clearance_cmd_m": min(command_clearance[max(index - 1, 0) : index + 1]),
                        "clearance_actual_m": actual_clearance[index],
                    }
                )
            episodes.append(
                {
                    "group": group,
                    "seed": episode.seed,
                    "kind": episode.kind,
                    "T": rendered.steps,
                    "reference_green": ref.green_count,
                    "reference_centroid": list(ref.green_centroid),
                    "projected_centre": list(centre),
                    "snapshot_offset_from_projected_px": math.dist(ref.green_centroid, centre),
                    "shift_exact": [list(v) for v in exact],
                    "shift_min_exact_px": min(math.hypot(*v) for v in exact),
                    "frames": frames,
                }
            )
    return episodes


def _rule_frames(episode: dict[str, Any], rule: str, value: float) -> list[bool]:
    out = []
    for row in episode["frames"]:
        v = row["green"] / episode["reference_green"]
        if rule in ("snapshot_v", "projected_v"):
            out.append(row["centroid"] is not None and v >= value)
        else:
            out.append(row["clearance_cmd_m"] > value)
    return out


def _drift(episode: dict[str, Any], row: dict[str, Any], rule: str) -> float | None:
    if row["centroid"] is None:
        return None
    ref = episode["reference_centroid"] if rule == "snapshot_v" else episode["projected_centre"]
    return math.dist(row["centroid"], ref)


def evaluate_rule(episodes: list[dict[str, Any]], rule: str, value: float) -> dict[str, Any]:
    worst: tuple[float, int, int, float] | None = None
    eligible_total = 0
    visible: list[tuple[float, int, int]] = []
    injected: list[tuple[float, int, int]] = []
    finals_ineligible = []
    no_eligible = []
    tail_share = []
    for episode in episodes:
        ok = _rule_frames(episode, rule, value)
        eligible_total += sum(ok)
        if not ok[-1]:
            finals_ineligible.append(episode["seed"])
        if not any(ok):
            no_eligible.append(episode["seed"])
        last = max((i for i, flag in enumerate(ok) if flag), default=-1)
        steps = episode["T"]
        if steps >= 2:
            # type 4 steps are randrange(1, T); none eligible from s on iff s > last
            tail_share.append(sum(1 for s in range(1, steps) if s > last) / (steps - 1))
        ref = episode["reference_centroid"] if rule == "snapshot_v" else episode["projected_centre"]
        shifts = [whole_pixels((v[0], v[1])) for v in episode["shift_exact"]]
        for index, (flag, row) in enumerate(zip(ok, episode["frames"], strict=True)):
            if not flag:
                continue
            v = row["green"] / episode["reference_green"]
            drift = _drift(episode, row, rule)
            visible.append((v, episode["seed"], index))
            if drift is None:
                continue
            if worst is None or drift > worst[0]:
                worst = (drift, episode["seed"], index, v)
            vector = (row["centroid"][0] - ref[0], row["centroid"][1] - ref[1])
            injected.append((injected_drift(vector, shifts)[0], episode["seed"], index))
    tolerance = (1 + WIDENING) * worst[0] if worst else 0.0
    shift_min = min((e["shift_min_exact_px"], e["seed"]) for e in episodes)
    lowest = min(injected, default=None)
    out: dict[str, Any] = {
        "rule": rule,
        "value": value,
        "eligible_share": eligible_total / sum(len(e["frames"]) for e in episodes),
        "episodes_without_eligible_frame": no_eligible,
        "episodes_final_frame_ineligible": finals_ineligible,
        "max_eligible_drift": None
        if worst is None
        else {"value": worst[0], "seed": worst[1], "frame": worst[2], "visibility": worst[3]},
        "tolerance_widened": tolerance,
        "smallest_shift_exact_px": {"value": shift_min[0], "seed": shift_min[1]},
        "stop_9_margin_px": shift_min[0] - tolerance,
        "min_injected_drift": None
        if lowest is None
        else {"value": lowest[0], "seed": lowest[1], "frame": lowest[2]},
        "eligible_frames_a_shift_could_pass": sum(1 for x in injected if x[0] <= tolerance),
        "injection_steps_with_no_eligible_frame_after_share_mean": statistics.fmean(tail_share)
        if tail_share
        else None,
        "episodes_with_some_step_followed_by_no_eligible_frame": sum(
            1 for share in tail_share if share > 0
        ),
    }
    if rule == "geometric_c":
        visibilities = sorted(visible)
        out["min_visibility_in_eligible_frames"] = (
            None
            if not visibilities
            else {
                "value": visibilities[0][0],
                "seed": visibilities[0][1],
                "frame": visibilities[0][2],
            }
        )
        for floor in PRESENCE_FLOORS:
            out[f"eligible_frames_below_visibility_{floor}"] = sum(
                1 for item in visibilities if item[0] < floor
            )
    return out


def summarize(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    offsets = sorted(
        (e["snapshot_offset_from_projected_px"], e["seed"], e["reference_green"]) for e in episodes
    )
    clear = [
        math.dist(row["centroid"], e["projected_centre"])
        for e in episodes
        for row in e["frames"]
        if row["centroid"] is not None and row["clearance_actual_m"] > 0.1
    ]
    rules = [("snapshot_v", v) for v in VISIBILITY_THRESHOLDS]
    rules += [("projected_v", v) for v in VISIBILITY_THRESHOLDS]
    rules += [("geometric_c", c) for c in CLEARANCES_M]
    return {
        "episodes": len(episodes),
        "snapshot_centroid_offset_from_projected_px": {
            "max": offsets[-1],
            "median": statistics.median(x[0] for x in offsets),
            "largest_five": offsets[-5:],
        },
        "drift_from_projected_when_actual_clearance_over_0.1_m": {
            "frames": len(clear),
            "max": max(clear) if clear else None,
            "median": statistics.median(clear) if clear else None,
        },
        "rules": [evaluate_rule(episodes, rule, value) for rule, value in rules],
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
                "WO-021: goal-rule diagnostic (second pass) for drafting m3-protocol-4, spent "
                "pilot seeds only"
            ),
            config={
                "visibility_thresholds": list(VISIBILITY_THRESHOLDS),
                "clearances_m": list(CLEARANCES_M),
                "goal_radius_m": GOAL_RADIUS_M,
            },
            seeds={f"{group} first": seeds[0] for group, seeds in SEQUENCES.items()},
            env_lock={"stack": env.stack_identity()},
        ) as record:
            if record.dirty:
                raise ValueError("commit first, so the code note stays true")
            episodes = run_episodes(env, task)
            report = {
                "run": record.directory.name,
                "code": record.code_note,
                "label": (
                    "measured, simulation; diagnostic on spent pilot seeds, not an exit-test result"
                ),
                "summary": summarize(episodes),
                "summary_by_group": {
                    group: summarize([e for e in episodes if e["group"] == group])
                    for group in SEQUENCES
                },
                "episodes": episodes,
            }
            text = json.dumps(report, indent=1, sort_keys=True, allow_nan=False) + "\n"
            (record.directory / RESULT).write_text(text, encoding="utf-8")
            record.note = "goal-rule diagnostic written"
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
