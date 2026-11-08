"""FABRICATED LeRobot v3.0 datasets for WO-023's tests. Not recordings: no arm, camera or policy.

The MP4 shards are stand-in bytes, not video; the importer hashes and links them and never decodes
them. Layout and column names follow LeRobot v3.0 (``meta/info.json``, ``meta/episodes``,
``data/chunk-000/file-000.parquet``, ``videos/<key>/chunk-000/file-000.mp4``).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

JOINTS = [
    "shoulder_pan.pos",
    "shoulder_lift.pos",
    "elbow_flex.pos",
    "wrist_flex.pos",
    "wrist_roll.pos",
    "gripper.pos",
]
CAMERAS = ("front", "top")
FPS = 30
LENGTHS = (5, 4, 6)
SESSIONS = {"0": "fixture-session-a", "1": "fixture-session-a", "2": "fixture-session-b"}
POSE_FEATURE = "observation.object_pose"


def info() -> dict[str, Any]:
    vector = {"dtype": "float32", "shape": [len(JOINTS)], "names": list(JOINTS), "fps": FPS}
    features: dict[str, Any] = {
        "action": copy.deepcopy(vector),
        "observation.state": copy.deepcopy(vector),
        POSE_FEATURE: {"dtype": "float32", "shape": [3], "names": ["x", "y", "z"], "fps": FPS},
    }
    for cam in CAMERAS:
        features[f"observation.images.{cam}"] = {
            "dtype": "video",
            "shape": [48, 64, 3],
            "names": ["height", "width", "channels"],
            "info": {"video.fps": FPS, "video.codec": "av1", "video.height": 48},
        }
    for key, dtype in (
        ("timestamp", "float32"),
        ("frame_index", "int64"),
        ("episode_index", "int64"),
        ("index", "int64"),
        ("task_index", "int64"),
    ):
        features[key] = {"dtype": dtype, "shape": [1], "names": None, "fps": FPS}
    return {
        "codebase_version": "v3.0",
        "robot_type": "so101_follower",
        "total_episodes": len(LENGTHS),
        "total_frames": sum(LENGTHS),
        "fps": FPS,
        "data_path": "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet",
        "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4",
        "features": features,
    }


def frames(lengths: tuple[int, ...] = LENGTHS) -> list[dict[str, Any]]:
    rows = []
    index = 0
    for ep, length in enumerate(lengths):
        for f in range(length):
            value = [float(ep * 10 + f + j / 10) for j in range(len(JOINTS))]
            pose = [0.1 * f, 0.2, 0.0]
            if ep == 2 and f == 1:
                pose = [float("nan"), 0.2, 0.0]  # the tag was not seen in this frame
            rows.append(
                {
                    "observation.state": value,
                    "action": [v + 0.5 for v in value],
                    POSE_FEATURE: pose,
                    "timestamp": f / FPS,
                    "frame_index": f,
                    "episode_index": ep,
                    "index": index,
                    "task_index": 0,
                }
            )
            index += 1
    return rows


def episodes(lengths: tuple[int, ...] = LENGTHS) -> list[dict[str, Any]]:
    out = []
    start = 0
    for ep, length in enumerate(lengths):
        row: dict[str, Any] = {
            "episode_index": ep,
            "data/chunk_index": 0,
            "data/file_index": 0,
            "dataset_from_index": start,
            "dataset_to_index": start + length,
            "tasks": ["put the cube in the bowl"],
            "length": length,
        }
        t0 = start / FPS
        for cam in CAMERAS:
            key = f"videos/observation.images.{cam}"
            row[f"{key}/chunk_index"] = 0
            row[f"{key}/file_index"] = 0
            row[f"{key}/from_timestamp"] = t0
            row[f"{key}/to_timestamp"] = t0 + length / FPS
        out.append(row)
        start += length
    return out


def write_dataset(
    root: Path,
    *,
    info_doc: dict[str, Any] | None = None,
    frame_rows: list[dict[str, Any]] | None = None,
    episode_rows: list[dict[str, Any]] | None = None,
) -> Path:
    """Write a fabricated LeRobot v3.0 dataset at ``root`` and return it."""
    (root / "meta" / "episodes" / "chunk-000").mkdir(parents=True)
    (root / "data" / "chunk-000").mkdir(parents=True)
    (root / "meta" / "info.json").write_text(json.dumps(info_doc or info(), indent=2))
    pq.write_table(
        pa.Table.from_pylist(episode_rows or episodes()),
        root / "meta" / "episodes" / "chunk-000" / "file-000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist([{"task_index": 0, "task": "put the cube in the bowl"}]),
        root / "meta" / "tasks.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist(frame_rows or frames()),
        root / "data" / "chunk-000" / "file-000.parquet",
    )
    for cam in CAMERAS:
        video = root / "videos" / f"observation.images.{cam}" / "chunk-000"
        video.mkdir(parents=True)
        (video / "file-000.mp4").write_bytes(f"FABRICATED stand-in for {cam} video".encode())
    return root


def declaration(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "format": "lerobot-v3.0",
        "dataset_root": "dataset",
        "units": dict.fromkeys(JOINTS[:-1], "normalized_m100_100")
        | {JOINTS[-1]: "normalized_0_100"},
        "calibration": "calibration.json",
        "rubric": "rubric.json",
        "task_id": "fixture-pick-place",
        "task_version": "1",
        "protocol_version": "fixture",
        "recorded_at": "2026-11-08T12:00:00+00:00",
        "robot_id": "fixture-follower",
        "purpose": "demonstration",
        "sessions": dict(SESSIONS),
        "policy": {"origin": "teleop"},
        "labels": None,
        "object_pose": {"feature": POSE_FEATURE, "frame_id": "top_camera_tag", "units": ["m"] * 3},
    }
    base.update(overrides)
    return base


def split(**sessions: dict[str, str]) -> dict[str, Any]:
    entries = {
        "fixture-session-a": {"partition": "train", "scene_group_id": "fixture-bench-a"},
        "fixture-session-b": {"partition": "dev", "scene_group_id": "fixture-bench-b"},
    }
    entries.update(sessions)
    return {"split_id": "fixture-split", "sessions": entries}


def extras(directory: Path, *, labels: dict[str, Any] | None = None) -> list[Path]:
    """Calibration, rubric and optional labels files, as the owner would pass to ``seal``."""
    directory.mkdir(parents=True, exist_ok=True)
    calibration = directory / "calibration.json"
    calibration.write_text(json.dumps({"FABRICATED": "calibration"}))
    rubric = directory / "rubric.json"
    rubric.write_text(json.dumps({"FABRICATED": "rubric"}))
    files = [calibration, rubric]
    if labels is not None:
        path = directory / "labels.json"
        path.write_text(json.dumps(labels))
        files.append(path)
    return files
