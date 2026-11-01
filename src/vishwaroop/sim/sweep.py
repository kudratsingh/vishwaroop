"""Every controller family over a range of seeds, each episode replayed by the frozen settings.

    python -m vishwaroop.sim.sweep --first-seed 100 --seeds 50 \\
        --tolerance-file evals/M0-exit-tests.json

Run it from the repository root. It is a ledgered run with its results in ``sweep.json``. Episodes
go to a temporary directory and are not kept: this measures, and WO-002 collects.

Exit codes: 0 measured, 1 a replay did not hold, 2 refused, 3 simulator not run, 130 interrupted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .env import ManiSkillPickCube, SimEnv, SimulatorUnavailableError
from .record import STACK_LOCK, partition_for_seed, record_scripted
from .replay import ReplayInvalidError, load_frozen, replay_episode, require_frozen_file
from .runlog import ledgered_run, require_code_root

# The families WO-001's report measures. WO-002 collects the others.
SWEEP_FAMILIES = ("nominal", "missed-grasp", "no-release", "wrong-place")


def measure(
    env: SimEnv,
    seeds: Sequence[int],
    tolerance_file: Path,
    run_id: str,
    code_note: str,
    replay: Callable[..., Any] = replay_episode,
) -> dict[str, Any]:
    """Record and replay each family on each seed, and count what the rubric and replay say."""
    tolerance, rubric = load_frozen(tolerance_file)
    labels: dict[str, Counter[str]] = defaultdict(Counter)
    unplanned: dict[str, list[int]] = defaultdict(list)
    deviations: list[float] = []
    invalid: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="m0-sweep-") as tmp:
        for variant in SWEEP_FAMILIES:
            for seed in seeds:
                episode = record_scripted(
                    env, seed, variant, run_id, tolerance_file, Path(tmp), code_note
                )
                manifest = json.loads((episode / "episode.json").read_text(encoding="utf-8"))
                labels[variant][manifest["outcome"]["reason"].split(":")[0]] += 1
                if "planning_failed" in manifest["notes"]:
                    unplanned[variant].append(seed)
                report = replay(episode, env, tolerance, rubric)
                deviations.append(max(repeat.max_deviation for repeat in report.repeats))
                if not report.claim_valid:
                    invalid.append({"variant": variant, "seed": seed, "reason": report.reason})
    return {
        "seeds": list(seeds),
        "episodes": len(deviations),
        "labels": {variant: dict(counts) for variant, counts in labels.items()},
        "seeds_unplanned": dict(unplanned),
        "max_deviation": max(deviations),
        "episodes_with_zero_deviation": sum(value == 0.0 for value in deviations),
        "replay_invalid": invalid,
    }


def _run(args: argparse.Namespace) -> dict[str, Any]:
    require_frozen_file(args.tolerance_file)
    seeds = range(args.first_seed, args.first_seed + args.seeds)
    if not seeds:
        raise ValueError("no seeds")
    for seed in (seeds[0], seeds[-1]):
        if partition_for_seed(seed) != "train":
            raise ValueError("use training seeds only: blocks 8 and 9 are the dev holdout")
    require_code_root()
    env = ManiSkillPickCube()
    with ledgered_run(
        purpose="m0 sweep of every controller family, with replay",
        config={"first_seed": args.first_seed, "seeds": args.seeds},
        seeds={str(seed): seed for seed in seeds},
        env_lock={
            "stack": env.stack_identity(),
            "stack_lock_sha256": hashlib.sha256(STACK_LOCK.read_bytes()).hexdigest(),
        },
    ) as run:
        report = measure(env, seeds, args.tolerance_file, run.directory.name, run.code_note)
        report["run"] = run.directory.name
        with (run.directory / "sweep.json").open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
        run.note = f"{report['episodes']} episodes"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-seed", type=int, required=True)
    parser.add_argument("--seeds", type=int, required=True)
    parser.add_argument("--tolerance-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = _run(args)
    except SimulatorUnavailableError as exc:
        print(f"not run: {exc}", file=sys.stderr)
        return 3
    except (ReplayInvalidError, ValueError, KeyError, TypeError, OSError) as exc:
        print(f"refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["replay_invalid"] else 0


if __name__ == "__main__":
    sys.exit(main())
