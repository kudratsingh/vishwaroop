"""WO-019: import banshee's four published D1 exports read-only, revalidate, and audit the M4 split.

    python -m vishwaroop.data.banshee_import verify --source <banshee>/data/exports
    python -m vishwaroop.data.banshee_import import --source <banshee>/data/exports
    python -m vishwaroop.data.banshee_import audit

Run it from the repository root, in the tooling environment (the pinned ironclad-kit v1.2.0), at a
clean commit. The rules are ET-M4-1 in ``evals/M4-exit-tests.json`` as amended by
``evals/M4-amendment-1.json`` and ``evals/M4-amendment-2.json``; all three are pinned by sha256
here and refused if changed.

``verify`` reads the exports in place and writes nothing. For each export it requires COMPLETE to
hold the sha256 of MANIFEST.json, and that to equal the hash the owner was given. It applies the
amended schema check: ``contract.schema_version`` exactly "1.0.0", with no conflicting declaration.
It checks every listed file's path, size and sha256, and that nothing unlisted is present. For the
two episode exports, it requires each episode.json's schema_version to be exactly "1.0.0", and
amendment 2's metadata check: split.partition "train" for the train split and "dev" for held-out,
the entry's partition equal to it, and scene_group_id equal to the entry's family_id.
``import`` runs the same checks, then copies each export, MANIFEST.json and COMPLETE included and
byte for byte, into ``data/imports/<export_id>/``. It re-hashes every copied file, makes the copy
read-only, and appends one ``ledgers/imports.jsonl`` line per export and one
``ledgers/licenses.jsonl`` line. ``audit`` is a ledgered run on the imported copies. It validates
every episode with the pinned validator, runs the contract's split audit over both episode exports
together, applies ET-M4-2's four data checks to their union, and writes
``artifacts/manifests/banshee-d1-import-v1.json``.

banshee is never written to and none of its code is run. Exit codes: 0 done, 2 refused or stopped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FROZEN = {
    Path("evals/M4-exit-tests.json"): (
        "86b6d7d1ac8743c483d15078eeb97204208561254913b9df76261ff01e918651"
    ),
    Path("evals/M4-amendment-1.json"): (
        "79f8b00597f69fd0eaba993bc4323a5f4dea2d61d0e9b8330f2c2762415b52aa"
    ),
    Path("evals/M4-amendment-2.json"): (
        "334cc6b9b93c74afcf3ab0757ab85ecd310b876a4e7300d3db4d6490ea50763d"
    ),
}
# amendment 2: the published split.partition for each M4 split
PARTITION_FOR_SPLIT = {"train": "train", "heldout": "dev"}
# The manifest sha256 of each published export, as banshee's COMPLETE markers and WO-029 report
# gave them to the owner on 2026-11-07.
EXPORTS = {
    "banshee-d1-sim-episodes": "d7bc0545852e8a3549790a956782723240faf6f4aa6496ab55ad15367d711fc0",
    "banshee-d1-sim-ulogs": "9e8c1fb2053f8a47289b4508789c1faad9649632f2a15bec7d97f09ad9d12f18",
    "banshee-d1-variation-v1-episodes": (
        "383dfea07505aa2db716c4c45a03eb31c6014f75bb603ddfd0a58f8096414cfe"
    ),
    "banshee-d1-variation-v1-ulogs": (
        "0b76d7b87bb78ab1b5fc94d3ac66af2c0e0389b4b6f0090a72f6b9961af940c0"
    ),
}
EPISODE_EXPORTS = ("banshee-d1-sim-episodes", "banshee-d1-variation-v1-episodes")
ULOG_FOR = {
    "banshee-d1-sim-episodes": "banshee-d1-sim-ulogs",
    "banshee-d1-variation-v1-episodes": "banshee-d1-variation-v1-ulogs",
}
SCHEMA_VERSION = "1.0.0"
PRODUCER = "banshee"
IMPORTS = Path("data/imports")
ARTIFACT = Path("artifacts/manifests/banshee-d1-import-v1.json")
ACTION_LABELS = ["ve", "vn", "vu", "yaw_rate"]
ACTION_UNITS = ["m/s", "m/s", "m/s", "rad/s"]
M4_PARTITIONS = {"train", "heldout"}
STACKS = {"jazzy", "humble"}
MARKERS = ("MANIFEST.json", "COMPLETE")
FREE_SPACE_MARGIN_BYTES = 2 * 1024**3
SHARED_ENTRY_FIELDS = (
    "run_id",
    "stack",
    "airframe",
    "suite_id",
    "case_id",
    "family_id",
    "route_id",
    "wind_id",
    "fault_family",
    "split",
    "partition",
    "success",
)


class ImportStopError(ValueError):
    """A frozen stop condition: report it, copy nothing more."""


def strict_loads(raw: bytes | str) -> Any:
    """json.loads that refuses duplicate keys, so a repeated declaration cannot hide."""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in items:
            if key in out:
                raise ImportStopError(f"duplicate JSON key {key!r}")
            out[key] = value
        return out

    return json.loads(raw, object_pairs_hook=pairs)


def git_state(repo: Path = Path(".")) -> dict[str, Any]:
    """The checkout's commit and whether its tree is dirty (any change, untracked included)."""
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout
    return {"commit": commit, "dirty": bool(status.strip())}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_frozen(root: Path = Path(".")) -> dict[str, str]:
    for path, expected in FROZEN.items():
        actual = sha256_file(root / path)
        if actual != expected:
            raise ImportStopError(f"{path} has sha256 {actual}, not the frozen {expected}")
    return {str(path): digest for path, digest in FROZEN.items()}


def _schema_versions_outside_contract(value: Any, path: str = "") -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            where = f"{path}.{key}" if path else key
            if where == "contract":
                continue
            if key == "schema_version":
                found.append((where, item))
            found += _schema_versions_outside_contract(item, where)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found += _schema_versions_outside_contract(item, f"{path}[{index}]")
    return found


def check_schema_declaration(manifest: dict[str, Any], name: str) -> None:
    """The amended schema check: contract.schema_version exactly "1.0.0", nothing conflicting."""
    contract = manifest.get("contract")
    if not isinstance(contract, dict):
        raise ImportStopError(f"{name}: the manifest has no contract object")
    if "schema_version" not in contract:
        raise ImportStopError(f"{name}: contract.schema_version is missing")
    declared = contract["schema_version"]
    if not isinstance(declared, str):
        raise ImportStopError(f"{name}: contract.schema_version is not a string: {declared!r}")
    if declared != SCHEMA_VERSION:
        raise ImportStopError(f"{name}: contract.schema_version is {declared!r}, not '1.0.0'")
    conflicting = [
        (where, v)
        for where, v in _schema_versions_outside_contract(manifest)
        if v != SCHEMA_VERSION
    ]
    if conflicting:
        raise ImportStopError(f"{name}: conflicting schema_version declarations {conflicting}")


@dataclass(frozen=True)
class Export:
    """A verified export: its id, root, raw manifest bytes and parsed manifest."""

    export_id: str
    root: Path
    manifest_bytes: bytes
    manifest: dict[str, Any]

    @property
    def kind(self) -> str:
        return str(self.manifest["kind"])


def _safe(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts or "\\" in relative or not relative:
        raise ImportStopError(f"unsafe path in manifest: {relative!r}")
    path = root / candidate
    if not path.resolve().is_relative_to(root.resolve()):
        raise ImportStopError(f"path escapes the export: {relative!r}")
    return path


def _listed_files(root: Path) -> set[str]:
    return {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    } - set(MARKERS)


def verify_export(root: Path, export_id: str, expected: str, *, hash_files: bool = True) -> Export:
    """Every pre-copy check of one export, reading it in place."""
    if not (root / "COMPLETE").is_file():
        raise ImportStopError(f"{export_id}: no COMPLETE marker")
    raw = (root / "MANIFEST.json").read_bytes()
    actual = sha256_bytes(raw)
    complete = (root / "COMPLETE").read_text(encoding="ascii").strip()
    if not (actual == complete == expected):
        raise ImportStopError(
            f"{export_id}: MANIFEST.json sha256 {actual}, COMPLETE {complete}, expected {expected}"
        )
    manifest = strict_loads(raw)
    if manifest.get("export_id") != export_id or manifest.get("producer") != PRODUCER:
        raise ImportStopError(f"{export_id}: the manifest names another export or producer")
    check_schema_declaration(manifest, export_id)
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ImportStopError(f"{export_id}: the manifest lists no files")
    listed = {}
    for item in files:
        relative = item["path"]
        if relative in listed or relative in MARKERS:
            raise ImportStopError(f"{export_id}: {relative} is listed twice or is a marker")
        listed[relative] = item
        path = _safe(root, relative)
        if path.is_symlink() or not path.is_file():
            raise ImportStopError(f"{export_id}: {relative} is missing or not a regular file")
        if path.stat().st_size != item["bytes"]:
            raise ImportStopError(f"{export_id}: {relative} has another size than listed")
        if hash_files and sha256_file(path) != item["sha256"]:
            raise ImportStopError(f"{export_id}: {relative} does not match its sha256")
    unlisted = sorted(_listed_files(root) - set(listed))
    if unlisted:
        raise ImportStopError(f"{export_id}: files not in the manifest: {unlisted[:5]}")
    export = Export(export_id, root, raw, manifest)
    if export.kind not in ("episodes", "ulogs"):
        raise ImportStopError(f"{export_id}: unknown export kind {export.kind!r}")
    check_counts(export)
    if export.kind == "episodes":
        for entry in manifest["entries"]:
            episode = strict_loads((_safe(root, entry["path"]) / "episode.json").read_bytes())
            if episode.get("schema_version") != SCHEMA_VERSION:
                raise ImportStopError(
                    f"{export_id}: {entry['episode_id']} schema_version "
                    f"{episode.get('schema_version')!r}, not '1.0.0'"
                )
            check_published_split(entry, episode, export_id)
    else:
        for entry in manifest["entries"]:
            for ulog in entry.get("ulogs") or []:
                if listed.get(ulog["path"], {}).get("sha256") != ulog["sha256"]:
                    raise ImportStopError(f"{export_id}: {ulog['path']} is not a listed file")
            if not entry.get("ulogs"):
                raise ImportStopError(f"{export_id}: {entry['episode_id']} has no ULog")
    return export


def check_published_split(entry: dict[str, Any], episode: dict[str, Any], export_id: str) -> None:
    """Amendment 2's metadata check on one episode, before anything is copied."""
    split = episode.get("split", {})
    expected = PARTITION_FOR_SPLIT.get(str(entry.get("split")))
    problems = []
    if expected is None:
        problems.append(f"M4 split {entry.get('split')!r} is neither train nor heldout")
    elif split.get("partition") != expected:
        problems.append(f"split.partition {split.get('partition')!r}, not {expected!r}")
    if entry.get("partition") != split.get("partition"):
        problems.append("the entry's partition differs from split.partition")
    if split.get("scene_group_id") != entry.get("family_id"):
        problems.append("scene_group_id is not the entry's family_id")
    if problems:
        raise ImportStopError(f"{export_id}: {entry['episode_id']}: {'; '.join(problems)}")


def stack_counts(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts by stack and by stack and M4 split, computed here from the entries."""
    return {
        "by_stack": dict(sorted(Counter(e["stack"] for e in entries).items())),
        "by_stack_and_split": dict(
            sorted(Counter(f"{e['stack']}/{e['split']}" for e in entries).items())
        ),
        "successful": sum(1 for e in entries if e["success"] is True),
        "failed": sum(1 for e in entries if e["success"] is False),
    }


def check_counts(export: Export) -> None:
    """The entries' stacks are known, and the counts computed here equal the producer's."""
    entries = export.manifest["entries"]
    counts = export.manifest.get("counts", {})
    stacks = {e.get("stack") for e in entries}
    if not stacks <= STACKS:
        raise ImportStopError(f"{export.export_id}: unknown stacks {sorted(map(str, stacks))}")
    if counts.get("entries") != len(entries):
        raise ImportStopError(f"{export.export_id}: counts.entries differs from the entries")
    mine = stack_counts(entries)
    if counts.get("by_stack_and_split") != mine["by_stack_and_split"]:
        raise ImportStopError(f"{export.export_id}: stack and split counts differ")
    if (counts.get("successful"), counts.get("failed")) != (mine["successful"], mine["failed"]):
        raise ImportStopError(f"{export.export_id}: success counts differ")


def verify_all(source: Path, *, hash_files: bool = True) -> list[Export]:
    exports = [
        verify_export(source / export_id, export_id, expected, hash_files=hash_files)
        for export_id, expected in EXPORTS.items()
    ]
    by_id = {export.export_id: export for export in exports}
    for episodes, ulogs in ULOG_FOR.items():
        a = {e["episode_id"]: e for e in by_id[episodes].manifest["entries"]}
        b = {e["episode_id"]: e for e in by_id[ulogs].manifest["entries"]}
        if set(a) != set(b) or len(a) != len(by_id[episodes].manifest["entries"]):
            raise ImportStopError(f"{episodes} and {ulogs} list different episodes")
        for episode_id, entry in a.items():
            other = b[episode_id]
            differing = [f for f in SHARED_ENTRY_FIELDS if entry.get(f) != other.get(f)]
            if differing:
                raise ImportStopError(f"{episode_id}: {ulogs} differs in {differing}")
    return exports


def partition_table(export: Export) -> dict[str, int]:
    """How episode.json's split.partition goes with the M4 split, for the record."""
    table: Counter[str] = Counter()
    for entry in export.manifest["entries"]:
        episode = strict_loads((export.root / entry["path"] / "episode.json").read_bytes())
        table[f"{entry['split']} -> {episode['split']['partition']}"] += 1
    return dict(sorted(table.items()))


def _make_read_only(root: Path) -> None:
    mode = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(mode | (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH if path.is_dir() else 0))
    root.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def copy_export(export: Export, repo: Path) -> Path:
    """Copy write-once to data/imports/<export_id>/, re-hash, make read-only."""
    target = repo / IMPORTS / export.export_id
    incoming = repo / IMPORTS / f".{export.export_id}.incoming"
    if target.exists():
        raise ImportStopError(f"{target} exists; imports are write-once")
    if incoming.exists():
        raise ImportStopError(f"{incoming} is left from an earlier attempt; the owner inspects it")
    incoming.mkdir(parents=True)
    for item in export.manifest["files"]:
        destination = _safe(incoming, item["path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(export.root / item["path"], destination)
        if sha256_file(destination) != item["sha256"]:
            raise ImportStopError(f"{export.export_id}: the copy of {item['path']} differs")
    for marker in MARKERS:
        shutil.copyfile(export.root / marker, incoming / marker)
    verify_export(incoming, export.export_id, EXPORTS[export.export_id])
    _make_read_only(incoming)
    os.rename(incoming, target)
    return target


def import_record(export: Export, frozen: dict[str, str], commit: str) -> dict[str, Any]:
    manifest = export.manifest
    return {
        "export_id": export.export_id,
        "producer": PRODUCER,
        "kind": export.kind,
        "source": f"banshee:data/exports/{export.export_id}",
        "target": str(IMPORTS / export.export_id),
        "manifest_sha256": EXPORTS[export.export_id],
        "source_commit": manifest["source_commit"],
        "created_at": manifest["created_at"],
        "contract": manifest["contract"],
        "split_plan": manifest.get("split_plan"),
        "transformation": manifest.get("transformation"),
        "counts": manifest["counts"],
        "stacks": stack_counts(manifest["entries"]),
        "files": len(manifest["files"]),
        "bytes": sum(item["bytes"] for item in manifest["files"]),
        "rights": manifest["rights"],
        "read_only": True,
        "rules": frozen,
        "tool_commit": commit,
        "actor": "claude-code-vishwaroop",
        "work_order": "WO-019",
    }


def license_record() -> dict[str, Any]:
    return {
        "asset": "banshee D1 simulation exports: " + ", ".join(EXPORTS),
        "date": "2026-11-07",
        "license": (
            "owner-private, all rights reserved; shared between the owner's own projects; "
            "publication terms decided per paper (owner, 2026-11-06). The producer manifests "
            "say: Owner-private. All rights reserved. For use within the owner's projects only."
        ),
        "use": "M4 dynamics data (ET-M4-1, ET-M4-2); ULogs are not contract records",
        "work_order": "WO-019",
    }


def _imported(repo: Path) -> dict[str, Export]:
    out = {}
    for export_id, expected in EXPORTS.items():
        root = repo / IMPORTS / export_id
        raw = (root / "MANIFEST.json").read_bytes()
        if sha256_bytes(raw) != expected:
            raise ImportStopError(f"the imported {export_id} manifest differs from the producer's")
        out[export_id] = Export(export_id, root, raw, strict_loads(raw))
    return out


def data_checks(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """ET-M4-2's four data checks, over the union of both episode exports.

    Each item has the manifest ``entry``, its ``export_id`` and the ``episode`` (episode.json).
    ``passed`` is the frozen checks only: (1) every episode_id once, no transitions sha256 in two
    families; (2) every family in one M4 partition; (3) exactly one training and one held-out
    partition designated (others may exist and are unused); (4) the action labels and units and
    the 7-value enu_local state stream; families_and_partitions' family id <-> triple
    bijection; and amendment 2's published split.partition and scene_group_id.
    ``other_problems`` holds consistency checks that the freeze does not gate on.
    """
    problems: list[str] = []
    other: list[str] = []
    ids = Counter(item["entry"]["episode_id"] for item in episodes)
    problems += [f"episode_id {k} occurs {n} times" for k, n in ids.items() if n > 1]
    triples: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    families_of_triple: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    transitions: dict[str, set[str]] = defaultdict(set)
    partitions: dict[str, set[str]] = defaultdict(set)
    sessions: dict[str, set[str]] = defaultdict(set)
    for item in episodes:
        entry, episode = item["entry"], item["episode"]
        family = entry["family_id"]
        if episode["episode_id"] != entry["episode_id"]:
            other.append(f"{entry['episode_id']}: episode.json names {episode['episode_id']}")
        if episode["split"]["scene_group_id"] != family:
            problems.append(f"{entry['episode_id']}: scene_group_id is not the family id")
        if episode["split"]["partition"] != PARTITION_FOR_SPLIT.get(entry["split"]):
            problems.append(f"{entry['episode_id']}: split.partition is not the published mapping")
        if episode["split"]["partition"] != entry["partition"]:
            problems.append(f"{entry['episode_id']}: split.partition differs from the manifest")
        triple = (entry["route_id"], entry["wind_id"], entry["fault_family"])
        triples[family].add(triple)
        families_of_triple[triple].add(family)
        transitions[episode["data"]["transitions_artifact"]["sha256"]].add(family)
        partitions[family].add(entry["split"])
        sessions[episode["split"]["session_group_id"]].add(entry["split"])
        spec = episode["action_spec"]
        if spec["labels"] != ACTION_LABELS or spec["units"] != ACTION_UNITS:
            problems.append(f"{entry['episode_id']}: action_spec is not {ACTION_LABELS}")
        state = [s for s in episode["streams"] if s["name"] == "state"]
        if len(state) != 1 or state[0]["frame_id"] != "enu_local" or state[0]["shape"] != [7]:
            problems.append(f"{entry['episode_id']}: no 7-value enu_local 'state' stream")
    problems += [f"family {f} has triples {sorted(t)}" for f, t in triples.items() if len(t) > 1]
    problems += [
        f"triple {t} has families {sorted(f)}" for t, f in families_of_triple.items() if len(f) > 1
    ]
    problems += [
        f"transitions sha256 {h[:12]} in families {sorted(f)}"
        for h, f in transitions.items()
        if len(f) > 1
    ]
    problems += [
        f"family {f} in partitions {sorted(p)}" for f, p in partitions.items() if len(p) > 1
    ]
    other += [f"session {s} in partitions {sorted(p)}" for s, p in sessions.items() if len(p) > 1]
    designated = {p for parts in partitions.values() for p in parts}
    if not designated >= M4_PARTITIONS:
        problems.append(
            f"the manifests designate partitions {sorted(designated)}, not one train and one "
            "heldout"
        )
    if designated != M4_PARTITIONS:
        other.append(f"partitions other than train and heldout: {sorted(designated)}")
    by_partition: dict[str, dict[str, Any]] = {}
    for split in sorted(designated):
        chosen = [i for i in episodes if i["entry"]["split"] == split]
        by_partition[split] = {
            "episodes": len(chosen),
            "families": len({i["entry"]["family_id"] for i in chosen}),
            "succeeded": sum(1 for i in chosen if i["entry"]["success"]),
            "failed": sum(1 for i in chosen if not i["entry"]["success"]),
            "by_stack": dict(Counter(i["entry"]["stack"] for i in chosen)),
            "by_export": dict(Counter(i["export_id"] for i in chosen)),
        }
    families: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"episodes": 0, "failed": 0, "exports": set(), "stacks": set()}
    )
    for item in episodes:
        cell = families[item["entry"]["family_id"]]
        cell["episodes"] += 1
        cell["failed"] += 0 if item["entry"]["success"] else 1
        cell["exports"].add(item["export_id"])
        cell["stacks"].add(item["entry"]["stack"])
        cell["partition"] = item["entry"]["split"]
    return {
        "passed": not problems,
        "problems": problems,
        "other_checks_passed": not other,
        "other_problems": other,
        "episodes": len(episodes),
        "by_partition": by_partition,
        "families": {
            family: {**cell, "exports": sorted(cell["exports"]), "stacks": sorted(cell["stacks"])}
            for family, cell in sorted(families.items())
        },
    }


def run_audit(repo: Path) -> dict[str, Any]:
    from ironclad.contracts.v1.audit_splits import audit
    from ironclad.contracts.v1.validate import ContractError, validate_episode

    imported = _imported(repo)
    episodes: list[dict[str, Any]] = []
    validation: dict[str, Any] = {"contract_valid": 0, "invalid": []}
    paths: list[Path] = []
    for export_id in EPISODE_EXPORTS:
        export = imported[export_id]
        for item in export.manifest["files"]:
            if sha256_file(export.root / item["path"]) != item["sha256"]:
                raise ImportStopError(f"{export_id}: imported {item['path']} changed")
        for entry in export.manifest["entries"]:
            path = export.root / entry["path"] / "episode.json"
            try:
                result = validate_episode(path)
            except (ContractError, OSError, ValueError) as exc:
                error = str(exc).replace(str(repo.resolve()), ".")
                validation["invalid"].append({"episode_id": entry["episode_id"], "error": error})
                continue
            if result["status"] == "contract_valid":
                validation["contract_valid"] += 1
            paths.append(path)
            episodes.append(
                {"export_id": export_id, "entry": entry, "episode": strict_loads(path.read_bytes())}
            )
    total = sum(len(imported[e].manifest["entries"]) for e in EPISODE_EXPORTS)
    validation["episodes"] = total
    validation["all_contract_valid"] = validation["contract_valid"] == total
    contract_audit: dict[str, Any] = {}
    for holdout_scenes in (False, True):
        base: tuple[str, ...] = ("session_group_id", "policy_run_group_id")
        fields = (*base, "scene_group_id") if holdout_scenes else base
        try:
            contract_audit[f"holdout_scenes={holdout_scenes}"] = audit(paths, fields)
        except ContractError as exc:
            contract_audit[f"holdout_scenes={holdout_scenes}"] = {
                "status": "failed",
                "error": str(exc).replace(str(repo.resolve()), "."),
            }
    checks = data_checks(episodes)
    ulogs: dict[str, Any] = {}
    for episodes_id, ulog_id in ULOG_FOR.items():
        export = imported[ulog_id]
        for item in export.manifest["files"]:
            if sha256_file(export.root / item["path"]) != item["sha256"]:
                raise ImportStopError(f"{ulog_id}: imported {item['path']} changed")
        ulogs[ulog_id] = {
            "files": len(export.manifest["files"]),
            "bytes": sum(item["bytes"] for item in export.manifest["files"]),
            "episodes": len(export.manifest["entries"]),
            "for": episodes_id,
            "sha256_match": True,
        }
    return {
        "validator": "ironclad-kit 1.2.0 (vishwaroop's pin), ironclad.contracts.v1.validate",
        "validation": validation,
        "contract_split_audit": contract_audit,
        "m4_data_checks": checks,
        "ulogs": ulogs,
        "manifests": {export_id: EXPORTS[export_id] for export_id in EXPORTS},
        "partition_tables": {e: partition_table(imported[e]) for e in EPISODE_EXPORTS},
        "stacks": {e: stack_counts(imported[e].manifest["entries"]) for e in EPISODE_EXPORTS},
        "episodes_index": [
            {
                "episode_id": item["entry"]["episode_id"],
                "export_id": item["export_id"],
                "stack": item["entry"]["stack"],
                "family_id": item["entry"]["family_id"],
                "m4_split": item["entry"]["split"],
                "split_partition": item["episode"]["split"]["partition"],
                "success": item["entry"]["success"],
            }
            for item in episodes
        ],
        "passed": validation["all_contract_valid"]
        and checks["passed"]
        and all(a.get("status") != "failed" for a in contract_audit.values()),
    }


def _cmd_verify(args: argparse.Namespace) -> int:
    check_frozen()
    exports = verify_all(args.source)
    for export in exports:
        line: dict[str, Any] = {
            "export_id": export.export_id,
            "kind": export.kind,
            "entries": len(export.manifest["entries"]),
            "files": len(export.manifest["files"]),
            "bytes": sum(item["bytes"] for item in export.manifest["files"]),
            "manifest_sha256": EXPORTS[export.export_id],
            "contract": export.manifest["contract"],
            "stacks": stack_counts(export.manifest["entries"]),
        }
        if export.kind == "episodes":
            line["split_partition_by_m4_split"] = partition_table(export)
        print(json.dumps(line, sort_keys=True))
    return 0


def _ledgered(path: Path, field: str, value: str) -> bool:
    if not path.exists():
        return False
    return any(json.loads(line).get(field) == value for line in path.read_text().splitlines())


def _cmd_import(args: argparse.Namespace) -> int:
    """Copy every export not yet imported; one that already is must re-verify, and only its
    missing ledger lines are written, so a stopped import can be resumed without deleting."""
    from ironclad.core.ledger import append_record

    frozen = check_frozen()
    git = git_state()
    if git["dirty"]:
        raise ImportStopError("commit first, so the import record names clean code")
    repo = Path(".")
    exports = verify_all(args.source)
    pending = [e for e in exports if not (repo / IMPORTS / e.export_id).exists()]
    needed = sum(item["bytes"] for e in pending for item in e.manifest["files"])
    (repo / IMPORTS).mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(repo / IMPORTS).free
    if free < needed + FREE_SPACE_MARGIN_BYTES:
        raise ImportStopError(f"{needed} bytes to copy but {free} free (margin 2 GiB)")
    imports = repo / "ledgers/imports.jsonl"
    for export in exports:
        target = repo / IMPORTS / export.export_id
        if target.exists():
            verify_export(target, export.export_id, EXPORTS[export.export_id])
            print(f"already imported and re-verified: {target}")
        else:
            copy_export(export, repo)
            print(f"imported {export.export_id} -> {target}")
        if not _ledgered(imports, "manifest_sha256", EXPORTS[export.export_id]):
            append_record(imports, import_record(export, frozen, git["commit"]))
    licenses = repo / "ledgers/licenses.jsonl"
    record = license_record()
    if not _ledgered(licenses, "asset", record["asset"]):
        append_record(licenses, record)
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    from ..sim.runlog import ledgered_run, require_code_root

    require_code_root()
    frozen = check_frozen()
    if git_state()["dirty"]:
        raise ImportStopError("commit first, so the code note stays true")
    with ledgered_run(
        purpose="WO-019: revalidate banshee's imported D1 episodes and audit the M4 split",
        config={"frozen": frozen, "manifests": EXPORTS},
        seeds={},
        env_lock={"validator": "ironclad-kit 1.2.0"},
    ) as run:
        if run.dirty:
            raise ImportStopError("commit first, so the code note stays true")
        report = {"run": run.directory.name, "code": run.code_note, **run_audit(Path("."))}
        text = json.dumps(report, indent=1, sort_keys=True, allow_nan=False) + "\n"
        (run.directory / "import_audit.json").write_text(text, encoding="utf-8")
        if report["passed"]:
            ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
            with ARTIFACT.open("x", encoding="utf-8") as stream:
                stream.write(text)
        run.note = f"banshee D1 import audit passed {report['passed']}"
        print(run.note)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("verify", "import"):
        command = commands.add_parser(name)
        command.add_argument("--source", type=Path, required=True, help="banshee's data/exports")
    commands.add_parser("audit")
    args = parser.parse_args(argv)
    try:
        run = {"verify": _cmd_verify, "import": _cmd_import, "audit": _cmd_audit}[args.command]
        return run(args)
    except (ImportStopError, OSError, KeyError, ValueError) as exc:
        print(f"stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
