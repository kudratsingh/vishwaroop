#!/usr/bin/env python3
"""Validate bounded local episode exports against contract v1.

Checks JSON Schema conformance, local artifact integrity (sha256, no traversal, no symlink escape),
action/stream dimensions, frame references, decision-time input rules, record continuity, validity
masks, provenance and validation-status rules. Never fetches, executes, or unpickles anything.

Optionally merges an append-only validation ledger (``--ledger``) so that evidence recorded after
export (replay checks, physical assessments) is applied without ever editing the episode manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

HERE = Path(__file__).resolve().parent
SCHEMA_VERSION = "1.0.0"


class ContractError(ValueError):
    """An invalid record, reference, or semantic relationship."""


# --------------------------------------------------------------------------- strict JSON


def _assert_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractError("non-finite numeric value")
    if isinstance(value, dict):
        for item in value.values():
            _assert_finite(item)
    elif isinstance(value, list):
        for item in value:
            _assert_finite(item)


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json(text: str) -> Any:
    """Parse JSON, rejecting NaN/Infinity and duplicate keys."""

    def reject(value: str) -> None:
        raise ContractError(f"invalid JSON constant {value}")

    try:
        parsed = json.loads(text, parse_constant=reject, object_pairs_hook=_no_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise ContractError(str(exc)) from exc
    _assert_finite(parsed)
    return parsed


def read_json(path: Path) -> Any:
    return parse_json(path.read_text(encoding="utf-8"))


def _check_schema(value: Any, filename: str) -> None:
    schema = read_json(HERE / filename)
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))
    if errors:
        first = errors[0]
        raise ContractError(f"{filename}: {list(first.path)}: {first.message}")


# --------------------------------------------------------------------------- artifacts


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_artifact(base: Path, ref: dict[str, str]) -> Path:
    """Resolve an artifact reference relative to the episode directory and verify its hash."""
    raw = Path(ref["path"])
    # Reject parent traversal even if it would resolve back inside the base.
    if raw.is_absolute() or ".." in raw.parts or "\\" in ref["path"]:
        raise ContractError("artifact path must be portable and relative, without traversal")
    path = (base / raw).resolve()
    if not path.is_relative_to(base.resolve()) or not path.is_file():
        raise ContractError(f"missing or escaped artifact: {raw}")
    if sha256_file(path) != ref["sha256"]:
        raise ContractError(f"artifact checksum mismatch: {raw}")
    return path


def _check_refs(base: Path, value: Any, seen: set[tuple[str, str]]) -> None:
    if isinstance(value, dict):
        if set(value) == {"path", "sha256"}:
            key = (value["path"], value["sha256"])
            if key not in seen:
                resolve_artifact(base, value)
                seen.add(key)
        else:
            for item in value.values():
                _check_refs(base, item, seen)
    elif isinstance(value, list):
        for item in value:
            _check_refs(base, item, seen)


# --------------------------------------------------------------------------- semantic checks


def _check_action_spec(episode: dict[str, Any]) -> int:
    spec = episode["action_spec"]
    n = len(spec["labels"])
    if len(set(spec["labels"])) != n:
        raise ContractError("duplicate action labels")
    if any(len(spec[key]) != n for key in ("units", "lower", "upper")):
        raise ContractError("action spec dimension mismatch")
    if any(lo >= hi for lo, hi in zip(spec["lower"], spec["upper"], strict=True)):
        raise ContractError("action lower bounds must be below upper bounds")
    if spec["frame_id"] not in episode["frames"]:
        raise ContractError("unknown action frame")
    return n


def _check_streams(episode: dict[str, Any]) -> dict[str, dict[str, Any]]:
    streams = {s["name"]: s for s in episode["streams"]}
    if len(streams) != len(episode["streams"]):
        raise ContractError("duplicate stream name")
    for stream in streams.values():
        if stream["frame_id"] not in episode["frames"]:
            raise ContractError("unknown observation frame")
        if len(stream["units"]) not in (1, math.prod(stream["shape"])):
            raise ContractError("stream units dimension mismatch")
    return streams


def _check_provenance(episode: dict[str, Any]) -> None:
    kind = episode["environment_kind"]
    if kind == "physics_sim" and episode["simulator"] is None:
        raise ContractError("physics_sim requires saved initial state and asset manifest")
    if kind == "real" and episode["simulator"] is not None:
        raise ContractError("real observations cannot have an active simulator identity")
    provenance = episode["provenance"]
    if kind == "imagined":
        if not provenance["parent_episode_ids"] or provenance["generator_model_artifact"] is None:
            raise ContractError("imagined records require parent and generator")
        if not episode["split"]["inherited_from_parent"]:
            raise ContractError("imagined records must inherit split lineage")
    if episode["episode_id"] in provenance["parent_episode_ids"]:
        raise ContractError("episode cannot parent itself")
    if len(set(provenance["parent_episode_ids"])) != len(provenance["parent_episode_ids"]):
        raise ContractError("duplicate parent IDs")
    policy = episode["policy"]
    if policy["origin"] == "trained":
        for key in (
            "checkpoint_id",
            "training_run_id",
            "family_id",
            "weights_artifact",
            "config_artifact",
        ):
            if policy[key] is None:
                raise ContractError(f"trained policy missing {key}")
        if episode["split"]["policy_run_group_id"] is None:
            raise ContractError("trained policy needs run grouping")


def check_validation_block(
    episode: dict[str, Any], statuses: list[str], evidence: list[dict[str, Any]]
) -> None:
    """Rules relating validation statuses to evidence; shared by manifest and ledger paths."""
    kind = episode["environment_kind"]
    if episode["purpose"] == "schema_fixture" and statuses:
        raise ContractError("fixtures cannot assert experiment validation")
    if "replay_checked" in statuses and not any(e["kind"] == "physics_replay" for e in evidence):
        raise ContractError("replay_checked needs replay evidence")
    if "generated" in statuses and kind != "imagined":
        raise ContractError("generated status is for imagined observations")
    if "physically_evaluated" in statuses:
        matching = any(
            e["kind"] == "physical_assessment" and e["assessed_episode_id"] == episode["episode_id"]
            for e in evidence
        )
        if kind != "real" or not matching:
            raise ContractError("physical assessment requires a real episode and matching evidence")


def _check_outcome(episode: dict[str, Any]) -> None:
    outcome = episode["outcome"]
    if outcome["success"] is not None and outcome["final_assessment_artifact"] is None:
        raise ContractError("outcome needs assessment evidence")
    if outcome["terminated"] and outcome["truncated"]:
        raise ContractError("this contract distinguishes terminal versus truncated episodes")
    reward = outcome["training_reward_artifact"]
    final = outcome["final_assessment_artifact"]
    if reward and final and reward["sha256"] == final["sha256"]:
        raise ContractError("training reward is not an independent final assessment")


def _check_observations(
    observations: list[dict[str, Any]], decision_time: int, streams: dict[str, dict[str, Any]]
) -> None:
    names: set[str] = set()
    for obs in observations:
        if obs["stream"] not in streams or obs["stream"] in names:
            raise ContractError("unknown or duplicate observation stream")
        names.add(obs["stream"])
        stream = streams[obs["stream"]]
        if obs["capture_t_ns"] > obs["received_t_ns"]:
            raise ContractError("observation received before capture in mapped clock")
        if stream["role"] == "input" and obs["received_t_ns"] > decision_time:
            raise ContractError("future observation leakage into decision inputs")
        payload_count = int(obs["value"] is not None) + int(obs["artifact"] is not None)
        if payload_count != (1 if obs["valid"] else 0):
            raise ContractError("validity mask and payload disagree")
        if obs["value"] is not None and len(obs["value"]) != math.prod(stream["shape"]):
            raise ContractError("observation shape mismatch")
    if names != set(streams):
        raise ContractError("all declared streams require records, including invalid/missing ones")


def _check_action(action: dict[str, Any], t_ns: int, n_actions: int) -> None:
    if action["decision_t_ns"] != t_ns or action["valid_until_t_ns"] <= t_ns:
        raise ContractError("invalid decision/expiry times")
    sent = action["sent_t_ns"]
    applied = action["applied_t_ns"]
    if sent is not None and sent < t_ns:
        raise ContractError("action sent before decision")
    if applied is not None and applied < (sent if sent is not None else t_ns):
        raise ContractError("action applied before decision/send")
    for key in ("requested", "filtered", "transmitted", "applied"):
        if action[key] is not None and len(action[key]) != n_actions:
            raise ContractError(f"{key} action dimension mismatch")
    # Requested and measured-applied values may legitimately violate limits in fault data.
    # Preserve such evidence; quality/flight gates assess constraint violations separately.
    for field, time_field in (("transmitted", "sent_t_ns"), ("applied", "applied_t_ns")):
        if action[field] is None and action[time_field] is not None:
            raise ContractError(f"{time_field} present without {field} action")


def _check_records(
    episode: dict[str, Any], base: Path, streams: dict[str, dict[str, Any]], n_actions: int
) -> int:
    data_path = resolve_artifact(base, episode["data"]["transitions_artifact"])
    lines = data_path.read_text(encoding="utf-8").splitlines()
    if len(lines) != episode["data"]["record_count"] or any(not line.strip() for line in lines):
        raise ContractError("record count mismatch or empty JSONL record")
    records = [parse_json(line) for line in lines]
    refs_seen: set[tuple[str, str]] = set()
    for index, record in enumerate(records):
        _check_schema(record, "transition.schema.json")
        _check_refs(base, record, refs_seen)
        if record["episode_id"] != episode["episode_id"] or record["step"] != index:
            raise ContractError("episode or step sequence mismatch")
        if index and records[index - 1]["t_ns"] + records[index - 1]["dt_ns"] != record["t_ns"]:
            raise ContractError("non-contiguous or non-monotonic transition times")
        _check_observations(record["observations"], record["t_ns"], streams)
        _check_observations(record["next_observations"], record["t_ns"] + record["dt_ns"], streams)
        _check_action(record["action"], record["t_ns"], n_actions)
    return len(records)


# --------------------------------------------------------------------------- ledger


def read_ledger(path: Path) -> list[dict[str, Any]]:
    """Read an append-only validation ledger (JSON Lines) and schema-check every record."""
    records: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            raise ContractError(f"ledger line {number} is empty")
        record = parse_json(line)
        _check_schema(record, "validation_ledger.schema.json")
        records.append(record)
    return records


def effective_validation(
    episode: dict[str, Any], ledger: list[dict[str, Any]], base: Path
) -> dict[str, Any]:
    """Merge manifest validation with ledger records for this episode, verifying evidence artifacts.

    The episode manifest is never edited: evidence recorded after export lives in the ledger. Ledger
    artifact paths are relative to the ledger's directory (``base``).
    """
    statuses = list(episode["validation"]["statuses"])
    evidence = list(episode["validation"]["evidence"])
    for record in ledger:
        if record["episode_id"] != episode["episode_id"]:
            continue
        resolve_artifact(base, record["evidence"]["artifact"])
        evidence.append(record["evidence"])
        if record["status"] not in statuses:
            statuses.append(record["status"])
    check_validation_block(episode, statuses, evidence)
    return {"statuses": statuses, "evidence": evidence}


# --------------------------------------------------------------------------- entry points


def validate_episode(path: str | Path, ledger_path: str | Path | None = None) -> dict[str, Any]:
    """Validate one episode directory; optionally apply an append-only validation ledger."""
    episode_path = Path(path).resolve()
    base = episode_path.parent
    episode = read_json(episode_path)
    _check_schema(episode, "episode.schema.json")
    _check_refs(base, episode, set())
    n_actions = _check_action_spec(episode)
    streams = _check_streams(episode)
    _check_provenance(episode)
    check_validation_block(
        episode, episode["validation"]["statuses"], episode["validation"]["evidence"]
    )
    _check_outcome(episode)
    record_count = _check_records(episode, base, streams, n_actions)
    effective: dict[str, Any] = {
        "statuses": episode["validation"]["statuses"],
        "evidence": episode["validation"]["evidence"],
    }
    if ledger_path is not None:
        ledger_file = Path(ledger_path).resolve()
        effective = effective_validation(episode, read_ledger(ledger_file), ledger_file.parent)
    return {
        "episode_id": episode["episode_id"],
        "records": record_count,
        "environment_kind": episode["environment_kind"],
        "purpose": episode["purpose"],
        "effective_validation_statuses": effective["statuses"],
        "status": "contract_valid",
        "note": "No simulator, policy, or physical validation was performed by this check.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode", type=Path)
    parser.add_argument(
        "--ledger", type=Path, default=None, help="append-only validation ledger (JSONL)"
    )
    args = parser.parse_args(argv)
    try:
        print(json.dumps(validate_episode(args.episode, args.ledger), indent=2))
        return 0
    except (ContractError, OSError, KeyError, TypeError) as exc:
        print(f"INVALID: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
