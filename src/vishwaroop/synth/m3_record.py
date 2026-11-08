"""Record one M3 episode: seed checks, a write-once scene snapshot, then ``sim.export``'s recorder.

Before anything is simulated, a seed is checked by ``protocol.partition_for_seed`` (blocks 0 to 9
and 18 to 19 refused), ``check_family_seed`` (a family lies wholly in one partition) and
``check_not_held`` (ET-M3-1's held seeds). WO-022 also refuses block 10, which it does not use, and
any block other than the one its family is recorded on: the evaluation family on block 16, the
operator and nominal families on block 11.

The snapshot follows ``evals/M3-protocol.md`` section 3 (``snapshot.take_snapshot``). It is written
once per seed under ``<out>/snapshots/seed-<seed>``, through a partial sibling renamed into place
so an interruption never leaves half a snapshot; a later episode on the same scene (F1s's
nominal demo of an F2 scene) reads it back and refuses a scene whose fresh snapshot differs from
it in any field but the render's sha256, which is recorded. The episode is then recorded by
``sim.export.record_episode``, which saves the initial state right after ``reset`` and runs from
it; its saved initial state must equal the snapshot's, byte for byte, or the episode is not of the
snapshotted scene and the recording stops.

Needs numpy for the snapshot's render, and the robotics environment for real scenes.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..outcome.pickplace import PlaceRubric
from ..sim.baseline import PlanSettings, ScriptedPickPlace
from ..sim.export import EpisodeSpec, record_episode
from .protocol import (
    PROTOCOL_VERSION,
    ProtocolRefusalError,
    block_of,
    check_family_seed,
    check_not_held,
    family_partition,
    partition_for_seed,
    scene_group_id,
)
from .snapshot import RenderingEnv, SnapshotError, read_snapshot, take_snapshot, write_snapshot

EVAL_FAMILY = "m3-eval-missed-grasp"
LATERAL_FAMILY = "m3-synth-lateral-miss"
CLOSE_HIGH_FAMILY = "m3-synth-close-high"
# F1s: the nominal scripted demos of F2's scenes. A train family needs an m3-synth- id (protocol
# section 5 and protocol.family_partition); this is WO-022's choice of name.
NOMINAL_FAMILY = "m3-synth-nominal"
OPERATOR_FAMILIES = (LATERAL_FAMILY, CLOSE_HIGH_FAMILY)
UNUSED_BLOCK = 10  # reserved for a reopened ET-M3-1 (WO-022 Scope 1)
FAMILY_BLOCK = {EVAL_FAMILY: 16, LATERAL_FAMILY: 11, CLOSE_HIGH_FAMILY: 11, NOMINAL_FAMILY: 11}
SUITE_ID = "m3-et-m3-6"
EMBODIMENT = "maniskill3_so100"
INSTRUCTION = "Pick up the cube and place it on the table at the goal's xy position."
SNAPSHOTS = "snapshots"
NOTES = (
    "Simulated SO-100 under the scripted controller, not the owner's SO-101. "
    "No claim about any physical arm. ET-M3-6 (WO-022)."
)


class SceneMismatchError(ValueError):
    """A scene's fresh snapshot, or an episode's initial state, differs from its saved snapshot."""


@dataclass(frozen=True)
class Task:
    """The frozen M0 task: ``env_id``, ``version``, ``max_episode_steps``."""

    env_id: str
    version: str
    max_episode_steps: int

    @classmethod
    def from_frozen(cls, m0_exit_tests: dict[str, Any]) -> Task:
        task = m0_exit_tests["task"]
        return cls(task["env_id"], task["version"], int(task["max_episode_steps"]))


def check_seed(family: str, seed: int) -> None:
    """Every check WO-022 makes on a seed before it is simulated; ProtocolRefusalError if not."""
    block = block_of(seed)
    partition_for_seed(seed)
    check_family_seed(family, seed)
    check_not_held([seed])
    if block == UNUSED_BLOCK:
        raise ProtocolRefusalError(
            f"seed {seed} is in block 10, which WO-022 does not use (kept for ET-M3-1)"
        )
    if family not in FAMILY_BLOCK:
        raise ProtocolRefusalError(f"{family} is not a WO-022 family: {sorted(FAMILY_BLOCK)}")
    if block != FAMILY_BLOCK[family]:
        raise ProtocolRefusalError(
            f"{family} is recorded on block {FAMILY_BLOCK[family]}, and seed {seed} is in {block}"
        )


def episode_id(family: str, seed: int) -> str:
    return f"{family}-seed-{seed:06d}"


def episode_spec(
    family: str, seed: int, run_id: str, task: Task, rubric: PlaceRubric, notes: str
) -> EpisodeSpec:
    """The manifest declarations for one M3 episode, all from the frozen protocol."""
    check_seed(family, seed)
    partition = family_partition(family)
    return EpisodeSpec(
        episode_id=episode_id(family, seed),
        seed=seed,
        purpose="training" if partition == "train" else "evaluation",
        task_id=task.env_id,
        task_version=task.version,
        instruction=INSTRUCTION,
        embodiment_id=EMBODIMENT,
        rubric=rubric,
        protocol_version=PROTOCOL_VERSION,
        policy_family=family,
        partition=partition,
        suite_id=SUITE_ID,
        scene_group_id=scene_group_id(seed),
        session_group_id=run_id,
        max_steps=task.max_episode_steps,
        notes=notes,
    )


# A re-snapshot of a written scene must match it in every field but the render's sha256, which is
# recorded rather than required: the scene is its state, assets, configuration, stack and goal.
RENDER_FIELD = "initial_render"


def snapshot_dir(out: Path, seed: int) -> Path:
    return Path(out) / SNAPSHOTS / f"seed-{seed:06d}"


def check_initial_state(episode_dir: Path, seed: int, state_sha256: str, out: Path) -> None:
    """Stop unless an episode's saved initial state is its scene snapshot's, byte for byte.

    ``record`` makes this comparison right after recording; a resumed run makes it before gating an
    episode it finds on disk, so an episode of another scene is never kept by resuming.
    """
    directory = snapshot_dir(out, seed)
    try:
        saved = read_snapshot(directory)
    except (SnapshotError, OSError, ValueError, KeyError) as exc:
        raise SceneMismatchError(
            f"{Path(episode_dir).name}: no readable snapshot at {directory}: {exc}"
        ) from exc
    expected = saved.manifest["initial_state"]["sha256"]
    if state_sha256 != expected:
        raise SceneMismatchError(
            f"{Path(episode_dir).name}: initial state {state_sha256} is not the snapshot's "
            f"{expected}"
        )


def scene(env: RenderingEnv, seed: int, task: Task, out: Path) -> tuple[dict[str, Any], bool]:
    """Snapshot the scene, written once; if already written, refuse a fresh snapshot that differs.

    Returns the saved snapshot's manifest and whether the fresh render's sha256 equals the saved
    one (always true for a first snapshot).
    """
    directory = snapshot_dir(out, seed)
    fresh = take_snapshot(env, seed, task.env_id, task.version)
    if not directory.exists():
        # Written whole into a new sibling, then renamed into place, so an interruption leaves
        # either no snapshot or a complete one; a stale partial sibling is never read or reused.
        partial = directory.with_name(f".{directory.name}.partial-{uuid.uuid4().hex}")
        write_snapshot(fresh, partial)
        if directory.exists():
            raise SceneMismatchError(f"seed {seed}: {directory} appeared while it was written")
        partial.rename(directory)
        return fresh.manifest, True
    try:
        saved = read_snapshot(directory)
    except (SnapshotError, OSError, ValueError) as exc:
        raise SceneMismatchError(f"seed {seed}: the saved snapshot is unreadable: {exc}") from exc
    changed = sorted(
        key
        for key in set(saved.manifest) | set(fresh.manifest)
        if key != RENDER_FIELD and saved.manifest.get(key) != fresh.manifest.get(key)
    )
    if changed:
        raise SceneMismatchError(f"seed {seed}: the scene differs from its snapshot in {changed}")
    same_render = saved.manifest[RENDER_FIELD] == fresh.manifest[RENDER_FIELD]
    return saved.manifest, same_render


@dataclass(frozen=True)
class Recorded:
    """One recorded episode and what WO-022 lists about it."""

    path: Path
    episode_id: str
    seed: int
    family: str
    steps: int
    label: str
    planning_error: str | None
    snapshot_state_sha256: str
    render_matches_snapshot: bool | None

    def to_json(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "episode_id": self.episode_id,
            "seed": self.seed,
            "family": self.family,
            "steps": self.steps,
            "label": self.label,
            "planning_error": self.planning_error,
            "initial_state_sha256": self.snapshot_state_sha256,
            "render_matches_snapshot": self.render_matches_snapshot,
        }


def record(
    env: RenderingEnv,
    family: str,
    seed: int,
    settings: PlanSettings,
    run_id: str,
    out: Path,
    task: Task,
    rubric: PlaceRubric,
    note: str = "",
) -> Recorded:
    """Check the seed, snapshot the scene, record one scripted episode with ``noise_seed = seed``.

    ``note`` (for example an operator's drawn parameters) is added to the manifest's notes, as is
    ``planning_failed`` when the plan could not be made; such an episode is kept like any other.
    """
    check_seed(family, seed)
    manifest, same_render = scene(env, seed, task, out)
    spec = episode_spec(family, seed, run_id, task, rubric, f"{NOTES} {note}".strip())
    policy = ScriptedPickPlace(settings, noise_seed=seed)

    def closing_note() -> str | None:
        error = policy.planning_error
        return None if error is None else f"planning_failed: {error}"

    path = record_episode(env, policy, spec, Path(out) / spec.episode_id, closing_note)
    state_sha = hashlib.sha256((path / "initial-state.json").read_bytes()).hexdigest()
    if state_sha != manifest["initial_state"]["sha256"]:
        raise SceneMismatchError(
            f"{spec.episode_id}: initial state {state_sha} is not the snapshot's "
            f"{manifest['initial_state']['sha256']}"
        )
    written = json.loads((path / "episode.json").read_text(encoding="utf-8"))
    transitions = written["data"]["transitions_artifact"]["path"]
    steps = len((path / transitions).read_text(encoding="utf-8").splitlines())
    label = str(written["outcome"]["reason"]).split(":", 1)[0]
    return Recorded(
        path,
        spec.episode_id,
        seed,
        family,
        steps,
        label,
        policy.planning_error,
        state_sha,
        same_render,
    )
