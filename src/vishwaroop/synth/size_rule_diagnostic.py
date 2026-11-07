"""A ledgered diagnostic of m3-protocol-2's size-check rule, on protocol-1's spent pilot seeds.

    python -m vishwaroop.synth.size_rule_diagnostic

Run it from the repository root, in the robotics environment, at a clean commit, before
``evals/M3-protocol-2.json`` is frozen. It re-renders block 10 seeds 10900 to 10919 (their frozen
use, setting protocol-1's tolerances, ended when that pilot stopped) with the same nominal and
operator alternation, and records for every frame: the cube's area ratio to the snapshot render,
the sightline clearance of the commanded and of the simulator's actual joint positions, and the
simulator's cube displacement from its start. It also gives, for several clearances, how many
leading frames each candidate would have size-checkable and what the area ratio and displacement
are in them. It writes ``size_rule_diagnostic.json`` into a new run directory and nothing into
``evals/``. It touches no seed that m3-protocol-2 uses.

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
from .checker import camera_position, cube_area, measure, sightline_clearance
from .et_m3_1 import _task
from .operators import et_m3_1_episodes
from .snapshot import render_episode, take_snapshot

SPENT_SEEDS = tuple(range(10900, 10920))
# m3-protocol-1's pilot merge distance (28.52 px, run 20261107T083058Z_83f404c3) widened by 10%
MERGE_RADIUS_PX = 31.37
CLEARANCES_M = (0.02, 0.025, 0.03, 0.035, 0.04, 0.05)
RESULT = "size_rule_diagnostic.json"


def _prefix(values: list[float], clearance: float) -> int:
    for count, value in enumerate(values):
        if value <= clearance:
            return count
    return len(values)


def summarize(episodes: list[dict[str, Any]], clearance: float) -> dict[str, Any]:
    """For one clearance: each candidate's n (commanded joints, prefix), and over those frames the
    area ratio's range and the largest cube displacement."""
    counts = []
    ratios: list[float] = []
    moved = 0.0
    frames = 0
    for episode in episodes:
        n = _prefix(episode["commanded_clearance_m"], clearance)
        counts.append(n)
        frames += len(episode["area_ratio"])
        ratios += episode["area_ratio"][:n]
        moved = max([moved, *episode["cube_displacement_m"][:n]])
    return {
        "clearance_m": clearance,
        "n_by_seed": {str(e["seed"]): c for e, c in zip(episodes, counts, strict=True)},
        "candidates_with_n_0": sum(1 for c in counts if c == 0),
        "candidates_with_n_below_2": sum(1 for c in counts if c < 2),
        "n_min": min(counts),
        "n_median": statistics.median(counts),
        "share_of_frames": sum(counts) / frames,
        "area_ratio_min": min(ratios) if ratios else None,
        "area_ratio_max": max(ratios) if ratios else None,
        "max_cube_displacement_m": moved,
    }


def run(env: Any, task: tuple[str, str, int]) -> list[dict[str, Any]]:
    episodes = []
    for episode in et_m3_1_episodes(SPENT_SEEDS):
        print(f"diagnostic seed {episode.seed} {episode.kind}", file=sys.stderr, flush=True)
        snapshot = take_snapshot(env, episode.seed, task[0], task[1])
        rendered = render_episode(env, snapshot, episode, task[2])
        camera = camera_position(snapshot.manifest)
        start = rendered.initial_cube
        reference_area = cube_area(measure(snapshot.render), MERGE_RADIUS_PX)[0]
        commanded = [rendered.initial_joints, *rendered.actions]
        episodes.append(
            {
                "seed": episode.seed,
                "kind": episode.kind,
                "T": rendered.steps,
                "planning_error": rendered.planning_error,
                "area_ratio": [
                    cube_area(measure(frame), MERGE_RADIUS_PX)[0] / reference_area
                    for frame in rendered.frames
                ],
                "commanded_clearance_m": [
                    sightline_clearance(joints, camera, start) for joints in commanded
                ],
                "actual_clearance_m": [
                    sightline_clearance(joints, camera, start)
                    for joints in rendered.joint_positions
                ],
                "cube_displacement_m": [math.dist(cube, start) for cube in rendered.cube_positions],
            }
        )
    return episodes


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
            purpose="WO-021: size-check rule diagnostic, spent protocol-1 pilot seeds 10900-10919",
            config={"clearances_m": list(CLEARANCES_M), "merge_radius_px": MERGE_RADIUS_PX},
            seeds={str(seed): seed for seed in SPENT_SEEDS},
            env_lock={"stack": env.stack_identity()},
        ) as record:
            if record.dirty:
                raise ValueError("commit first, so the code note stays true")
            episodes = run(env, task)
            report = {
                "run": record.directory.name,
                "code": record.code_note,
                "label": "measured, simulation; diagnostic on spent seeds, not an exit-test result",
                "summaries": [summarize(episodes, value) for value in CLEARANCES_M],
                "episodes": episodes,
            }
            text = json.dumps(report, indent=1, sort_keys=True, allow_nan=False) + "\n"
            (record.directory / RESULT).write_text(text, encoding="utf-8")
            record.note = "size-rule diagnostic written"
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
