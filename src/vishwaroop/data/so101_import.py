"""WO-023: real SO-101 recordings in LeRobot's dataset format v3.0 → contract-v1 episodes.

    python -m vishwaroop.data.so101_import seal --dataset <lerobot dir> --declaration <json> \
        --export-id <id> --out <export root>          # owner tool: seal a finished recording
    python -m vishwaroop.data.so101_import verify --export <export dir>
    python -m vishwaroop.data.so101_import import --export <export dir> --split <split json>

The export shape is ``docs/SO101_EXPORT.md``. ``verify`` reads an export in place and writes
nothing: ``importer.verify_export`` (``COMPLETE``, ``MANIFEST.json``, every file's sha256), then the
``identities.so101`` declaration and the LeRobot tables. ``import`` repeats that, copies the export
write-once and read-only into ``data/imports/<export_id>/``, converts every episode into
``data/derived/so101-real/<export_id>/<episode_id>/`` (built in a hidden sibling, validated with the
contract's validator and split audit, then renamed into place), and appends one
``ledgers/imports.jsonl`` line.

What the conversion claims and does not:
- ``environment_kind: real``, ``simulator: null``. Joint state and the recorded ``action`` (as the
  ``requested`` stage only; LeRobot records no filtered, transmitted or applied stage) carry the
  units the producer declared. Nothing is assumed: undeclared units are refused.
- Times are LeRobot's nominal frame times (``timestamp``, ``frame_index / fps``) in clock domain
  ``lerobot_nominal_frame_time``. True capture latency is not recorded and is not invented.
- Camera frames stay in the recorded MP4 shards, never re-encoded. Each frame's artifact is the
  shard, hard-linked into the episode directory; ``lerobot-adapter.json`` (the configuration's
  ``preprocessing_artifact``) gives each camera's shard and ``from_timestamp``. Frames are not
  decoded here, so frame content is checked only through the shard's sha256.
- ``outcome.success`` is set only from a declared label file; otherwise it is ``null``.

Exit codes: 0 done, 2 refused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import stat
import sys
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from ironclad.contracts.v1 import audit_splits, validate
from ironclad.core.artifacts import sha256_file
from ironclad.core.ledger import append_record

from ..importer import COMPLETE_MARKER, MANIFEST_NAME, ExportImportError, verify_export

CODEBASE_VERSION = "v3.0"
DECLARATION_KEY = "so101"
DECLARATION_FORMAT = "lerobot-v3.0"
EMBODIMENT_ID = "so101_real"
CLOCK_DOMAIN = "lerobot_nominal_frame_time"
JOINT_FRAME = "so101_joint_coordinates"
STATE_KEY = "observation.state"
ACTION_KEY = "action"
IMAGE_PREFIX = "observation.images."
DERIVED_DIR = Path("data/derived/so101-real")
IMPORTS_DIR = Path("data/imports")
IMPORTS_LEDGER = Path("ledgers/imports.jsonl")
AUDIT_GROUPS = ("session_group_id", "scene_group_id", "policy_run_group_id")
# Representation bounds of each declared unit, recorded in action_spec. They are not the arm's
# physical joint limits.
UNIT_BOUNDS: dict[str, tuple[float, float]] = {
    "deg": (-180.0, 180.0),
    "rad": (-math.pi, math.pi),
    "normalized_m100_100": (-100.0, 100.0),
    "normalized_0_100": (0.0, 100.0),
}
PARTITIONS = ("train", "dev", "regression")
PURPOSES = ("demonstration", "evaluation")
ASSESSMENT_METHODS = ("physical_sensor_and_review", "blinded_review")
# A frame's timestamp may differ from frame_index / fps by at most half a frame.
MAX_TIMESTAMP_SLIP_FRAMES = 0.5


class So101ImportError(ExportImportError):
    """An SO-101 export, its declaration, its tables or a split that this importer refuses."""


# ------------------------------------------------------------------ declaration and split


@dataclass(frozen=True)
class Policy:
    """The policy that produced the episodes: ``teleop``, or ``trained`` with its identities."""

    origin: str
    checkpoint_id: str | None = None
    training_run_id: str | None = None
    family_id: str | None = None
    weights: str | None = None
    config: str | None = None
    policy_run_group_id: str | None = None


@dataclass(frozen=True)
class Labels:
    """A declared label file (export-relative) and how its labels were assessed."""

    file: str
    method: str


@dataclass(frozen=True)
class ObjectPose:
    """The optional object-pose feature, a ``reference_only`` stream never fed to a policy."""

    feature: str
    frame_id: str
    units: tuple[str, ...]


@dataclass(frozen=True)
class Declaration:
    """``MANIFEST.json``'s ``identities.so101`` block (``docs/SO101_EXPORT.md``)."""

    dataset_root: str
    units: dict[str, str]
    calibration: str
    rubric: str
    task_id: str
    task_version: str
    protocol_version: str
    recorded_at: str
    robot_id: str
    purpose: str
    sessions: dict[int, str]
    policy: Policy
    labels: Labels | None
    object_pose: ObjectPose | None

    def export_files(self) -> list[str]:
        """Export-relative files the declaration names outside the dataset root."""
        files = [self.calibration, self.rubric]
        if self.labels is not None:
            files.append(self.labels.file)
        if self.policy.weights is not None:
            files.append(self.policy.weights)
        if self.policy.config is not None:
            files.append(self.policy.config)
        return files


def _str(block: dict[str, Any], key: str, where: str) -> str:
    value = block.get(key)
    if not isinstance(value, str) or not value:
        raise So101ImportError(f"{where}.{key} must be a non-empty string")
    return value


def _rel(value: str, where: str) -> str:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise So101ImportError(f"{where} must be a relative path inside the export: {value!r}")
    return value


def parse_declaration(identities: dict[str, Any]) -> Declaration:
    """Read and check ``identities.so101``. Anything missing or unknown is refused."""
    block = identities.get(DECLARATION_KEY)
    if not isinstance(block, dict):
        raise So101ImportError(f"MANIFEST identities has no '{DECLARATION_KEY}' declaration")
    where = f"identities.{DECLARATION_KEY}"
    if block.get("format") != DECLARATION_FORMAT:
        raise So101ImportError(f"{where}.format must be {DECLARATION_FORMAT!r}")
    units = block.get("units")
    if not isinstance(units, dict) or not units:
        raise So101ImportError(f"{where}.units must declare a unit for every joint")
    for name, unit in units.items():
        if unit not in UNIT_BOUNDS:
            raise So101ImportError(
                f"{where}.units[{name!r}] is {unit!r}, not one of {sorted(UNIT_BOUNDS)}"
            )
    purpose = _str(block, "purpose", where)
    if purpose not in PURPOSES:
        raise So101ImportError(f"{where}.purpose must be one of {PURPOSES}")
    sessions_raw = block.get("sessions")
    if not isinstance(sessions_raw, dict) or not sessions_raw:
        raise So101ImportError(f"{where}.sessions must map every episode index to a session")
    sessions: dict[int, str] = {}
    for key, session in sessions_raw.items():
        if not str(key).isdigit() or not isinstance(session, str) or not session:
            raise So101ImportError(f"{where}.sessions has a bad entry {key!r}: {session!r}")
        sessions[int(key)] = session
    return Declaration(
        dataset_root=_rel(_str(block, "dataset_root", where), f"{where}.dataset_root"),
        units=dict(units),
        calibration=_rel(_str(block, "calibration", where), f"{where}.calibration"),
        rubric=_rel(_str(block, "rubric", where), f"{where}.rubric"),
        task_id=_str(block, "task_id", where),
        task_version=_str(block, "task_version", where),
        protocol_version=_str(block, "protocol_version", where),
        recorded_at=_str(block, "recorded_at", where),
        robot_id=_str(block, "robot_id", where),
        purpose=purpose,
        sessions=sessions,
        policy=_parse_policy(block.get("policy"), f"{where}.policy"),
        labels=_parse_labels(block.get("labels"), f"{where}.labels"),
        object_pose=_parse_object_pose(block.get("object_pose"), f"{where}.object_pose"),
    )


def _parse_policy(raw: Any, where: str) -> Policy:
    if not isinstance(raw, dict):
        raise So101ImportError(f"{where} must be an object with 'origin'")
    origin = raw.get("origin")
    if origin == "teleop":
        extra = sorted(k for k in raw if k != "origin")
        if extra:
            raise So101ImportError(f"{where}: a teleop policy carries no identities, got {extra}")
        return Policy(origin="teleop")
    if origin != "trained":
        raise So101ImportError(f"{where}.origin must be 'teleop' or 'trained', not {origin!r}")
    keys = ("checkpoint_id", "training_run_id", "family_id", "weights", "config")
    missing = [k for k in keys if not isinstance(raw.get(k), str) or not raw.get(k)]
    if missing:
        raise So101ImportError(f"{where}: a trained policy needs {missing}")
    group = raw.get("policy_run_group_id", raw["training_run_id"])
    if not isinstance(group, str) or not group:
        raise So101ImportError(f"{where}.policy_run_group_id must be a non-empty string")
    return Policy(
        origin="trained",
        checkpoint_id=raw["checkpoint_id"],
        training_run_id=raw["training_run_id"],
        family_id=raw["family_id"],
        weights=_rel(raw["weights"], f"{where}.weights"),
        config=_rel(raw["config"], f"{where}.config"),
        policy_run_group_id=group,
    )


def _parse_labels(raw: Any, where: str) -> Labels | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise So101ImportError(f"{where} must be null or an object")
    method = _str(raw, "method", where)
    if method not in ASSESSMENT_METHODS:
        raise So101ImportError(f"{where}.method must be one of {ASSESSMENT_METHODS}")
    return Labels(file=_rel(_str(raw, "file", where), f"{where}.file"), method=method)


def _parse_object_pose(raw: Any, where: str) -> ObjectPose | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise So101ImportError(f"{where} must be null or an object")
    units = raw.get("units")
    if not isinstance(units, list) or not units or not all(isinstance(u, str) for u in units):
        raise So101ImportError(f"{where}.units must list one unit per element")
    return ObjectPose(
        feature=_str(raw, "feature", where),
        frame_id=_str(raw, "frame_id", where),
        units=tuple(units),
    )


@dataclass(frozen=True)
class SessionSplit:
    """One session's declared partition and scene group."""

    partition: str
    scene_group_id: str


def load_split(path: Path) -> tuple[str, dict[str, SessionSplit]]:
    """Read a split file: ``{"split_id": ..., "sessions": {session: {partition, scene_group_id}}}``.

    ``sealed`` is refused: sealed suites stay outside agent reach (AGENTS.md sections 6.8, 13.3).
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise So101ImportError(f"split file unreadable: {exc}") from exc
    if not isinstance(raw, dict):
        raise So101ImportError("split file must be a JSON object")
    split_id = raw.get("split_id")
    sessions = raw.get("sessions")
    if not isinstance(split_id, str) or not split_id:
        raise So101ImportError("split file needs a non-empty split_id")
    if not isinstance(sessions, dict) or not sessions:
        raise So101ImportError("split file must declare its sessions")
    out: dict[str, SessionSplit] = {}
    for session, entry in sessions.items():
        if not isinstance(entry, dict):
            raise So101ImportError(f"split entry for {session!r} must be an object")
        partition = entry.get("partition")
        if partition == "sealed":
            raise So101ImportError(
                f"session {session!r} is declared sealed; sealed suites are never imported by an "
                "agent"
            )
        if partition not in PARTITIONS:
            raise So101ImportError(
                f"session {session!r} has partition {partition!r}, not one of {PARTITIONS}"
            )
        scene = entry.get("scene_group_id")
        if not isinstance(scene, str) or not scene:
            raise So101ImportError(f"session {session!r} needs a scene_group_id")
        out[session] = SessionSplit(partition=partition, scene_group_id=scene)
    return split_id, out


# ------------------------------------------------------------------ LeRobot tables


@dataclass(frozen=True)
class Camera:
    """One video-backed camera feature from ``meta/info.json``."""

    key: str
    name: str
    height: int
    width: int
    channels: int
    fps: float
    codec: str


@dataclass(frozen=True)
class Dataset:
    """The parts of a LeRobot v3.0 dataset this importer reads."""

    root: Path
    info: dict[str, Any]
    fps: float
    joint_names: tuple[str, ...]
    cameras: tuple[Camera, ...]
    episodes: tuple[dict[str, Any], ...]


def _info_path(root: Path) -> Path:
    return root / "meta" / "info.json"


def read_dataset(root: Path, declaration: Declaration) -> Dataset:
    """Read ``meta/info.json`` and ``meta/episodes``; check them against the declaration."""
    try:
        info = json.loads(_info_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise So101ImportError(f"meta/info.json unreadable: {exc}") from exc
    if info.get("codebase_version") != CODEBASE_VERSION:
        raise So101ImportError(
            f"codebase_version is {info.get('codebase_version')!r}; only {CODEBASE_VERSION} is read"
        )
    if info.get("storage_format", "parquet") != "parquet":
        raise So101ImportError("only Parquet-backed datasets are read (not Lance)")
    fps = info.get("fps")
    if not isinstance(fps, int | float) or isinstance(fps, bool) or fps <= 0:
        raise So101ImportError("meta/info.json fps must be a positive number")
    features = info.get("features")
    if not isinstance(features, dict):
        raise So101ImportError("meta/info.json has no features")
    joint_names = _vector_names(features, STATE_KEY)
    if _vector_names(features, ACTION_KEY) != joint_names:
        raise So101ImportError("action and observation.state must name the same joints in order")
    if set(declaration.units) != set(joint_names):
        raise So101ImportError(
            f"declared units cover {sorted(declaration.units)}, but the joints are "
            f"{list(joint_names)}"
        )
    if declaration.object_pose is not None:
        pose = features.get(declaration.object_pose.feature)
        if not isinstance(pose, dict) or pose.get("shape") != [len(declaration.object_pose.units)]:
            raise So101ImportError(
                f"object pose feature {declaration.object_pose.feature!r} is missing or its shape "
                "differs from its declared units"
            )
    cameras = tuple(_camera(key, feat) for key, feat in sorted(features.items()) if _is_video(feat))
    for key in features:
        if key.startswith(IMAGE_PREFIX) and not _is_video(features[key]):
            raise So101ImportError(f"{key} is stored as images, not video; only video is read")
    episodes = _read_table_dir(root / "meta" / "episodes")
    seen: set[int] = set()
    for row in episodes:
        index = row.get("episode_index")
        if not isinstance(index, int) or index in seen:
            raise So101ImportError(f"bad or duplicate episode_index {index!r}")
        seen.add(index)
        for key in row:
            if key.startswith("videos/") and key.split("/")[1] not in {c.key for c in cameras}:
                raise So101ImportError(f"episodes table names video {key!r} absent from info.json")
    return Dataset(root, info, float(fps), joint_names, cameras, tuple(episodes))


def _is_video(feature: Any) -> bool:
    return isinstance(feature, dict) and feature.get("dtype") == "video"


def _vector_names(features: dict[str, Any], key: str) -> tuple[str, ...]:
    feat = features.get(key)
    if not isinstance(feat, dict):
        raise So101ImportError(f"meta/info.json has no {key} feature")
    names = feat.get("names")
    shape = feat.get("shape")
    if not isinstance(names, list) or not names or shape != [len(names)]:
        raise So101ImportError(f"{key} needs one name per element and a matching shape")
    return tuple(str(n) for n in names)


def _camera(key: str, feature: dict[str, Any]) -> Camera:
    if not key.startswith(IMAGE_PREFIX):
        raise So101ImportError(f"video feature {key!r} is not an observation image")
    info = feature.get("info") or {}
    shape = feature.get("shape")
    if not isinstance(shape, list) or len(shape) != 3:
        raise So101ImportError(f"{key} shape must be [height, width, channels]")
    return Camera(
        key=key,
        name=key[len(IMAGE_PREFIX) :],
        height=int(shape[0]),
        width=int(shape[1]),
        channels=int(shape[2]),
        fps=float(info.get("video.fps", 0.0)),
        codec=str(info.get("video.codec", "unknown")),
    )


def _read_table_dir(directory: Path) -> list[dict[str, Any]]:
    files = sorted(directory.rglob("*.parquet"))
    if not files:
        raise So101ImportError(f"no Parquet files under {directory.name}")
    rows: list[dict[str, Any]] = []
    for path in files:
        rows.extend(pq.read_table(path).to_pylist())
    return rows


def _template(info: dict[str, Any], key: str, **fields: Any) -> str:
    template = info.get(key)
    if not isinstance(template, str):
        raise So101ImportError(f"meta/info.json has no {key}")
    return template.format(**fields)


def episode_frames(dataset: Dataset, episode: dict[str, Any]) -> list[dict[str, Any]]:
    """The episode's rows from its data shard, in frame order, after the frame checks."""
    rel = _template(
        dataset.info,
        "data_path",
        chunk_index=episode["data/chunk_index"],
        file_index=episode["data/file_index"],
    )
    table = pq.read_table(dataset.root / rel)
    start, stop = int(episode["dataset_from_index"]), int(episode["dataset_to_index"])
    rows = [r for r in table.to_pylist() if start <= int(r["index"]) < stop]
    rows.sort(key=lambda r: int(r["index"]))
    index = episode["episode_index"]
    if len(rows) != int(episode["length"]) or len(rows) != stop - start:
        raise So101ImportError(
            f"episode {index}: {len(rows)} rows in its shard, but length is {episode['length']}"
        )
    for expected, row in enumerate(rows):
        if int(row["episode_index"]) != index:
            raise So101ImportError(
                f"episode {index}: a row belongs to episode {row['episode_index']}"
            )
        if int(row["frame_index"]) != expected:
            raise So101ImportError(
                f"episode {index}: frame_index {row['frame_index']} where {expected} was expected"
            )
        slip = abs(float(row["timestamp"]) * dataset.fps - expected)
        if slip > MAX_TIMESTAMP_SLIP_FRAMES:
            raise So101ImportError(
                f"episode {index}: frame {expected}'s timestamp is {slip:.2f} frames off its index"
            )
        for key in (STATE_KEY, ACTION_KEY):
            value = row.get(key)
            if not isinstance(value, list) or len(value) != len(dataset.joint_names):
                raise So101ImportError(
                    f"episode {index} frame {expected}: {key} must have "
                    f"{len(dataset.joint_names)} values"
                )
    return rows


def _video_rel(dataset: Dataset, episode: dict[str, Any], camera: Camera) -> str:
    return _template(
        dataset.info,
        "video_path",
        video_key=camera.key,
        chunk_index=episode[f"videos/{camera.key}/chunk_index"],
        file_index=episode[f"videos/{camera.key}/file_index"],
    )


# ------------------------------------------------------------------ conversion


def episode_id(export_id: str, index: int) -> str:
    """The contract episode id of LeRobot episode ``index`` in export ``export_id``."""
    return f"{export_id}-ep{index:06d}"


def _finite(values: Sequence[Any]) -> list[float] | None:
    out = [float(v) for v in values]
    return out if all(math.isfinite(v) for v in out) else None


def _place(src: Path, dst: Path) -> None:
    """Hard-link ``src`` to ``dst`` (no copy on the same volume); copy if linking is refused."""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def _artifact(base: Path, name: str) -> dict[str, str]:
    return {"path": name, "sha256": sha256_file(base / name)}


def convert_episode(
    *,
    export_id: str,
    export_root: Path,
    declaration: Declaration,
    dataset: Dataset,
    episode: dict[str, Any],
    split: SessionSplit,
    session: str,
    target: Path,
) -> Path:
    """Write one contract-v1 episode directory at ``target`` (which must not exist)."""
    index = int(episode["episode_index"])
    rows = episode_frames(dataset, episode)
    if target.exists():
        raise So101ImportError(f"{target.name} already exists; episodes are write-once")
    target.mkdir(parents=True)
    ep_id = episode_id(export_id, index)

    _place(export_root / declaration.calibration, target / "calibration.json")
    _place(export_root / declaration.rubric, target / "rubric.json")
    _place(_info_path(dataset.root), target / "lerobot-info.json")
    adapter: dict[str, Any] = {
        "adapter": "vishwaroop.data.so101_import",
        "lerobot_codebase_version": CODEBASE_VERSION,
        "export_id": export_id,
        "episode_index": index,
        "fps": dataset.fps,
        "clock_domain": CLOCK_DOMAIN,
        "frames_decoded": False,
        "cameras": {},
    }
    camera_files: dict[str, str] = {}
    for camera in dataset.cameras:
        name = f"video-{camera.name}.mp4"
        rel = _video_rel(dataset, episode, camera)
        _place(dataset.root / rel, target / name)
        camera_files[camera.name] = name
        adapter["cameras"][camera.name] = {
            "feature": camera.key,
            "shard": name,
            "shard_export_path": f"{declaration.dataset_root}/{rel}",
            "from_timestamp": float(episode[f"videos/{camera.key}/from_timestamp"]),
            "to_timestamp": float(episode[f"videos/{camera.key}/to_timestamp"]),
            "frame_time": "from_timestamp + transition t_ns / 1e9",
            "height": camera.height,
            "width": camera.width,
            "channels": camera.channels,
            "fps": camera.fps,
            "codec": camera.codec,
        }
    (target / "lerobot-adapter.json").write_bytes(_json_bytes(adapter))
    (target / "embodiment.json").write_bytes(
        _json_bytes(
            {
                "embodiment_id": EMBODIMENT_ID,
                "robot_type": dataset.info.get("robot_type"),
                "robot_id": declaration.robot_id,
                "joints": list(dataset.joint_names),
                "units": [declaration.units[j] for j in dataset.joint_names],
            }
        )
    )
    (target / "controller.json").write_bytes(
        _json_bytes(
            {
                "control": "LeRobot position targets at the recording fps",
                "fps": dataset.fps,
                "recorded_action_stage": "requested",
                "note": "filtered, transmitted and applied stages are not recorded by LeRobot",
            }
        )
    )

    policy = declaration.policy
    weights = config = None
    if policy.origin == "trained":
        assert policy.weights is not None and policy.config is not None
        _place(export_root / policy.weights, target / "policy-weights.bin")
        _place(export_root / policy.config, target / "policy-config.json")
        weights = _artifact(target, "policy-weights.bin")
        config = _artifact(target, "policy-config.json")

    outcome: dict[str, Any] = {
        "protocol_version": declaration.protocol_version,
        "rubric_version": declaration.task_version,
        "assessment_method": "unknown",
        "success": None,
        "terminated": False,
        "truncated": False,
        "reason": "episode ended by the operator; no assessment declared",
        "final_assessment_artifact": None,
        "training_reward_artifact": None,
        "paired_trial_id": None,
        "reviewer_ids": [],
    }
    if declaration.labels is not None:
        outcome.update(_label_outcome(export_root, declaration.labels, index, target))

    units = [declaration.units[j] for j in dataset.joint_names]
    lower = [UNIT_BOUNDS[u][0] for u in units]
    upper = [UNIT_BOUNDS[u][1] for u in units]
    streams: list[dict[str, Any]] = [
        {
            "name": "state",
            "kind": "state",
            "frame_id": JOINT_FRAME,
            "units": units,
            "shape": [len(units)],
            "dtype": "float32",
            "role": "input",
        }
    ]
    frames = [JOINT_FRAME]
    for camera in dataset.cameras:
        frame = f"camera_{camera.name}"
        frames.append(frame)
        streams.append(
            {
                "name": f"rgb_{camera.name}",
                "kind": "rgb",
                "frame_id": frame,
                "units": ["intensity_0_255"],
                "shape": [camera.height, camera.width, camera.channels],
                "dtype": "uint8",
                "role": "input",
            }
        )
    pose = declaration.object_pose
    if pose is not None:
        frames.append(pose.frame_id)
        streams.append(
            {
                "name": "object_pose",
                "kind": "reference",
                "frame_id": pose.frame_id,
                "units": list(pose.units),
                "shape": [len(pose.units)],
                "dtype": "float32",
                "role": "reference_only",
            }
        )

    manifest: dict[str, Any] = {
        "schema_version": "1.0.0",
        "episode_id": ep_id,
        "producer": "arm",
        "created_at": declaration.recorded_at,
        "environment_kind": "real",
        "purpose": declaration.purpose,
        "task": {
            "id": declaration.task_id,
            "version": declaration.task_version,
            "instruction": _instruction(episode),
            "criteria_artifact": _artifact(target, "rubric.json"),
        },
        "configuration": {
            "embodiment_id": EMBODIMENT_ID,
            "embodiment_artifact": _artifact(target, "embodiment.json"),
            "controller_artifact": _artifact(target, "controller.json"),
            "calibration_artifact": _artifact(target, "calibration.json"),
            "preprocessing_artifact": _artifact(target, "lerobot-adapter.json"),
            "stack_artifact": _artifact(target, "lerobot-info.json"),
        },
        "policy": {
            "origin": policy.origin,
            "checkpoint_id": policy.checkpoint_id,
            "training_run_id": policy.training_run_id,
            "family_id": policy.family_id,
            "weights_artifact": weights,
            "config_artifact": config,
        },
        "provenance": {
            "parent_episode_ids": [],
            "source_episode_artifacts": [],
            "generator_model_artifact": None,
        },
        "split": {
            "partition": split.partition,
            "suite_id": f"so101-real-{export_id}",
            "scene_group_id": split.scene_group_id,
            "session_group_id": session,
            "policy_run_group_id": policy.policy_run_group_id,
            "inherited_from_parent": False,
        },
        "timebase": {
            "unit": "nanoseconds",
            "clock_domain": CLOCK_DOMAIN,
            "alignment_artifact": None,
        },
        "frames": frames,
        "streams": streams,
        "action_spec": {
            "representation": "absolute_joint_position",
            "labels": list(dataset.joint_names),
            "units": units,
            "frame_id": JOINT_FRAME,
            "semantics": (
                "LeRobot's recorded action: the position target per joint, in the declared units. "
                "Bounds are the units' representation range, not the arm's joint limits."
            ),
            "lower": lower,
            "upper": upper,
        },
        "simulator": None,
        "validation": {"statuses": [], "evidence": []},
        "outcome": outcome,
        "notes": (
            "Real SO-101 recording imported from a LeRobot v3.0 export. Times are nominal frame "
            "times; camera frames stay in the hard-linked MP4 shards (lerobot-adapter.json) and "
            "were not decoded on import."
        ),
    }

    video_artifacts = {name: _artifact(target, f) for name, f in camera_files.items()}
    times = [round(float(r["timestamp"]) * 1e9) for r in rows]
    nominal_dt = round(1e9 / dataset.fps)
    lines: list[str] = []
    for step, row in enumerate(rows):
        t_ns = times[step]
        dt_ns = times[step + 1] - t_ns if step + 1 < len(rows) else nominal_dt
        if dt_ns <= 0:
            raise So101ImportError(f"episode {index}: timestamps do not increase at frame {step}")
        nxt = rows[step + 1] if step + 1 < len(rows) else None
        record = {
            "schema_version": "1.0.0",
            "episode_id": ep_id,
            "step": step,
            "t_ns": t_ns,
            "dt_ns": dt_ns,
            "observations": _observations(row, t_ns, dataset, pose, video_artifacts),
            "next_observations": _observations(nxt, t_ns + dt_ns, dataset, pose, video_artifacts),
            "action": {
                "requested": [float(v) for v in row[ACTION_KEY]],
                "filtered": None,
                "transmitted": None,
                "applied": None,
                "decision_t_ns": t_ns,
                "sent_t_ns": None,
                "applied_t_ns": None,
                "valid_until_t_ns": t_ns + dt_ns,
            },
            "context": {
                "mode": "teleop" if policy.origin == "teleop" else "policy",
                "estimator_valid": True,
                "intervention": None,
            },
        }
        lines.append(json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False))
    (target / "transitions.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest["data"] = {
        "format": "jsonl",
        "record_count": len(lines),
        "transitions_artifact": _artifact(target, "transitions.jsonl"),
    }
    (target / "episode.json").write_bytes(_json_bytes(manifest))
    validate.validate_episode(target / "episode.json")
    return target


def _instruction(episode: dict[str, Any]) -> str:
    tasks = episode.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 1 or not isinstance(tasks[0], str):
        raise So101ImportError(
            f"episode {episode.get('episode_index')}: exactly one task string is required"
        )
    return tasks[0]


def _observations(
    row: dict[str, Any] | None,
    t_ns: int,
    dataset: Dataset,
    pose: ObjectPose | None,
    videos: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    """Observation records at ``t_ns``; every stream is invalid when ``row`` is None."""

    def obs(
        stream: str, value: list[float] | None, artifact: dict[str, str] | None
    ) -> dict[str, Any]:
        return {
            "stream": stream,
            "capture_t_ns": t_ns,
            "received_t_ns": t_ns,
            "valid": value is not None or artifact is not None,
            "value": value,
            "artifact": artifact,
        }

    out = [obs("state", _finite(row[STATE_KEY]) if row else None, None)]
    for camera in dataset.cameras:
        out.append(obs(f"rgb_{camera.name}", None, videos[camera.name] if row else None))
    if pose is not None:
        raw = row.get(pose.feature) if row else None
        out.append(obs("object_pose", _finite(raw) if isinstance(raw, list) else None, None))
    return out


def _label_outcome(root: Path, labels: Labels, index: int, target: Path) -> dict[str, Any]:
    try:
        table = json.loads((root / labels.file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise So101ImportError(f"label file unreadable: {exc}") from exc
    entry = table.get(str(index)) if isinstance(table, dict) else None
    if not isinstance(entry, dict):
        raise So101ImportError(f"label file has no entry for episode {index}")
    success = entry.get("success")
    reviewers = entry.get("reviewer_ids")
    if not isinstance(success, bool):
        raise So101ImportError(f"episode {index}: label success must be true or false")
    if not isinstance(reviewers, list) or not reviewers:
        raise So101ImportError(f"episode {index}: a label needs its reviewer_ids")
    if not (target / "labels.json").exists():
        _place(root / labels.file, target / "labels.json")
    return {
        "assessment_method": labels.method,
        "success": success,
        "terminated": bool(entry.get("terminated", True)),
        "truncated": bool(entry.get("truncated", False)),
        "reason": str(entry.get("reason", "labelled by review")),
        "final_assessment_artifact": _artifact(target, "labels.json"),
        "reviewer_ids": [str(r) for r in reviewers],
    }


# ------------------------------------------------------------------ commands


@dataclass(frozen=True)
class CheckedExport:
    """A verified export with its parsed declaration and dataset."""

    export_id: str
    producer: str
    root: Path
    files: dict[str, str]
    declaration: Declaration
    dataset: Dataset


def check_export(export_dir: Path) -> CheckedExport:
    """``verify_export``, then the declaration, the files it names and the LeRobot tables."""
    verified = verify_export(export_dir)
    if verified.producer != "arm":
        raise So101ImportError(f"producer is {verified.producer!r}; SO-101 exports come from 'arm'")
    declaration = parse_declaration(verified.identities)
    for rel in declaration.export_files():
        if rel not in verified.files:
            raise So101ImportError(f"{rel} is declared but not hashed in MANIFEST.json")
    root_prefix = declaration.dataset_root.rstrip("/") + "/"
    listed = [rel for rel in verified.files if rel.startswith(root_prefix)]
    present = [
        p.relative_to(verified.root).as_posix()
        for p in (verified.root / declaration.dataset_root).rglob("*")
        if p.is_file()
    ]
    unlisted = sorted(set(present) - set(listed))
    if unlisted:
        raise So101ImportError(f"dataset files not hashed in MANIFEST.json: {unlisted[:5]}")
    dataset = read_dataset(verified.root / declaration.dataset_root, declaration)
    indices = {int(e["episode_index"]) for e in dataset.episodes}
    if indices != set(declaration.sessions):
        raise So101ImportError(
            f"sessions are declared for episodes {sorted(declaration.sessions)}, "
            f"but the dataset holds {sorted(indices)}"
        )
    for episode in dataset.episodes:
        episode_frames(dataset, episode)
    return CheckedExport(
        verified.export_id, verified.producer, verified.root, verified.files, declaration, dataset
    )


def _copy_export(checked: CheckedExport, target: Path) -> None:
    """Copy the export write-once and read-only, re-hashing every copied file."""
    if target.exists():
        raise So101ImportError(f"{target} already exists; imports are write-once")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{checked.export_id}.incoming-", dir=target.parent))
    try:
        for rel, expected in checked.files.items():
            dest = tmp / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(checked.root / rel, dest)
            if sha256_file(dest) != expected:
                raise So101ImportError(f"copy of {rel} does not match its hash; import aborted")
        for name in (MANIFEST_NAME, COMPLETE_MARKER):
            shutil.copy2(checked.root / name, tmp / name)
        _read_only(tmp)
        os.rename(tmp, target)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def _read_only(path: Path) -> None:
    """Drop write permission on every file. Never the reverse: converted episodes hard-link the
    imported copy's files, so loosening a mode here would loosen the import too. Unlinking a
    read-only file needs only the directory's permission, so a failed build is still removable."""
    for item in path.rglob("*"):
        if item.is_file():
            item.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


def import_export(
    export_dir: Path, split_path: Path, repo_root: Path, *, actor: str = "agent"
) -> dict[str, Any]:
    """Check, copy, convert, validate and audit an export; append one imports-ledger line."""
    checked = check_export(export_dir)
    split_id, sessions = load_split(split_path)
    declaration = checked.declaration
    missing = sorted({s for s in declaration.sessions.values() if s not in sessions})
    if missing:
        raise So101ImportError(f"sessions {missing} are not declared in split {split_id}")
    precheck_groups(declaration, sessions)
    derived = repo_root / DERIVED_DIR / checked.export_id
    if derived.exists():
        raise So101ImportError(f"{derived} already exists; conversions are write-once")
    imported = repo_root / IMPORTS_DIR / checked.export_id
    _copy_export(checked, imported)
    try:
        record = _convert_all(checked, imported, derived, split_id, sessions, split_path)
    except BaseException as exc:
        # The read-only copy stays (nothing is deleted); the ledger accounts for it.
        append_record(
            repo_root / IMPORTS_LEDGER,
            {
                "kind": "so101-lerobot-v3",
                "export_id": checked.export_id,
                "target": (IMPORTS_DIR / checked.export_id).as_posix(),
                "status": "conversion_failed",
                "error": f"{type(exc).__name__}: {exc}",
                "actor": actor,
            },
        )
        raise
    record["actor"] = actor
    return append_record(repo_root / IMPORTS_LEDGER, record)


def precheck_groups(declaration: Declaration, sessions: dict[str, SessionSplit]) -> None:
    """Refuse, before anything is copied, a group that would span partitions.

    The same rule the contract's split audit applies after conversion (session, scene and
    policy-run groups, and the raw training run), checked here on the declaration alone.
    """
    seen: dict[tuple[str, str], set[str]] = {}
    run = declaration.policy
    for session in declaration.sessions.values():
        entry = sessions[session]
        keys = [("session_group_id", session), ("scene_group_id", entry.scene_group_id)]
        if run.policy_run_group_id is not None:
            keys.append(("policy_run_group_id", run.policy_run_group_id))
        if run.training_run_id is not None:
            keys.append(("training_run_id", run.training_run_id))
        for key in keys:
            seen.setdefault(key, set()).add(entry.partition)
    for key, partitions in sorted(seen.items()):
        if len(partitions) > 1:
            raise So101ImportError(f"group leakage: {key}: {sorted(partitions)}")


def _convert_all(
    checked: CheckedExport,
    imported: Path,
    derived: Path,
    split_id: str,
    sessions: dict[str, SessionSplit],
    split_path: Path,
) -> dict[str, Any]:
    """Convert every episode from the imported copy, validate, audit, and place it."""
    declaration = checked.declaration
    copy = check_export(imported)

    derived.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{checked.export_id}.incoming-", dir=derived.parent))
    try:
        paths = []
        for episode in copy.dataset.episodes:
            index = int(episode["episode_index"])
            session = declaration.sessions[index]
            ep_dir = convert_episode(
                export_id=copy.export_id,
                export_root=copy.root,
                declaration=declaration,
                dataset=copy.dataset,
                episode=episode,
                split=sessions[session],
                session=session,
                target=tmp / episode_id(copy.export_id, index),
            )
            paths.append(ep_dir / "episode.json")
        audit = audit_splits.audit(paths, AUDIT_GROUPS)
        _read_only(tmp)
        os.rename(tmp, derived)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    partitions: dict[str, int] = {}
    for session in declaration.sessions.values():
        part = sessions[session].partition
        partitions[part] = partitions.get(part, 0) + 1
    record = {
        "kind": "so101-lerobot-v3",
        "export_id": checked.export_id,
        "producer": checked.producer,
        "manifest_sha256": sha256_file(imported / MANIFEST_NAME),
        "files": len(checked.files),
        "bytes": sum((imported / rel).stat().st_size for rel in checked.files),
        "target": (IMPORTS_DIR / checked.export_id).as_posix(),
        "derived": (DERIVED_DIR / checked.export_id).as_posix(),
        "episodes": len(paths),
        "episodes_by_partition": partitions,
        "split_id": split_id,
        "split_sha256": _sha256_bytes(split_path.read_bytes()),
        "policy_origin": declaration.policy.origin,
        "contract": {"name": "ironclad contracts v1", "schema_version": "1.0.0"},
        "audit": audit,
        "frames_decoded": False,
        "read_only": True,
    }
    return record


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def seal(
    dataset_dir: Path,
    declaration_path: Path,
    extra_files: Iterable[Path],
    export_id: str,
    out_root: Path,
) -> Path:
    """Owner tool: copy a finished LeRobot dataset and its declared files into a sealed export.

    Writes ``<out_root>/<export_id>/`` with ``dataset/``, the extra files by name, then
    ``MANIFEST.json``, and ``COMPLETE`` (holding the manifest's sha256) last. The dataset itself is
    only read. The declaration's ``dataset_root`` must be ``dataset``.
    """
    if not export_id or "/" in export_id or export_id.startswith("."):
        raise So101ImportError("export_id must be a plain name")
    try:
        block = json.loads(declaration_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise So101ImportError(f"declaration unreadable: {exc}") from exc
    declaration = parse_declaration({DECLARATION_KEY: block})
    if declaration.dataset_root != "dataset":
        raise So101ImportError("a sealed export keeps its dataset under 'dataset'")
    read_dataset(dataset_dir, declaration)
    target = out_root / export_id
    if target.exists():
        raise So101ImportError(f"{target} already exists; exports are write-once")
    out_root.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{export_id}.sealing-", dir=out_root))
    try:
        shutil.copytree(dataset_dir, tmp / "dataset")
        for extra in extra_files:
            if (tmp / extra.name).exists():
                raise So101ImportError(f"two extra files are named {extra.name}")
            shutil.copy2(extra, tmp / extra.name)
        files = {
            p.relative_to(tmp).as_posix(): sha256_file(p)
            for p in sorted(tmp.rglob("*"))
            if p.is_file()
        }
        manifest = {
            "export_id": export_id,
            "producer": "arm",
            "files": files,
            "identities": {DECLARATION_KEY: block},
        }
        manifest_bytes = _json_bytes(manifest)
        (tmp / MANIFEST_NAME).write_bytes(manifest_bytes)
        os.rename(tmp, target)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    (target / COMPLETE_MARKER).write_text(_sha256_bytes(manifest_bytes) + "\n", encoding="utf-8")
    check_export(target)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_seal = sub.add_parser("seal", help="owner tool: seal a finished LeRobot dataset")
    p_seal.add_argument("--dataset", type=Path, required=True)
    p_seal.add_argument("--declaration", type=Path, required=True)
    p_seal.add_argument("--extra", type=Path, action="append", default=[])
    p_seal.add_argument("--export-id", required=True)
    p_seal.add_argument("--out", type=Path, required=True)
    p_verify = sub.add_parser("verify", help="check an export in place; writes nothing")
    p_verify.add_argument("--export", type=Path, required=True)
    p_import = sub.add_parser("import", help="copy, convert, validate, audit, ledger")
    p_import.add_argument("--export", type=Path, required=True)
    p_import.add_argument("--split", type=Path, required=True)
    p_import.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        if args.command == "seal":
            target = seal(args.dataset, args.declaration, args.extra, args.export_id, args.out)
            print(json.dumps({"sealed": target.name}))
        elif args.command == "verify":
            checked = check_export(args.export)
            print(
                json.dumps(
                    {
                        "export_id": checked.export_id,
                        "episodes": len(checked.dataset.episodes),
                        "cameras": [c.name for c in checked.dataset.cameras],
                        "policy_origin": checked.declaration.policy.origin,
                    }
                )
            )
        else:
            record = import_export(args.export, args.split, args.repo_root)
            print(json.dumps(record, sort_keys=True))
        return 0
    except (ExportImportError, validate.ContractError) as exc:
        print(f"REFUSED: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
