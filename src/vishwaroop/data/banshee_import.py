"""WO-019: import banshee's four published D1 exports read-only, revalidate, and audit the M4 split.

    python -m vishwaroop.data.banshee_import verify --source <banshee>/data/exports
    python -m vishwaroop.data.banshee_import import --source <banshee>/data/exports
    python -m vishwaroop.data.banshee_import audit

Run it from the repository root, in the tooling environment (the pinned ironclad-kit v1.2.0), at a
clean commit. The rules are ET-M4-1 in ``evals/M4-exit-tests.json`` as amended by
``evals/M4-amendment-1.json``; both are pinned by sha256 here and refused if changed.

``verify`` reads the exports in place and writes nothing. For each export it requires COMPLETE to
hold the sha256 of MANIFEST.json, and that to equal the hash the owner was given. It applies the
amended schema check: ``contract.schema_version`` exactly "1.0.0", with no conflicting declaration.
It checks every listed file's path, size and sha256, and that nothing unlisted is present. For the
two episode exports, it requires each episode.json's schema_version to be exactly "1.0.0".
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
}
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
MARKERS = ("MANIFEST.json", "COMPLETE")


class ImportStopError(ValueError):
    """A frozen stop condition: report it, copy nothing more."""


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
    manifest = json.loads(raw)
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
    if export.kind == "episodes":
        for entry in manifest["entries"]:
            episode = json.loads((_safe(root, entry["path"]) / "episode.json").read_bytes())
            if episode.get("schema_version") != SCHEMA_VERSION:
                raise ImportStopError(
                    f"{export_id}: {entry['episode_id']} schema_version "
                    f"{episode.get('schema_version')!r}, not '1.0.0'"
                )
    elif export.kind != "ulogs":
        raise ImportStopError(f"{export_id}: unknown export kind {export.kind!r}")
    return export


def verify_all(source: Path, *, hash_files: bool = True) -> list[Export]:
    exports = [
        verify_export(source / export_id, export_id, expected, hash_files=hash_files)
        for export_id, expected in EXPORTS.items()
    ]
    by_id = {export.export_id: export for export in exports}
    for episodes, ulogs in ULOG_FOR.items():
        a = {e["episode_id"] for e in by_id[episodes].manifest["entries"]}
        b = {e["episode_id"] for e in by_id[ulogs].manifest["entries"]}
        if a != b:
            raise ImportStopError(f"{episodes} and {ulogs} list different episodes")
    return exports


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
    if sha256_bytes((incoming / "MANIFEST.json").read_bytes()) != EXPORTS[export.export_id]:
        raise ImportStopError(f"{export.export_id}: the copied MANIFEST.json differs")
    _make_read_only(incoming)
    os.rename(incoming, target)
    return target


def import_record(export: Export, amendment_sha256: str) -> dict[str, Any]:
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
        "files": len(manifest["files"]),
        "bytes": sum(item["bytes"] for item in manifest["files"]),
        "rights": manifest["rights"],
        "read_only": True,
        "rules": {"evals/M4-amendment-1.json": amendment_sha256},
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
        out[export_id] = Export(export_id, root, raw, json.loads(raw))
    return out


def data_checks(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """ET-M4-2's four data checks, over the union of both episode exports.

    Each item has the manifest ``entry``, its ``export_id`` and the ``episode`` (episode.json).
    """
    problems: list[str] = []
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
            problems.append(f"{entry['episode_id']}: episode.json names {episode['episode_id']}")
        if episode["split"]["scene_group_id"] != family:
            problems.append(f"{entry['episode_id']}: scene_group_id is not the family id")
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
    problems += [
        f"session {s} in partitions {sorted(p)}" for s, p in sessions.items() if len(p) > 1
    ]
    designated = {p for parts in partitions.values() for p in parts}
    if designated != M4_PARTITIONS:
        problems.append(
            f"the manifests designate partitions {sorted(designated)}, not train/heldout"
        )
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
                validation["invalid"].append({"episode_id": entry["episode_id"], "error": str(exc)})
                continue
            if result["status"] == "contract_valid":
                validation["contract_valid"] += 1
            paths.append(path)
            episodes.append(
                {"export_id": export_id, "entry": entry, "episode": json.loads(path.read_bytes())}
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
                "error": str(exc),
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
        "passed": validation["all_contract_valid"]
        and checks["passed"]
        and all(a.get("status") != "failed" for a in contract_audit.values()),
    }


def _cmd_verify(args: argparse.Namespace) -> int:
    check_frozen()
    exports = verify_all(args.source)
    for export in exports:
        print(
            json.dumps(
                {
                    "export_id": export.export_id,
                    "kind": export.kind,
                    "entries": len(export.manifest["entries"]),
                    "files": len(export.manifest["files"]),
                    "manifest_sha256": EXPORTS[export.export_id],
                    "contract": export.manifest["contract"],
                }
            )
        )
    return 0


def _cmd_import(args: argparse.Namespace) -> int:
    from ironclad.core.ledger import append_record

    frozen = check_frozen()
    repo = Path(".")
    exports = verify_all(args.source)
    for export in exports:
        target = copy_export(export, repo)
        record = append_record(
            repo / "ledgers/imports.jsonl",
            import_record(export, frozen["evals/M4-amendment-1.json"]),
        )
        print(f"imported {export.export_id} -> {target} ({record['record_id']})")
    append_record(repo / "ledgers/licenses.jsonl", license_record())
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    from ..sim.runlog import ledgered_run, require_code_root

    require_code_root()
    frozen = check_frozen()
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
