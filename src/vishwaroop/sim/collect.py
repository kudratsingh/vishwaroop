"""Collect one partition of the planned M0 dataset, as one ledgered run (WO-002).

    python -m vishwaroop.sim.collect --config evals/M0-dataset-plan.json --partition train \\
        --tolerance-file evals/M0-exit-tests.json --out data/derived/m0-dataset/<commit>

Run it from the repository root. A run's episodes stay in one partition, so run it once for each,
and commit ``ledgers/runs.jsonl`` between them so that the second run records a clean tree. Failure
labels come only from the independent rubric. It checks free disk before starting and between
episodes, and stops at the plan's time limit; what it wrote stays.

Exit codes: 0 collected, 1 a sampled replay did not hold, 2 refused, 3 simulator not run,
130 interrupted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .env import ManiSkillPickCube, SimEnv, SimulatorUnavailableError
from .record import FAMILY_PARTITION, STACK_LOCK, partition_for_seed, record_scripted
from .replay import ReplayInvalidError, load_frozen, replay_episode, require_frozen_file
from .runlog import ledgered_run, require_code_root

_GB = 1024**3


def load_plan(path: Path) -> dict[str, Any]:
    """Read a dataset plan, and refuse one that breaks the split rules."""
    plan: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    seen: set[tuple[str, int]] = set()
    for family in plan["families"]:
        variant, partition = family["variant"], family["partition"]
        if FAMILY_PARTITION.get(variant) != partition:
            raise ValueError(f"family {variant} does not belong to {partition}")
        if family["count"] <= 0:
            raise ValueError(f"family {variant} has no episodes")
        for seed in range(family["first_seed"], family["first_seed"] + family["count"]):
            if partition_for_seed(seed) != partition:
                raise ValueError(f"seed {seed} of family {variant} is not in {partition}")
            if (variant, seed) in seen:
                raise ValueError(f"family {variant} repeats seed {seed}")
            seen.add((variant, seed))
    return plan


def _check_disk(path: Path, min_free_gb: float) -> None:
    free = shutil.disk_usage(path).free
    if free < min_free_gb * _GB:
        raise OSError(f"only {free / _GB:.1f} GB free, and the plan requires {min_free_gb} GB")


def collect(
    env: SimEnv,
    plan: dict[str, Any],
    partition: str,
    tolerance_file: Path,
    out_dir: Path,
    run_id: str,
    code_note: str,
    replay: Callable[..., Any] = replay_episode,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Record every episode the plan gives this partition, and replay a sample of each family."""
    tolerance, rubric = load_frozen(tolerance_file)
    families = [family for family in plan["families"] if family["partition"] == partition]
    if not families:
        raise ValueError(f"the plan has no families in {partition}")
    deadline = clock() + plan["max_seconds_per_run"]
    labels: dict[str, Counter[str]] = {}
    sampled: list[dict[str, Any]] = []
    for family in families:
        variant = family["variant"]
        labels[variant] = Counter()
        for index in range(family["count"]):
            if clock() > deadline:
                raise TimeoutError(
                    f"the plan's limit of {plan['max_seconds_per_run']} s was reached"
                )
            _check_disk(out_dir, plan["min_free_disk_gb"])
            seed = family["first_seed"] + index
            episode = record_scripted(
                env, seed, variant, run_id, tolerance_file, out_dir, code_note
            )
            manifest = json.loads((episode / "episode.json").read_text(encoding="utf-8"))
            labels[variant][manifest["outcome"]["reason"].split(":")[0]] += 1
            if index < plan["replay_sample_per_family"]:
                report = replay(episode, env, tolerance, rubric)
                sampled.append(
                    {
                        "episode_id": manifest["episode_id"],
                        "valid": report.claim_valid,
                        "max_deviation": max(repeat.max_deviation for repeat in report.repeats),
                        "reason": report.reason,
                    }
                )
    return {
        "partition": partition,
        "episodes": sum(sum(counts.values()) for counts in labels.values()),
        "labels": {variant: dict(counts) for variant, counts in labels.items()},
        "replay_sample": sampled,
        "replay_sample_invalid": sum(not item["valid"] for item in sampled),
    }


def _run(args: argparse.Namespace) -> dict[str, Any]:
    require_frozen_file(args.tolerance_file)
    plan = load_plan(args.config)
    require_code_root()
    args.out.mkdir(parents=True, exist_ok=True)
    _check_disk(args.out, plan["min_free_disk_gb"])
    env = ManiSkillPickCube()
    seeds = {
        f"{family['variant']}:{family['first_seed']}": family["first_seed"]
        for family in plan["families"]
        if family["partition"] == args.partition
    }
    with ledgered_run(
        purpose=f"m0 dataset, {args.partition}",
        config={
            "plan_sha256": hashlib.sha256(args.config.read_bytes()).hexdigest(),
            "partition": args.partition,
        },
        seeds=seeds,
        env_lock={
            "stack": env.stack_identity(),
            "stack_lock_sha256": hashlib.sha256(STACK_LOCK.read_bytes()).hexdigest(),
        },
    ) as run:
        report = collect(
            env,
            plan,
            args.partition,
            args.tolerance_file,
            args.out,
            run.directory.name,
            run.code_note,
        )
        report["run"] = run.directory.name
        with (run.directory / "collection.json").open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
        run.note = (
            f"{report['episodes']} episodes; "
            f"{report['replay_sample_invalid']} sampled replays invalid"
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--partition", required=True, choices=["train", "dev"])
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
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["replay_sample_invalid"] else 0


if __name__ == "__main__":
    sys.exit(main())
