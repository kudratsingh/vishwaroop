"""Record scripted episodes on the frozen M0 task, in the real simulator.

    python -m vishwaroop.sim.record --seed 12 --variant nominal --run-id wo-001-first \\
        --tolerance-file evals/M0-exit-tests.json --out data/derived/m0

The episode's split, its group ids and its rubric come from ``evals/M0-protocol.md`` and the frozen
exit tests. Nothing is overwritten: the contract writer refuses an existing directory.

Exit codes: 0 recorded, 2 a precondition failed, 3 the simulator cannot run here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .baseline import VARIANTS, ScriptedPickPlace
from .env import ManiSkillPickCube, SimEnv, SimulatorUnavailableError
from .export import EpisodeSpec, record_episode
from .replay import ReplayInvalidError, load_frozen, require_frozen_file

SEEDS_PER_BLOCK = 1000
TRAIN_BLOCKS = range(8)
DEV_BLOCKS = range(8, 10)
EMBODIMENT = "maniskill3_so100"
INSTRUCTION = "Pick up the cube and place it on the table at the goal's xy position."


def partition_for_seed(seed: int) -> str:
    """The partition of a seed's block. Seeds outside blocks 0-9 belong to nothing in M0."""
    block = seed // SEEDS_PER_BLOCK
    if block in TRAIN_BLOCKS:
        return "train"
    if block in DEV_BLOCKS:
        return "dev"
    raise ValueError(f"seed {seed} is outside the frozen M0 seed blocks 0-9")


def episode_spec(
    seed: int, variant: str, run_id: str, frozen: dict[str, Any], rubric: Any
) -> EpisodeSpec:
    """The manifest declarations for one episode, all from the frozen protocol."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant}; known: {sorted(VARIANTS)}")
    family = f"m0-scripted-{variant}"
    partition = partition_for_seed(seed)
    task = frozen["task"]
    return EpisodeSpec(
        episode_id=f"{family}-seed-{seed:06d}",
        seed=seed,
        purpose="training" if partition == "train" else "evaluation",
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
        notes=(
            "Simulated SO-100 under the scripted controller, not the owner's SO-101. "
            "No claim about any physical arm."
        ),
    )


def record_scripted(
    env: SimEnv,
    seed: int,
    variant: str,
    run_id: str,
    tolerance_file: Path,
    out_dir: Path,
) -> Path:
    """Record one scripted episode under ``out_dir``, named by its episode id."""
    frozen = json.loads(tolerance_file.read_text(encoding="utf-8"))
    _, rubric = load_frozen(tolerance_file)
    spec = episode_spec(seed, variant, run_id, frozen, rubric)
    policy = ScriptedPickPlace(VARIANTS[variant])
    return record_episode(env, policy, spec, out_dir / spec.episode_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--variant", required=True, choices=sorted(VARIANTS))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--tolerance-file", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        require_frozen_file(args.tolerance_file)
        env = ManiSkillPickCube()
        path = record_scripted(
            env, args.seed, args.variant, args.run_id, args.tolerance_file, args.out
        )
    except SimulatorUnavailableError as exc:
        print(f"not run: {exc}", file=sys.stderr)
        return 3
    except (ReplayInvalidError, ValueError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    manifest = json.loads((path / "episode.json").read_text(encoding="utf-8"))
    print(json.dumps({"episode": str(path), "outcome": manifest["outcome"]["reason"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
