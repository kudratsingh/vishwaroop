#!/usr/bin/env python3
"""Audit an assembled set of episode manifests for explicit lineage and split-group leakage.

This checks declared groups and parent links; it is not statistical proof of independence and
cannot detect undeclared confounders or test-set disclosure.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from validate import ContractError, read_json, validate_episode

DEFAULT_GROUPS: tuple[str, ...] = ("session_group_id", "policy_run_group_id")


def audit(paths: list[Path], group_fields: tuple[str, ...] = DEFAULT_GROUPS) -> dict[str, Any]:
    """Validate every episode, then check group leakage, parent lineage and cycles."""
    episodes: dict[str, dict[str, Any]] = {}
    for path in paths:
        validate_episode(path)
        episode = read_json(path)
        if episode["episode_id"] in episodes:
            raise ContractError("duplicate episode ID")
        episodes[episode["episode_id"]] = episode

    group_seen: dict[tuple[str, str], set[str]] = {}
    for episode in episodes.values():
        partition = episode["split"]["partition"]
        for field in group_fields:
            value = episode["split"][field]
            if value is not None:
                group_seen.setdefault((field, value), set()).add(partition)
        # Raw run identity is also enforced, so renaming a grouping field cannot hide leakage.
        run_id = episode["policy"]["training_run_id"]
        if run_id is not None:
            group_seen.setdefault(("training_run_id", run_id), set()).add(partition)
        for parent_id in episode["provenance"]["parent_episode_ids"]:
            if parent_id not in episodes:
                raise ContractError(
                    f"parent {parent_id} absent from assembled audit; lineage unverified"
                )
            if partition != episodes[parent_id]["split"]["partition"]:
                raise ContractError("parent/descendant split leakage")
    for key, partitions in group_seen.items():
        if len(partitions) > 1:
            raise ContractError(f"group leakage: {key}: {sorted(partitions)}")

    visiting: set[str] = set()
    done: set[str] = set()

    def visit(episode_id: str) -> None:
        if episode_id in visiting:
            raise ContractError("cyclic episode lineage")
        if episode_id in done:
            return
        visiting.add(episode_id)
        for parent in episodes[episode_id]["provenance"]["parent_episode_ids"]:
            visit(parent)
        visiting.remove(episode_id)
        done.add(episode_id)

    for episode_id in episodes:
        visit(episode_id)
    return {
        "episodes": len(episodes),
        "status": "declared_group_and_lineage_checks_passed",
        "note": "No guarantee against undeclared confounders or test-set disclosure.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episodes", type=Path, nargs="+")
    parser.add_argument(
        "--holdout-scenes", action="store_true", help="also treat scene_group_id as a holdout axis"
    )
    args = parser.parse_args(argv)
    groups = DEFAULT_GROUPS + (("scene_group_id",) if args.holdout_scenes else ())
    try:
        print(json.dumps(audit(args.episodes, groups), indent=2))
        return 0
    except (ContractError, OSError, KeyError, TypeError) as exc:
        print(f"INVALID: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
