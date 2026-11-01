"""Record scripted episodes on the frozen M0 task, in the real simulator, as one run.

    python -m vishwaroop.sim.record --episode 12:nominal --episode 12:wrong-place \\
        --tolerance-file evals/M0-exit-tests.json --out data/derived/m0

Run it from the repository root. The run gets a new directory under ``runs/`` and lines in
``ledgers/runs.jsonl``, with its code commit and dirty flag, and the run id is the episodes' session
group. Splits, group ids and the rubric come from ``evals/M0-protocol.md`` and the frozen exit
tests. Nothing is overwritten: the contract writer refuses an existing directory.

Exit codes: 0 recorded, 2 a precondition failed, 3 the simulator cannot run here, 130 interrupted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .baseline import VARIANTS, ScriptedPickPlace
from .env import ManiSkillPickCube, SimEnv, SimulatorUnavailableError
from .export import EpisodeSpec, record_episode
from .replay import ReplayInvalidError, load_frozen, require_frozen_file
from .runlog import ledgered_run, require_code_root

SEEDS_PER_BLOCK = 1000
TRAIN_BLOCKS = range(8)
DEV_BLOCKS = range(8, 10)
EMBODIMENT = "maniskill3_so100"
INSTRUCTION = "Pick up the cube and place it on the table at the goal's xy position."
STACK_LOCK = Path("config") / "stack-lock.resolved.v2.json"

# A policy family lies wholly in one partition (evals/M0-protocol.md section 3). Every family so
# far is a training family, so a dev seed is refused. Dev needs families of its own.
FAMILY_PARTITION = dict.fromkeys(VARIANTS, "train")


def partition_for_seed(seed: int) -> str:
    """The partition of a seed's block. Seeds outside blocks 0-9 belong to nothing in M0."""
    block = seed // SEEDS_PER_BLOCK
    if block in TRAIN_BLOCKS:
        return "train"
    if block in DEV_BLOCKS:
        return "dev"
    raise ValueError(f"seed {seed} is outside the frozen M0 seed blocks 0-9")


def episode_spec(
    seed: int,
    variant: str,
    run_id: str,
    frozen: dict[str, Any],
    rubric: Any,
    code_note: str = "",
) -> EpisodeSpec:
    """The manifest declarations for one episode, all from the frozen protocol."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant}; known: {sorted(VARIANTS)}")
    family = f"m0-scripted-{variant}"
    partition = partition_for_seed(seed)
    if partition != FAMILY_PARTITION[variant]:
        raise ValueError(
            f"family {family} belongs to {FAMILY_PARTITION[variant]}, but seed {seed} is in "
            f"{partition}; a family lies wholly in one partition"
        )
    task = frozen["task"]
    notes = (
        "Simulated SO-100 under the scripted controller, not the owner's SO-101. "
        "No claim about any physical arm."
    )
    return EpisodeSpec(
        episode_id=f"{family}-seed-{seed:06d}",
        seed=seed,
        purpose="training",
        task_id=task["env_id"],
        task_version=task["version"],
        instruction=INSTRUCTION,
        embodiment_id=EMBODIMENT,
        rubric=rubric,
        protocol_version=frozen["protocol_version"],
        policy_family=family,
        partition=partition,
        suite_id="m0-collection",
        scene_group_id=f"m0-seed-block-{seed // SEEDS_PER_BLOCK}",
        session_group_id=run_id,
        max_steps=task["max_episode_steps"],
        notes=f"{notes} {code_note}".rstrip(),
    )


def record_scripted(
    env: SimEnv,
    seed: int,
    variant: str,
    run_id: str,
    tolerance_file: Path,
    out_dir: Path,
    code_note: str = "",
) -> Path:
    """Record one scripted episode under ``out_dir``, named by its episode id.

    A plan that could not be made is a real failure of this controller, and its episode reads as an
    ordinary ``never_lifted``. The manifest's notes then say ``planning_failed``, to tell them
    apart.
    """
    frozen = json.loads(tolerance_file.read_text(encoding="utf-8"))
    _, rubric = load_frozen(tolerance_file)
    platform = env.stack_identity().get("platform", "unknown")
    provenance = (
        f"Recorded on {platform} with CPU physics; replay is claimed only on the same stack. "
        f"{code_note}"
    )
    spec = episode_spec(seed, variant, run_id, frozen, rubric, provenance.rstrip())
    policy = ScriptedPickPlace(VARIANTS[variant])

    def closing_note() -> str | None:
        error = policy.planning_error
        return None if error is None else f"planning_failed: {error}"

    return record_episode(env, policy, spec, out_dir / spec.episode_id, closing_note)


def parse_episode(text: str) -> tuple[int, str]:
    """Split ``SEED:VARIANT``."""
    seed, separator, variant = text.partition(":")
    if not separator or variant not in VARIANTS:
        raise ValueError(f"{text} is not SEED:VARIANT with a variant in {sorted(VARIANTS)}")
    return int(seed), variant


def _run(args: argparse.Namespace) -> list[dict[str, str]]:
    require_frozen_file(args.tolerance_file)
    wanted = [parse_episode(text) for text in args.episode]
    frozen = json.loads(args.tolerance_file.read_text(encoding="utf-8"))
    _, rubric = load_frozen(args.tolerance_file)
    for seed, variant in wanted:
        episode_spec(seed, variant, "check", frozen, rubric)
    require_code_root()
    task = frozen["task"]
    env = ManiSkillPickCube(env_id=task["env_id"], max_episode_steps=task["max_episode_steps"])
    results: list[dict[str, str]] = []
    with ledgered_run(
        purpose="m0 scripted episodes",
        config={"episodes": args.episode, "tolerance_file": str(args.tolerance_file)},
        seeds={f"{seed}:{variant}": seed for seed, variant in wanted},
        env_lock={
            "stack": env.stack_identity(),
            "stack_lock_sha256": hashlib.sha256(STACK_LOCK.read_bytes()).hexdigest(),
        },
    ) as run:
        for seed, variant in wanted:
            path = record_scripted(
                env, seed, variant, run.directory.name, args.tolerance_file, args.out, run.code_note
            )
            manifest = json.loads((path / "episode.json").read_text(encoding="utf-8"))
            results.append(
                {
                    "episode": str(path),
                    "run": str(run.directory),
                    "outcome": manifest["outcome"]["reason"],
                }
            )
        run.note = f"{len(results)} episodes"
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode", action="append", required=True, help="SEED:VARIANT")
    parser.add_argument("--tolerance-file", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        results = _run(args)
    except SimulatorUnavailableError as exc:
        print(f"not run: {exc}", file=sys.stderr)
        return 3
    except (ReplayInvalidError, ValueError, KeyError, TypeError, OSError) as exc:
        print(f"refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
