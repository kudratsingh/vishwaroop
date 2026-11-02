"""Load the train partition of the M0 dataset for the compute pilot, with no simulator or torch.

Only ``train`` episodes are read, and a dev seed is refused even if a manifest calls it train.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

STATE_STREAMS = ("joint_position", "object_position", "target_position", "object_grasped")
STATE_SIZE = 13
ACTION_SIZE = 6
FIRST_DEV_SEED = 8000  # evals/M0-protocol.md: blocks 8 and 9 are dev
HOLDOUT_EVERY = 10  # a seed is in the pilot's own holdout, within train, when divisible by this


@dataclass(frozen=True)
class EpisodeArrays:
    """One episode: ``len(states) == len(actions) + 1``."""

    seed: int
    states: list[list[float]]
    actions: list[list[float]]
    family: str = ""


def state_vector(packets: Sequence[Mapping[str, Any]]) -> list[float]:
    """The 13 state values, in a fixed order, from one record's observation packets."""
    values = {packet["stream"]: packet["value"] for packet in packets}
    state: list[float] = []
    for stream in STATE_STREAMS:
        value = values.get(stream)
        if value is None:
            raise ValueError(f"stream {stream} is missing or invalid")
        state.extend(float(item) for item in value)
    if len(state) != STATE_SIZE:
        raise ValueError(f"expected {STATE_SIZE} state values, found {len(state)}")
    return state


def read_episode(path: Path, expected_sha256: str, seed: int) -> EpisodeArrays:
    """Read one episode's transitions, checking them against the manifest's hash."""
    raw = (path / "transitions.jsonl").read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise ValueError(f"{path.name}: transitions hash {actual} is not the manifest's")
    records = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    if not records:
        raise ValueError(f"{path.name}: no transitions")
    states = [state_vector(records[0]["observations"])]
    actions: list[list[float]] = []
    for record in records:
        requested = record["action"]["requested"]
        if len(requested) != ACTION_SIZE:
            raise ValueError(f"{path.name}: expected {ACTION_SIZE} action values")
        actions.append([float(value) for value in requested])
        states.append(state_vector(record["next_observations"]))
    return EpisodeArrays(seed, states, actions)


def load_train(manifest_path: Path, root: Path) -> list[EpisodeArrays]:
    """Every ``train`` episode of a dataset manifest. Never returns a dev episode."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sequences: list[EpisodeArrays] = []
    for entry in manifest["episodes"]:
        if entry["partition"] != "train":
            continue
        if entry["seed"] >= FIRST_DEV_SEED:
            raise ValueError(f"{entry['episode_id']}: seed {entry['seed']} is a dev seed")
        episode = read_episode(root / entry["path"], entry["transitions_sha256"], entry["seed"])
        sequences.append(replace(episode, family=entry.get("family", "")))
    if not sequences:
        raise ValueError("the manifest has no train episodes")
    return sequences


def split_holdout(
    sequences: Sequence[EpisodeArrays],
) -> tuple[list[EpisodeArrays], list[EpisodeArrays]]:
    """Split by seed, within train: this is a sanity check for the pilot, not the dev set."""
    fit = [item for item in sequences if item.seed % HOLDOUT_EVERY != 0]
    holdout = [item for item in sequences if item.seed % HOLDOUT_EVERY == 0]
    return fit, holdout


def split_family(
    sequences: Sequence[EpisodeArrays], family: str
) -> tuple[list[EpisodeArrays], list[EpisodeArrays]]:
    """Hold out one whole family, within train, the way dev holds out families from train."""
    fit = [item for item in sequences if item.family != family]
    holdout = [item for item in sequences if item.family == family]
    if not fit or not holdout:
        raise ValueError(f"family {family} does not split this data in two")
    return fit, holdout
