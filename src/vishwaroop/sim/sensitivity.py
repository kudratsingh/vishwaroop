"""How far a tiny change at the start of an episode moves it, on the same actions (ADR-0006).

This is the evidence behind recording from the restored state. Each case starts the nominal
controller's recorded actions a slightly different way, and is compared with the run from the saved
state, on the frozen replay streams. Results are for this stack and this machine.

    python -m vishwaroop.sim.sensitivity --first-seed 0 --seeds 100 --branch-seeds 20 \\
        --tolerance-file evals/M0-exit-tests.json --out runs/<new-file>.json

Exit codes: 0 measured, 2 refused, 3 simulator not run. The results are the finding: 0 does not mean
that the cases stayed within tolerance.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ..outcome.pickplace import PlaceRubric, StateSample, assess
from .baseline import VARIANTS, ScriptedPickPlace
from .env import ManiSkillPickCube, Packet, SimEnv, SimulatorUnavailableError
from .replay import ReplayInvalidError, load_frozen, require_frozen_file

_STREAMS = ("joint_position", "object_position", "target_position")
CUBE_NUDGE_M = 1e-7
BRANCH_STEPS = (30, 60, 90, 120, 150)


def _deviation(first: Packet, second: Packet) -> float:
    return max(
        abs(a - b)
        for stream in _STREAMS
        for a, b in zip(first[stream], second[stream], strict=True)
    )


def _sample(step: int, packet: Packet) -> StateSample:
    x, y, z = packet["object_position"]
    tx, ty, tz = packet["target_position"]
    return StateSample(step, (x, y, z), (tx, ty, tz), bool(packet["object_grasped"][0]))


def _run_actions(
    env: SimEnv, start: Packet, actions: Sequence[list[float]], rubric: PlaceRubric
) -> tuple[list[Packet], str]:
    packets = [start]
    for action in actions:
        packets.append(env.step(action))
    samples = [_sample(step, packet) for step, packet in enumerate(packets)]
    return packets, assess(samples, rubric).label


def nudge_cube(state: bytes, metres: float = CUBE_NUDGE_M) -> bytes:
    """The saved state with the cube's x moved, in the ManiSkill adapter's state format."""
    saved = json.loads(state.decode("utf-8"))
    saved["state"]["actors"]["cube"][0][0] += metres
    return json.dumps(saved, sort_keys=True).encode("utf-8")


def _start(
    name: str, env: SimEnv, seed: int, state: bytes, nudge: Callable[[bytes], bytes]
) -> Packet:
    """Begin one case, right before its actions."""
    if name == "plain_reset":
        return env.reset(seed)
    if name == "restored_again":
        env.restore_state(state)
        return env.restore_state(env.save_state())
    if name == "cube_nudged":
        return env.restore_state(nudge(state))
    raise ValueError(f"unknown case {name}")


class _Case:
    def __init__(self) -> None:
        self.episodes = 0
        self.over_tolerance = 0
        self.worst = 0.0
        self.label_flips = 0

    def add(self, deviation: float, tolerance: float, flipped: bool) -> None:
        self.episodes += 1
        self.over_tolerance += int(deviation > tolerance)
        self.worst = max(self.worst, deviation)
        self.label_flips += int(flipped)

    def result(self) -> dict[str, Any]:
        return {
            "episodes": self.episodes,
            "over_tolerance": self.over_tolerance,
            "max_deviation": self.worst,
            "label_flips": self.label_flips,
        }


def measure(
    env: SimEnv,
    seeds: Sequence[int],
    branch_seeds: Sequence[int],
    tolerance: float,
    rubric: PlaceRubric,
    nudge: Callable[[bytes], bytes] = nudge_cube,
) -> dict[str, Any]:
    """Run each case over ``seeds``, and mid-episode branches over ``branch_seeds``.

    An episode whose plan could not be made is skipped and counted, because it barely moves.
    """
    cases = {name: _Case() for name in ("plain_reset", "restored_again", "cube_nudged")}
    branches = {step: _Case() for step in BRANCH_STEPS}
    unplanned: list[int] = []
    resaved_differs = 0
    for seed in seeds:
        env.reset(seed)
        state = env.save_state()
        policy = ScriptedPickPlace(VARIANTS["nominal"])
        packet = env.restore_state(state)
        policy_view = {name: packet[name] for name in _STREAMS}
        actions: list[list[float]] = []
        while (action := policy(policy_view, len(actions))) is not None:
            actions.append(action)
        if policy.planning_error is not None:
            unplanned.append(seed)
            continue
        base, label = _run_actions(env, packet, actions, rubric)

        for name in cases:
            start = _start(name, env, seed, state, nudge)
            packets, new_label = _run_actions(env, start, actions, rubric)
            worst = max(_deviation(a, b) for a, b in zip(base, packets, strict=True))
            cases[name].add(worst, tolerance, new_label != label)
        env.restore_state(state)
        resaved_differs += int(env.save_state() != state)
        if seed in branch_seeds:
            for branch in BRANCH_STEPS:
                env.restore_state(state)
                for action in actions[:branch]:
                    env.step(action)
                middle = env.restore_state(env.save_state())
                packets, new_label = _run_actions(env, middle, actions[branch:], rubric)
                worst = max(_deviation(a, b) for a, b in zip(base[branch:], packets, strict=True))
                branches[branch].add(worst, tolerance, new_label != label)
    return {
        "seeds": list(seeds),
        "tolerance": tolerance,
        "family": "m0-scripted-nominal",
        "seeds_skipped_unplanned": unplanned,
        "saved_state_differs_after_restore": resaved_differs,
        "cube_nudge_m": CUBE_NUDGE_M,
        "cases": {name: case.result() for name, case in cases.items()},
        "branch_seeds": list(branch_seeds),
        "branches": {str(step): case.result() for step, case in branches.items()},
    }


def _run(args: argparse.Namespace) -> dict[str, Any]:
    if args.out.exists() or not args.out.parent.is_dir():
        raise ValueError(f"{args.out} exists or has no directory; reports are write-once")
    require_frozen_file(args.tolerance_file)
    tolerance, rubric = load_frozen(args.tolerance_file)
    seeds = range(args.first_seed, args.first_seed + args.seeds)
    if seeds.stop > 8000 or seeds.start < 0:
        raise ValueError("use training seeds only: blocks 8 and 9 are the dev holdout")
    report = measure(
        ManiSkillPickCube(),
        seeds,
        seeds[: args.branch_seeds],
        tolerance.max_state_deviation,
        rubric,
    )
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-seed", type=int, default=0)
    parser.add_argument("--seeds", type=int, default=100)
    parser.add_argument("--branch-seeds", type=int, default=20)
    parser.add_argument("--tolerance-file", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = _run(args)
    except SimulatorUnavailableError as exc:
        print(f"not run: {exc}", file=sys.stderr)
        return 3
    except (ReplayInvalidError, ValueError, KeyError, TypeError, OSError) as exc:
        print(f"refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
