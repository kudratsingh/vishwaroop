"""Independent pick-and-place outcome, computed from recorded simulator state (rubric m0-place-1).

Units: positions in metres in the world frame, with the table top at height 0. ``grasped`` is the
simulator's own report of whether the object is held.

This module decides success from state alone. It imports only the standard library and takes
nothing from a policy, a reward or a learned model; a test enforces that. An episode that cannot be
decided gets ``success=None`` and the label ``insufficient_evidence``; it is never counted as a
failure.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from itertools import pairwise
from pathlib import Path
from typing import Any

OBJECT_STREAM = "object_position"
TARGET_STREAM = "target_position"
GRASPED_STREAM = "object_grasped"

Position = tuple[float, float, float]


@dataclass(frozen=True)
class PlaceRubric:
    """Frozen success numbers. All lengths are in metres; ``dwell_steps`` is in control steps."""

    rubric_version: str
    target_radius_m: float
    rest_height_m: float
    rest_height_tolerance_m: float
    min_lift_above_rest_m: float
    max_step_motion_m: float
    dwell_steps: int

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> PlaceRubric:
        """Build from a frozen specification; raises ``ValueError`` on missing or extra keys."""
        expected = {f.name for f in fields(cls)}
        if set(raw) != expected:
            raise ValueError(f"rubric keys differ from {sorted(expected)}: {sorted(raw)}")
        return cls(**raw)


@dataclass(frozen=True)
class StateSample:
    """Simulator state after one step. A ``None`` field means that sample was invalid or missing."""

    step: int
    object_position_m: Position | None
    target_position_m: Position | None
    grasped: bool | None


@dataclass(frozen=True)
class Outcome:
    """The decision. ``label`` is ``success``, a failure mode, or ``insufficient_evidence``."""

    success: bool | None
    label: str
    reason: str
    rubric_version: str
    samples: int


def assess(samples: Sequence[StateSample], rubric: PlaceRubric) -> Outcome:
    """Apply the rubric to an episode's samples, in step order.

    The checks run in a fixed order and the first failure gives the label, so each failed episode
    has exactly one label: never_lifted, still_grasped, not_on_table, outside_target, not_settled.
    """

    def decide(success: bool | None, label: str, reason: str) -> Outcome:
        return Outcome(success, label, reason, rubric.rubric_version, len(samples))

    if len(samples) < rubric.dwell_steps:
        return decide(
            None,
            "insufficient_evidence",
            f"{len(samples)} samples; the rubric needs at least {rubric.dwell_steps}",
        )
    complete: list[tuple[Position, Position, bool]] = []
    for sample in samples:
        if (
            sample.object_position_m is None
            or sample.target_position_m is None
            or sample.grasped is None
        ):
            return decide(None, "insufficient_evidence", f"invalid sample at step {sample.step}")
        complete.append((sample.object_position_m, sample.target_position_m, sample.grasped))

    highest = max(position[2] for position, _, _ in complete)
    if highest - rubric.rest_height_m < rubric.min_lift_above_rest_m:
        return decide(False, "never_lifted", f"highest object height was {highest:.6f} m")

    window = complete[-rubric.dwell_steps :]
    if any(grasped for _, _, grasped in window):
        return decide(False, "still_grasped", "object reported as grasped during the final dwell")
    for position, _, _ in window:
        if abs(position[2] - rubric.rest_height_m) > rubric.rest_height_tolerance_m:
            return decide(False, "not_on_table", f"object height was {position[2]:.6f} m")
    for position, target, _ in window:
        distance = math.hypot(position[0] - target[0], position[1] - target[1])
        if distance > rubric.target_radius_m:
            return decide(False, "outside_target", f"object was {distance:.6f} m from the target")
    for (before, _, _), (after, _, _) in pairwise(window):
        motion = math.dist(before, after)
        if motion > rubric.max_step_motion_m:
            return decide(False, "not_settled", f"object moved {motion:.6f} m in one step")
    return decide(True, "success", "lifted, released, on the table, in the target, and settled")


def _stream_value(packets: Sequence[Mapping[str, Any]], name: str) -> list[float] | None:
    for packet in packets:
        if packet["stream"] == name:
            value = packet["value"] if packet["valid"] else None
            return None if value is None else [float(v) for v in value]
    return None


def _position(value: list[float] | None) -> Position | None:
    if value is None or len(value) != 3:
        return None
    return (value[0], value[1], value[2])


def _sample(step: int, packets: Sequence[Mapping[str, Any]]) -> StateSample:
    grasped = _stream_value(packets, GRASPED_STREAM)
    return StateSample(
        step=step,
        object_position_m=_position(_stream_value(packets, OBJECT_STREAM)),
        target_position_m=_position(_stream_value(packets, TARGET_STREAM)),
        grasped=None if grasped is None or len(grasped) != 1 else grasped[0] >= 0.5,
    )


def samples_from_records(records: Sequence[Mapping[str, Any]]) -> list[StateSample]:
    """Turn transition records into samples: the first observation, then each next observation."""
    if not records:
        return []
    samples = [_sample(0, records[0]["observations"])]
    samples.extend(_sample(i + 1, r["next_observations"]) for i, r in enumerate(records))
    return samples


def samples_from_episode(episode_dir: str | Path) -> list[StateSample]:
    """Read samples from an exported episode directory. Reads files only; verifies no hashes."""
    base = Path(episode_dir)
    manifest = json.loads((base / "episode.json").read_text(encoding="utf-8"))
    name = Path(manifest["data"]["transitions_artifact"]["path"]).name
    lines = (base / name).read_text(encoding="utf-8").splitlines()
    return samples_from_records([json.loads(line) for line in lines])


class PickPlaceJudge:
    """Implements ``interfaces.SuccessJudge`` from an episode's recorded state alone."""

    def __init__(self, rubric: PlaceRubric) -> None:
        self._rubric = rubric

    def judge(self, episode_dir: str) -> tuple[bool | None, str]:
        """Return (success, evidence note); ``None`` means the evidence does not decide."""
        outcome = assess(samples_from_episode(episode_dir), self._rubric)
        return outcome.success, f"{outcome.label}: {outcome.reason}"
