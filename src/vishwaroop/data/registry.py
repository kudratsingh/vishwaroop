"""Check and record a collected dataset (WO-002).

    python -m vishwaroop.data.registry build --root data/derived/m0-dataset/<commit> \\
        --out artifacts/manifests/m0-dataset-v1.json
    python -m vishwaroop.data.registry summarize artifacts/manifests/m0-dataset-v1.json

The contract validator checks an episode against itself, so a split edited consistently in a
manifest passes it, and passes replay. ``check_episode`` closes that gap: it ties the seed, from the
hashed initial state, to its block and partition, and the family to its one partition. Like the
other checks, it catches mistakes, not forgery: re-hashing an edited state too can defeat it.

Exit codes: 0 done, 1 the dataset misses a frozen threshold, 2 refused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ironclad.contracts.v1.audit_splits import audit
from ironclad.contracts.v1.validate import ContractError, validate_episode

from ..sim.baseline import UNREACHABLE_HOLD_STEPS
from ..sim.record import FAMILY_PARTITION, SEEDS_PER_BLOCK, partition_for_seed

FAMILY_PREFIX = "m0-scripted-"
SUCCESS = "success"
SUITE = "m0-collection"
PLANNING_FAILED = "planning_failed"
MIN_EPISODES = 200
MIN_FAILURE_SHARE = 0.30
MIN_FAILURE_MODES = 3
LICENSES = {
    "mani_skill": "Apache-2.0, per the LICENSE file in the mani_skill 3.0.1 wheel",
    "so100_assets": "the LICENSE file beside the SO-100 assets in that wheel, Apache-2.0 text",
}


class RegistryError(ValueError):
    """An episode's declared split or family disagrees with what its files show."""


@dataclass(frozen=True)
class Entry:
    """One checked episode. ``label`` comes from the independent rubric's assessment."""

    episode_id: str
    seed: int
    family: str
    partition: str
    scene_group_id: str
    session_group_id: str
    label: str
    planning_failed: bool
    episode_sha256: str
    transitions_sha256: str
    path: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_episode(episode_dir: Path) -> Entry:
    """Validate one episode and tie its split to its seed. ``RegistryError`` on a mismatch."""
    manifest_path = episode_dir / "episode.json"
    validate_episode(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    state_path = episode_dir / manifest["simulator"]["initial_state_artifact"]["path"]
    seed = json.loads(state_path.read_bytes())["seed"]
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise RegistryError(f"{manifest['episode_id']}: the saved state has no integer seed")
    split = manifest["split"]
    family = manifest["policy"]["family_id"]
    name = manifest["episode_id"]
    expected_partition = partition_for_seed(seed)
    if split["partition"] != expected_partition:
        raise RegistryError(
            f"{name}: seed {seed} belongs to {expected_partition}, but its split says "
            f"{split['partition']}"
        )
    expected_scene = f"m0-seed-block-{seed // SEEDS_PER_BLOCK}"
    if split["scene_group_id"] != expected_scene:
        raise RegistryError(
            f"{name}: seed {seed} belongs to {expected_scene}, not {split['scene_group_id']}"
        )
    if split["policy_run_group_id"] != family:
        raise RegistryError(f"{name}: its run group and family differ")
    if not family.startswith(FAMILY_PREFIX):
        raise RegistryError(f"{name}: unknown family {family}")
    home = FAMILY_PARTITION.get(family.removeprefix(FAMILY_PREFIX))
    if home is None:
        raise RegistryError(f"{name}: unknown family {family}")
    if home != split["partition"]:
        raise RegistryError(f"{name}: family {family} belongs to {home}, not {split['partition']}")
    if name != f"{family}-seed-{seed:06d}":
        raise RegistryError(f"{name}: its id does not name its family and seed {seed}")
    expected_purpose = "training" if split["partition"] == "train" else "evaluation"
    if manifest["purpose"] != expected_purpose:
        raise RegistryError(f"{name}: purpose {manifest['purpose']} is not {expected_purpose}")
    if split["suite_id"] != SUITE or split["inherited_from_parent"] is not False:
        raise RegistryError(f"{name}: its suite or inheritance is not this collection's")
    outcome = manifest["outcome"]
    assessment = episode_dir / outcome["final_assessment_artifact"]["path"]
    label = json.loads(assessment.read_text(encoding="utf-8"))["label"]
    if outcome["success"] != (label == SUCCESS) or not outcome["reason"].startswith(f"{label}:"):
        raise RegistryError(f"{name}: its declared outcome disagrees with its assessment, {label}")
    planning_failed = PLANNING_FAILED in manifest["notes"]
    if planning_failed != (manifest["data"]["record_count"] == UNREACHABLE_HOLD_STEPS):
        raise RegistryError(f"{name}: its notes and its length disagree about a planning failure")
    if planning_failed and label != "never_lifted":
        raise RegistryError(f"{name}: a planning failure cannot be labelled {label}")
    return Entry(
        episode_id=name,
        seed=seed,
        family=family,
        partition=split["partition"],
        scene_group_id=split["scene_group_id"],
        session_group_id=split["session_group_id"],
        label=label,
        planning_failed=planning_failed,
        episode_sha256=_sha256(manifest_path),
        transitions_sha256=_sha256(episode_dir / manifest["data"]["transitions_artifact"]["path"]),
        path=str(episode_dir),
    )


def episode_dirs(root: Path) -> list[Path]:
    """Every episode directory under ``root``, in a stable order."""
    return sorted(path.parent for path in root.rglob("episode.json"))


def summarize(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts by family and outcome, and the frozen ET-M0-6 thresholds against them.

    A planning failure is a real failure of the controller, so it counts as a failure. The share
    without those episodes is reported too, and the threshold must hold both ways.
    """
    total = len(entries)
    labels = Counter(entry["label"] for entry in entries)
    modes = sorted(label for label in labels if label != SUCCESS)
    failures = total - labels[SUCCESS]
    unplanned = sum(entry["planning_failed"] for entry in entries)
    share = failures / total if total else 0.0
    planned = total - unplanned
    planned_share = (failures - unplanned) / planned if planned else 0.0
    by_family: dict[str, Counter[str]] = {}
    for entry in entries:
        by_family.setdefault(entry["family"], Counter())[entry["label"]] += 1
    partitions = Counter(entry["partition"] for entry in entries)
    return {
        "episodes": total,
        "partitions": dict(partitions),
        "labels": dict(labels),
        "failures": failures,
        "failure_share": share,
        "planning_failed_episodes": unplanned,
        "failure_share_without_planning_failures": planned_share,
        "failure_modes": modes,
        "by_family": {family: dict(counts) for family, counts in sorted(by_family.items())},
        "et_m0_6_counts_met": (
            total >= MIN_EPISODES
            and share >= MIN_FAILURE_SHARE
            and planned_share >= MIN_FAILURE_SHARE
            and len(modes) >= MIN_FAILURE_MODES
        ),
    }


def planned_episode_ids(plan: dict[str, Any]) -> set[str]:
    """Every episode id a dataset plan calls for."""
    return {
        f"{FAMILY_PREFIX}{family['variant']}-seed-{seed:06d}"
        for family in plan["families"]
        for seed in range(family["first_seed"], family["first_seed"] + family["count"])
    }


def _check_against_records(
    entries: list[dict[str, Any]], plan: dict[str, Any], runs_ledger: Path
) -> None:
    """The set must be what was planned, each from a run the ledger shows as completed."""
    found = {entry["episode_id"] for entry in entries}
    wanted = planned_episode_ids(plan)
    if found != wanted:
        raise RegistryError(
            f"the set differs from the plan: {len(wanted - found)} missing, "
            f"{len(found - wanted)} unplanned, for example {sorted(found ^ wanted)[:3]}"
        )
    lines = runs_ledger.read_text(encoding="utf-8").splitlines()
    completed = {
        record["run_id"] for record in map(json.loads, lines) if record.get("status") == "completed"
    }
    unknown = sorted({entry["session_group_id"] for entry in entries} - completed)
    if unknown:
        raise RegistryError(f"sessions with no completed run in {runs_ledger}: {unknown}")


def build(root: Path, plan: dict[str, Any], runs_ledger: Path) -> dict[str, Any]:
    """Check every episode under ``root``, run the split audit, and assemble the manifest."""
    directories = episode_dirs(root)
    if not directories:
        raise RegistryError(f"no episodes under {root}")
    entries = [vars(check_episode(directory)) for directory in directories]
    _check_against_records(entries, plan, runs_ledger)
    result = audit([directory / "episode.json" for directory in directories])
    return {
        "name": root.name,
        "dataset": "m0-dataset-v1",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "licenses": LICENSES,
        "lineage": "simulator episodes under scripted controllers; no parents",
        "audit_splits": {
            key: value
            for key, value in result.items()
            if isinstance(value, str | int | float | bool) or value is None
        },
        "summary": summarize(entries),
        "episodes": entries,
    }


def _build(args: argparse.Namespace) -> int:
    if args.out.exists() or not args.out.parent.is_dir():
        raise RegistryError(f"{args.out} exists or has no directory; manifests are write-once")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    manifest = build(args.root, plan, args.runs_ledger)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(manifest["summary"], indent=2, sort_keys=True))
    return 0 if manifest["summary"]["et_m0_6_counts_met"] else 1


def _summarize(args: argparse.Namespace) -> int:
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    summary = summarize(manifest["episodes"])
    if summary != manifest["summary"]:
        raise RegistryError("the manifest's summary does not match its episodes")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["et_m0_6_counts_met"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("build")
    make.add_argument("--root", type=Path, required=True)
    make.add_argument("--out", type=Path, required=True)
    make.add_argument("--plan", type=Path, default=Path("evals/M0-dataset-plan.json"))
    make.add_argument("--runs-ledger", type=Path, default=Path("ledgers/runs.jsonl"))
    make.set_defaults(run=_build)
    show = commands.add_parser("summarize")
    show.add_argument("manifest", type=Path)
    show.set_defaults(run=_summarize)
    args = parser.parse_args(argv)
    try:
        code: int = args.run(args)
    except (ContractError, RegistryError, ValueError, KeyError, TypeError, OSError) as exc:
        print(f"refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return code


if __name__ == "__main__":
    sys.exit(main())
