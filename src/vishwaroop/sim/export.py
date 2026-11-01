"""Record a simulator episode and export it through the contract's write-once writer.

Time is simulated: ``t_ns`` starts at 0 and advances by ``env.dt_ns`` per step, in the clock domain
``simulation_steps``. Only what was commanded is recorded. The filtered, transmitted and applied
action stages stay ``null``, because the simulator does not report them to this adapter, and a
null is honest where a copied value would not be.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..outcome.pickplace import Outcome, PlaceRubric, assess, samples_from_records
from .contract import writer_module
from .env import Packet, SimEnv

Policy = Callable[[Packet, int], list[float] | None]
"""Maps (latest packet, step) to an action in ``action_spec`` units; ``None`` ends the episode."""

SCHEMA_VERSION = "1.0.0"
CLOCK_DOMAIN = "simulation_steps"
CONTEXT = {"mode": "scripted_sim", "estimator_valid": True, "intervention": None}


@dataclass(frozen=True)
class EpisodeSpec:
    """Everything an episode's manifest declares that the simulator does not supply."""

    episode_id: str
    seed: int
    purpose: str
    task_id: str
    task_version: str
    instruction: str
    embodiment_id: str
    rubric: PlaceRubric
    protocol_version: str
    policy_family: str
    partition: str
    suite_id: str
    scene_group_id: str
    session_group_id: str
    max_steps: int
    notes: str
    created_at: str | None = None


def _packets(env: SimEnv, packet: Packet, t_ns: int) -> list[dict[str, Any]]:
    """Build one observation list. A missing or non-finite stream is invalid, never faked."""
    records: list[dict[str, Any]] = []
    for stream in env.stream_specs:
        value = packet.get(stream.name)
        if value is not None and not all(math.isfinite(float(v)) for v in value):
            value = None
        records.append(
            {
                "stream": stream.name,
                "capture_t_ns": t_ns,
                "received_t_ns": t_ns,
                "valid": value is not None,
                "value": None if value is None else [float(v) for v in value],
                "artifact": None,
            }
        )
    return records


def _record(
    env: SimEnv,
    spec: EpisodeSpec,
    step: int,
    packet: Packet,
    action: list[float],
    next_packet: Packet,
) -> dict[str, Any]:
    t_ns = step * env.dt_ns
    return {
        "schema_version": SCHEMA_VERSION,
        "episode_id": spec.episode_id,
        "step": step,
        "t_ns": t_ns,
        "dt_ns": env.dt_ns,
        "observations": _packets(env, packet, t_ns),
        "next_observations": _packets(env, next_packet, t_ns + env.dt_ns),
        "action": {
            "requested": [float(v) for v in action],
            "filtered": None,
            "transmitted": None,
            "applied": None,
            "decision_t_ns": t_ns,
            "sent_t_ns": None,
            "applied_t_ns": None,
            "valid_until_t_ns": t_ns + env.dt_ns,
        },
        "context": dict(CONTEXT),
    }


def _ref(name: str) -> dict[str, str]:
    """An artifact reference whose hash the writer fills in."""
    return {"path": name, "sha256": ""}


def _manifest(
    env: SimEnv, spec: EpisodeSpec, outcome: Outcome, terminated: bool, created_at: str
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "episode_id": spec.episode_id,
        "producer": "vishwaroop",
        "created_at": created_at,
        "environment_kind": "physics_sim",
        "purpose": spec.purpose,
        "task": {
            "id": spec.task_id,
            "version": spec.task_version,
            "instruction": spec.instruction,
            "criteria_artifact": _ref("rubric.json"),
        },
        "configuration": {
            "embodiment_id": spec.embodiment_id,
            "embodiment_artifact": _ref("configuration.json"),
            "controller_artifact": _ref("configuration.json"),
            "calibration_artifact": _ref("configuration.json"),
            "preprocessing_artifact": _ref("configuration.json"),
            "stack_artifact": _ref("stack.json"),
        },
        "policy": {
            "origin": "scripted",
            "checkpoint_id": None,
            "training_run_id": None,
            "family_id": spec.policy_family,
            "weights_artifact": None,
            "config_artifact": None,
        },
        "provenance": {
            "parent_episode_ids": [],
            "source_episode_artifacts": [],
            "generator_model_artifact": None,
        },
        "split": {
            "partition": spec.partition,
            "suite_id": spec.suite_id,
            "scene_group_id": spec.scene_group_id,
            "session_group_id": spec.session_group_id,
            "policy_run_group_id": spec.policy_family,
            "inherited_from_parent": False,
        },
        "timebase": {
            "unit": "nanoseconds",
            "clock_domain": CLOCK_DOMAIN,
            "alignment_artifact": None,
        },
        "frames": list(env.frames),
        "streams": [stream.to_manifest() for stream in env.stream_specs],
        "action_spec": env.action_spec.to_manifest(),
        "simulator": {
            "engine": env.engine,
            "version": env.version,
            "initial_state_artifact": _ref("initial-state.json"),
            "asset_manifest_artifact": _ref("assets.json"),
            "restore_mode": "initial_state_only",
        },
        "validation": {"statuses": [], "evidence": []},
        "outcome": {
            "protocol_version": spec.protocol_version,
            "rubric_version": spec.rubric.rubric_version,
            "assessment_method": "independent_sim_state",
            "success": outcome.success,
            "terminated": terminated,
            "truncated": not terminated,
            "reason": f"{outcome.label}: {outcome.reason}",
            "final_assessment_artifact": _ref("final-assessment.json"),
            "training_reward_artifact": None,
            "paired_trial_id": None,
            "reviewer_ids": [],
        },
        "notes": spec.notes,
    }


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n"


def record_episode(
    env: SimEnv,
    policy: Policy,
    spec: EpisodeSpec,
    target_dir: Path,
    closing_note: Callable[[], str | None] | None = None,
) -> Path:
    """Run one episode and write it once. Raises the contract's error if it does not validate.

    The initial state is saved right after ``reset``, before any action, and the episode then runs
    from that saved state, by the same path a replay takes. Starting straight from ``reset`` instead
    diverges from replay, because restoring is not exact and contact amplifies the difference
    (ADR-0006). The policy sees only the streams declared as inputs. ``closing_note`` runs after the
    last step, and what it returns is added to the manifest's notes. The outcome comes from the
    independent rubric. An existing ``target_dir`` is refused by the writer. The manifest says
    ``scripted``, because M0's only policies are scripted (evals/M0-protocol.md section 6).
    """
    inputs = {stream.name for stream in env.stream_specs if stream.role == "input"}
    env.reset(spec.seed)
    initial_state = env.save_state()
    packet = env.restore_state(initial_state)
    records: list[dict[str, Any]] = []
    terminated = False
    for step in range(spec.max_steps):
        action = policy({name: packet[name] for name in packet if name in inputs}, step)
        if action is None:
            terminated = True
            break
        next_packet = env.step(action)
        records.append(_record(env, spec, step, packet, action, next_packet))
        packet = next_packet
    outcome = assess(samples_from_records(records), spec.rubric)
    created_at = spec.created_at or datetime.now(UTC).isoformat(timespec="seconds")
    note = closing_note() if closing_note is not None else None
    final_spec = spec if note is None else replace(spec, notes=f"{spec.notes} {note}")
    manifest = _manifest(env, final_spec, outcome, terminated, created_at)
    builder = writer_module().EpisodeBuilder(manifest)
    builder.add_file("rubric.json", _json_bytes(asdict(spec.rubric)))
    builder.add_file("configuration.json", _json_bytes(env.configuration()))
    builder.add_file("stack.json", _json_bytes(env.stack_identity()))
    builder.add_file("assets.json", _json_bytes(env.asset_manifest()))
    builder.add_file("initial-state.json", initial_state)
    builder.add_file("final-assessment.json", _json_bytes(asdict(outcome)))
    for record in records:
        builder.add_record(record)
    written: Path = builder.write(Path(target_dir))
    return written
