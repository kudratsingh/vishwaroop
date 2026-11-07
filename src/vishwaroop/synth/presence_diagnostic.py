"""A ledgered diagnostic for drafting m3-protocol-3's presence rule, on spent seeds only.

    python -m vishwaroop.synth.presence_diagnostic

Run it from the repository root, in the robotics environment, at a clean commit. It re-renders
the unmodified episodes of four spent seed sequences, each exactly as its run built it:
m3-protocol-1's pilot (10900 to 10919), and m3-protocol-2's pilot (10300 to 10319), controls
(10400 to 10459) and injection sources (10200 to 10259). For every frame it records the cube's
area ratio to the snapshot render, under m3-protocol-2's pilot-set merge radius, and the sightline
clearance of the commanded joints. For every episode it records the size-checkable prefix n, the
final frame's ratio, and the longest runs of frames below several visibility floors. It writes
``presence_diagnostic.json`` into a new run directory and nothing into ``evals/``, and it touches
no unused seed.

Exit codes: 0 done, 2 refused, 3 simulator not run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ..sim.env import ManiSkillPickCube, SimulatorUnavailableError
from ..sim.runlog import ledgered_run, require_code_root
from .checker import (
    SIGHTLINE_CLEARANCE_M,
    camera_position,
    cube_area,
    measure,
    sightline_clearance,
    size_checkable_frames,
)
from .et_m3_1 import _task
from .operators import et_m3_1_episodes
from .snapshot import render_episode, take_snapshot

TOLERANCES = Path("evals/M3-checker-tolerances.json")
SEQUENCES = {
    "protocol-1 pilot": tuple(range(10900, 10920)),
    "protocol-2 pilot": tuple(range(10300, 10320)),
    "protocol-2 controls": tuple(range(10400, 10460)),
    "protocol-2 injection sources": tuple(range(10200, 10260)),
}
FLOORS = (0.0, 0.02, 0.05, 0.1)
RESULT = "presence_diagnostic.json"


def longest_run(values: list[float], floor: float) -> tuple[int, int | None]:
    """The longest run of consecutive frames whose ratio is at or below ``floor``, and where it
    starts (None if there is none)."""
    best, start, length, begin = 0, None, 0, 0
    for index, value in enumerate(values):
        if value <= floor:
            if length == 0:
                begin = index
            length += 1
            if length > best:
                best, start = length, begin
        else:
            length = 0
    return best, start


def run(env: Any, task: tuple[str, str, int], merge_radius: float) -> list[dict[str, Any]]:
    episodes = []
    for group, seeds in SEQUENCES.items():
        for episode in et_m3_1_episodes(seeds):
            print(f"{group} seed {episode.seed} {episode.kind}", file=sys.stderr, flush=True)
            snapshot = take_snapshot(env, episode.seed, task[0], task[1])
            rendered = render_episode(env, snapshot, episode, task[2])
            camera = camera_position(snapshot.manifest)
            start = rendered.initial_cube
            reference = cube_area(measure(snapshot.render), merge_radius)[0]
            ratios = [
                round(cube_area(measure(frame), merge_radius)[0] / reference, 5)
                for frame in rendered.frames
            ]
            commanded = [rendered.initial_joints, *rendered.actions]
            n = size_checkable_frames(rendered.initial_joints, start, camera, rendered.actions)
            runs = {}
            for floor in FLOORS:
                length, begin = longest_run(ratios, floor)
                runs[str(floor)] = {"frames": length, "starts": begin}
            episodes.append(
                {
                    "group": group,
                    "seed": episode.seed,
                    "kind": episode.kind,
                    "T": rendered.steps,
                    "size_checkable_frames": n,
                    "final_ratio": ratios[-1],
                    "min_ratio": min(ratios),
                    "min_ratio_after_prefix": min(ratios[n:], default=None),
                    "longest_run_at_or_below": runs,
                    "area_ratio": ratios,
                    "commanded_clearance_m": [
                        round(sightline_clearance(joints, camera, start), 5) for joints in commanded
                    ],
                }
            )
    return episodes


def summarize(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    finals = sorted(e["final_ratio"] for e in episodes)
    out: dict[str, Any] = {
        "episodes": len(episodes),
        "final_ratio_min": finals[0],
        "final_ratio_lowest_five": finals[:5],
        "min_ratio_anywhere": min(e["min_ratio"] for e in episodes),
        "below_size_band_in_prefix": sum(
            1
            for e in episodes
            if any(r < 0.9 for r in e["area_ratio"][: e["size_checkable_frames"]])
        ),
    }
    for floor in FLOORS:
        lengths = [e["longest_run_at_or_below"][str(floor)]["frames"] for e in episodes]
        out[f"runs_at_or_below_{floor}"] = {
            "episodes_with_any": sum(1 for x in lengths if x > 0),
            "longest": max(lengths),
            "episodes_ending_in_one": sum(1 for e in episodes if e["final_ratio"] <= floor),
        }
    return out


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    try:
        require_code_root()
        found = sorted(Path("runs").glob(f"*/{RESULT}*"))
        if found:
            raise ValueError(f"already run in {found[0]}")
        merge_radius = float(json.loads(TOLERANCES.read_text(encoding="utf-8"))["merge_radius_px"])
        task = _task()
        env = ManiSkillPickCube(env_id=task[0], max_episode_steps=task[2], render=True)
        with ledgered_run(
            purpose="WO-021: presence-rule diagnostic for drafting m3-protocol-3, spent seeds only",
            config={"merge_radius_px": merge_radius, "floors": list(FLOORS)},
            seeds={f"{group} first": seeds[0] for group, seeds in SEQUENCES.items()},
            env_lock={"stack": env.stack_identity()},
        ) as record:
            if record.dirty:
                raise ValueError("commit first, so the code note stays true")
            episodes = run(env, task, merge_radius)
            report = {
                "run": record.directory.name,
                "code": record.code_note,
                "label": "measured, simulation; diagnostic on spent seeds, not an exit-test result",
                "sightline_clearance_m": SIGHTLINE_CLEARANCE_M,
                "summary": summarize(episodes),
                "summary_by_group": {
                    group: summarize([e for e in episodes if e["group"] == group])
                    for group in SEQUENCES
                },
                "episodes": episodes,
            }
            text = json.dumps(report, indent=1, sort_keys=True, allow_nan=False) + "\n"
            (record.directory / RESULT).write_text(text, encoding="utf-8")
            record.note = "presence diagnostic written"
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
