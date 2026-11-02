"""Simulator branches for ET-M1-2 and ET-M1-5: several action chunks from the same dev states.

    python -m vishwaroop.sim.branches

Run it from the repository root, in the robotics environment. The states, chunks and costs are
frozen in ``evals/M1-planner-scorer.json`` and its first amendment. Every chunk starts from the
episode's saved initial state, restored as M0's replay does, followed by the recorded actions up
to the state, through physics. Nothing else is restored or forced, and a reached state that
differs from the recorded one is refused. The run
takes about a minute, so a stopped run is simply repeated. Results go to ``branches.json`` in a
new run directory. Exit codes: 0 done, 2 refused, 3 simulator not run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..models.pilot_data import EpisodeArrays, read_episode, state_vector
from ..scoring.violations import margins, task_cost, violated
from .env import ManiSkillPickCube, Packet, SimulatorUnavailableError
from .replay import _load_episode
from .runlog import ledgered_run, require_code_root

PLAN_PATH = Path("evals/M1-planner-scorer.json")
PLAN_SHA256 = "88c952ed4ee1ca91db359e5ff964a913f460e6cfc67ef6fdeee79e7a420453bf"
AMENDMENT_PATH = Path("evals/M1-planner-scorer-amendment-1.json")
AMENDMENT_SHA256 = "2025f7c2c701b3f44841f39dea908816e424def0fee08fb6f2272ada8e9fd81c"
DEV_MANIFESTS = (
    Path("artifacts/manifests/m0-dataset-v1.json"),
    Path("artifacts/manifests/m1-dev-topup-v1.json"),
)
STATES_PER_FAMILY = 20
MIN_STEPS = 25
FIRST_STATE = 3
CHUNK = 10
OFFSETS_RAD = (0.05, 0.15)
ARM_JOINTS = 5
GRIPPER_OPEN_RAD = -0.3
GRIPPER_CLOSED_RAD = -0.8
REACHED_TOLERANCE = 1e-6


def select_states(
    entries: Sequence[dict[str, Any]], lengths: dict[str, int]
) -> list[tuple[str, int]]:
    """For each dev family, its 20 lowest-seed episodes with enough steps, and one step in each."""
    chosen: list[tuple[str, int]] = []
    for family in sorted({entry["family"] for entry in entries}):
        candidates = sorted(
            (entry for entry in entries if entry["family"] == family),
            key=lambda entry: entry["seed"],
        )
        usable = [entry for entry in candidates if lengths[entry["episode_id"]] >= MIN_STEPS]
        for entry in usable[:STATES_PER_FAMILY]:
            last = lengths[entry["episode_id"]] - CHUNK - 1
            step = random.Random(entry["seed"]).randint(FIRST_STATE, last)  # noqa: S311
            chosen.append((entry["episode_id"], step))
    return chosen


def make_chunks(
    recorded: Sequence[Sequence[float]],
    seed: int,
    step: int,
    lower: Sequence[float],
    upper: Sequence[float],
) -> list[list[list[float]]]:
    """The four frozen chunks, each clipped to the action limits."""
    if len(recorded) != CHUNK:
        raise ValueError(f"a chunk is {CHUNK} actions")
    chooser = random.Random(seed * 100 + step)  # noqa: S311
    shifted = []
    for spread in OFFSETS_RAD:
        offset = [chooser.gauss(0.0, spread) for _ in range(ARM_JOINTS)] + [0.0]
        shifted.append(
            [[a + b for a, b in zip(action, offset, strict=True)] for action in recorded]
        )
    middle = (GRIPPER_OPEN_RAD + GRIPPER_CLOSED_RAD) / 2
    inverted = [
        [
            *action[:ARM_JOINTS],
            GRIPPER_CLOSED_RAD if action[ARM_JOINTS] > middle else GRIPPER_OPEN_RAD,
        ]
        for action in recorded
    ]
    chunks = [[list(action) for action in recorded], *shifted, inverted]
    return [
        [
            [
                min(max(value, low), high)
                for value, low, high in zip(action, lower, upper, strict=True)
            ]
            for action in chunk
        ]
        for chunk in chunks
    ]


def _state(packet: Packet) -> list[float]:
    return state_vector([{"stream": name, "value": value} for name, value in packet.items()])


def run_chunk(
    env: Any,
    episode: EpisodeArrays,
    step: int,
    chunk: Sequence[Sequence[float]],
    initial_state: bytes,
) -> list[list[float]]:
    """Restore the initial state, run the recorded prefix, check it, then execute the chunk."""
    packet = env.restore_state(initial_state)
    for action in episode.actions[:step]:
        packet = env.step(list(action))
    reached: list[float] = _state(packet)
    gap = max(abs(a - b) for a, b in zip(reached, episode.states[step], strict=True))
    if gap > REACHED_TOLERANCE:
        raise ValueError(f"seed {episode.seed} step {step}: reached state differs by {gap}")
    states: list[list[float]] = [reached]
    for command in chunk:
        states.append(_state(env.step(list(command))))
    return states


def _branches(env: Any) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for path in DEV_MANIFESTS:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        entries.extend(entry for entry in manifest["episodes"] if entry["partition"] == "dev")
    episodes = {
        entry["episode_id"]: read_episode(
            Path(entry["path"]), entry["transitions_sha256"], entry["seed"]
        )
        for entry in entries
    }
    lengths = {name: len(item.actions) for name, item in episodes.items()}
    paths = {entry["episode_id"]: Path(entry["path"]) for entry in entries}
    family = {entry["episode_id"]: entry["family"] for entry in entries}
    lower, upper = env.action_spec.lower, env.action_spec.upper
    results = []
    for index, (name, step) in enumerate(select_states(entries, lengths)):
        episode = episodes[name]
        print(f"state {index} {name} step {step}", file=sys.stderr, flush=True)
        chunks = make_chunks(episode.actions[step : step + CHUNK], episode.seed, step, lower, upper)
        _, _, initial_state = _load_episode(paths[name])
        executed = []
        for number, chunk in enumerate(chunks):
            states = run_chunk(env, episode, step, chunk, initial_state)
            scaled = margins(states)
            executed.append(
                {
                    "chunk": number,
                    "actions": chunk,
                    "states": states,
                    "cost": task_cost(states[-1]),
                    "margins": scaled,
                    "violated": violated(scaled),
                }
            )
        results.append(
            {
                "episode_id": name,
                "family": family[name],
                "seed": episode.seed,
                "step": step,
                "history_states": episode.states[step - FIRST_STATE : step + 1],
                "history_actions": episode.actions[step - FIRST_STATE : step],
                "chunks": executed,
            }
        )
    return {
        "states": len(results),
        "chunks": sum(len(item["chunks"]) for item in results),
        "violating_chunks": sum(c["violated"] for item in results for c in item["chunks"]),
        "branches": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        require_code_root()
        for path, expected in ((PLAN_PATH, PLAN_SHA256), (AMENDMENT_PATH, AMENDMENT_SHA256)):
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(f"{path} has sha256 {actual}, not the frozen {expected}")
        env = ManiSkillPickCube()
        with ledgered_run(
            purpose="WO-005: simulator branches on dev states, for ET-M1-2 and ET-M1-5",
            config={"plan_sha256": PLAN_SHA256, "amendment_sha256": AMENDMENT_SHA256},
            seeds={"chunks": 100},
            env_lock={"stack": env.stack_identity()},
        ) as run:
            if run.dirty:
                raise ValueError("commit first, so the code note stays true")
            report = {"run": run.directory.name, "code": run.code_note, **_branches(env)}
            with (run.directory / "branches.json").open("x", encoding="utf-8") as stream:
                json.dump(report, stream, sort_keys=True, allow_nan=False)
                stream.write("\n")
            run.note = f"{report['states']} states, {report['violating_chunks']} violating chunks"
            print(run.directory)
    except SimulatorUnavailableError as exc:
        print(f"not run: {exc}", file=sys.stderr)
        return 3
    except (ValueError, OSError, KeyError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
