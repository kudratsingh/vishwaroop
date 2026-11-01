"""Look at an exported episode, by a route that does not use the outcome code (ET-M0-4).

The episode must first pass contract validation, which checks its hashes and paths. ``raw_facts``
then reads the transitions directly. ``--render`` replays the recorded actions from the saved
initial state with the camera on and writes a contact sheet for a person or agent to look at. If the
rendered run strays from the recording by more than the frozen replay tolerance, the pictures do not
show this episode, and the command says so and exits 1.

    python -m vishwaroop.sim.inspect_episode --episode DIR --out NEW_DIR --render

Exit codes: 0 inspected, 1 the pictures cannot be trusted, 2 refused, 3 simulator not run.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .contract import validator
from .env import ManiSkillPickCube, SimulatorUnavailableError

_FRAMES = 12
_COMPARED = ("joint_position", "object_position", "target_position")
_DWELL_STEPS = 10
_RENDER_MAX_DEVIATION = 0.001  # evals/M0-exit-tests.json, replay.max_state_deviation


def _value(packets: Sequence[Mapping[str, Any]], stream: str) -> list[float]:
    for packet in packets:
        if packet["stream"] == stream:
            value: list[float] | None = packet["value"]
            if value is None:
                raise ValueError(f"stream {stream} is marked invalid in the record")
            return value
    raise ValueError(f"stream {stream} is not in the record")


def raw_facts(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """What happened, in numbers, computed here from the transitions and nothing else."""
    if not records:
        raise ValueError("the episode has no records")
    states = [records[0]["observations"], *(r["next_observations"] for r in records)]
    cube = [_value(state, "object_position") for state in states]
    grasped = [bool(_value(state, "object_grasped")[0]) for state in states]
    target = _value(states[-1], "target_position")
    tail = cube[-(_DWELL_STEPS + 1) :]
    return {
        "records": len(records),
        "cube_start_m": cube[0],
        "cube_end_m": cube[-1],
        "cube_peak_height_m": max(position[2] for position in cube),
        "target_xy_m": target[:2],
        "end_distance_to_target_xy_m": math.dist(cube[-1][:2], target[:2]),
        "samples_grasped": sum(grasped),
        "grasped_at_end": grasped[-1],
        "largest_step_motion_in_last_10_steps_m": max(
            math.dist(a, b) for a, b in itertools.pairwise(tail)
        ),
    }


def frame_steps(record_count: int, frames: int = _FRAMES) -> list[int]:
    """Evenly spaced steps to draw, always including the first state and the last."""
    if record_count <= 0 or frames < 2:
        raise ValueError("need at least one record and two frames")
    return sorted({round(i * record_count / (frames - 1)) for i in range(frames)})


def _render(episode: Path, manifest: dict[str, Any], records: list[Any], out: Path) -> float:
    from PIL import Image, ImageDraw

    configuration = json.loads((episode / "configuration.json").read_text(encoding="utf-8"))
    env = ManiSkillPickCube(
        env_id=configuration["env_id"],
        max_episode_steps=configuration["max_episode_steps"],
        render=True,
    )
    state = (episode / manifest["simulator"]["initial_state_artifact"]["path"]).read_bytes()
    env.restore_state(state)
    wanted = set(frame_steps(len(records)))
    images: list[tuple[int, Any]] = []
    if 0 in wanted:
        images.append((0, env.render_rgb()))
    worst = 0.0
    for index, record in enumerate(records):
        packet = env.step(record["action"]["requested"])
        for stream in _COMPARED:
            recorded = _value(record["next_observations"], stream)
            for now, then in zip(packet[stream], recorded, strict=True):
                gap = abs(now - then)
                worst = max(worst, gap) if math.isfinite(gap) else math.inf
        if index + 1 in wanted:
            images.append((index + 1, env.render_rgb()))
    columns = 4
    height, width = images[0][1].shape[:2]
    rows = math.ceil(len(images) / columns)
    sheet = Image.new("RGB", (columns * width, rows * height), "white")
    for position, (step, image) in enumerate(images):
        tile = Image.fromarray(image)
        ImageDraw.Draw(tile).text((8, 8), f"step {step}", fill="white")
        sheet.paste(tile, ((position % columns) * width, (position // columns) * height))
    sheet.save(out / "contact-sheet.png")
    return worst


def _run(args: argparse.Namespace) -> dict[str, Any]:
    validator().validate_episode(args.episode / "episode.json")
    manifest = json.loads((args.episode / "episode.json").read_text(encoding="utf-8"))
    path = args.episode / manifest["data"]["transitions_artifact"]["path"]
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    report: dict[str, Any] = {
        "episode_id": manifest["episode_id"],
        "recorded_outcome": manifest["outcome"]["reason"],
        "raw_facts": raw_facts(records),
    }
    args.out.mkdir(parents=True, exist_ok=False)
    if args.render:
        worst = _render(args.episode, manifest, records, args.out)
        report["rendered_run_max_deviation"] = worst if math.isfinite(worst) else "inf"
        report["rendered_run_trusted"] = worst <= _RENDER_MAX_DEVIATION
    with (args.out / "inspection.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="a new directory")
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = _run(args)
    except SimulatorUnavailableError as exc:
        print(f"not run: {exc}", file=sys.stderr)
        return 3
    except (ValueError, KeyError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report.get("rendered_run_trusted") is False else 0


if __name__ == "__main__":
    sys.exit(main())
