"""Replay an exported episode from its saved initial state only, through physics.

The claim is that the recorded actions reproduce the episode. It holds only when the episode and the
simulator describe the same experiment, the recorded outcome matches the rubric, and every repeat
stays inside the frozen tolerance, gives the recorded label, and restored state once per repeat.

The restore count comes from the environment adapter, so it can only catch forcing the adapter
counts. The forcing mode exists to show that forcing gets rejected; it never supports a claim.

Exit codes for the command line: 0 claim valid, 1 claim invalid, 2 refused, 3 simulator not run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import asdict, dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

from ..outcome.pickplace import PlaceRubric, assess, samples_from_records
from .contract import validator
from .env import ManiSkillPickCube, Packet, SimEnv, SimulatorUnavailableError
from .export import CLOCK_DOMAIN

INITIAL_STATE_ONLY = "initial_state_only"
FORCED_INTERMEDIATE_STATES = "forced_intermediate_states"
_MODES = {INITIAL_STATE_ONLY, FORCED_INTERMEDIATE_STATES}
_REPO_ROOT = Path(__file__).resolve().parents[3]


class ReplayInvalidError(ValueError):
    """The inputs do not describe one experiment, or a limit is unusable; nothing was replayed."""


@dataclass(frozen=True)
class ReplayTolerance:
    """Frozen replay numbers. ``max_state_deviation`` is in the compared streams' units."""

    compare_streams: list[str]
    max_state_deviation: float
    repeats: int
    max_episode_steps: int | None = None


@dataclass(frozen=True)
class RepeatResult:
    """One replay. ``per_step`` holds each compared stream's largest absolute error, per sample."""

    repeat: int
    max_deviation: float
    worst_step: int
    worst_stream: str
    outcome_label: str
    success: bool | None
    per_step: list[dict[str, float]]


@dataclass(frozen=True)
class ReplayReport:
    """The claim and its evidence."""

    episode_id: str
    mode: str
    claim_valid: bool
    reason: str
    recorded_label: str
    record_count: int
    tolerance: ReplayTolerance
    repeats: list[RepeatResult]


def load_frozen(path: Path) -> tuple[ReplayTolerance, PlaceRubric]:
    """Read the replay tolerance and rubric from a frozen exit-test file."""
    frozen = json.loads(Path(path).read_text(encoding="utf-8"))
    replay = frozen["replay"]
    tolerance = ReplayTolerance(
        compare_streams=list(replay["compare_streams"]),
        max_state_deviation=float(replay["max_state_deviation"]),
        repeats=int(replay["repeats"]),
        max_episode_steps=int(frozen["task"]["max_episode_steps"]),
    )
    return tolerance, PlaceRubric.from_mapping(frozen["place_rubric"])


def require_frozen_file(path: Path, status_ledger: Path) -> None:
    """Refuse a specification whose sha256 no ``frozen`` event in the status ledger records."""
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    for line in status_ledger.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("event") == "frozen" and digest in record.get("note", ""):
            return
    raise ReplayInvalidError(f"{path} sha256 {digest} matches no frozen event in {status_ledger}")


def _check_tolerance(tolerance: ReplayTolerance) -> None:
    if tolerance.repeats < 1:
        raise ReplayInvalidError(f"repeats must be at least 1, not {tolerance.repeats}")
    if not tolerance.compare_streams:
        raise ReplayInvalidError("compare_streams is empty, so nothing would be compared")
    limit = tolerance.max_state_deviation
    if not math.isfinite(limit) or limit < 0:
        raise ReplayInvalidError(f"max_state_deviation must be finite and not negative: {limit}")


def _read_json(episode_dir: Path, artifact: dict[str, str]) -> Any:
    return json.loads((episode_dir / artifact["path"]).read_text(encoding="utf-8"))


def _load_episode(episode_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]], bytes]:
    manifest_path = episode_dir / "episode.json"
    validator().validate_episode(manifest_path)
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    simulator = manifest["simulator"]
    if simulator is None:
        raise ReplayInvalidError("episode has no simulator identity")
    transitions = manifest["data"]["transitions_artifact"]["path"]
    lines = (episode_dir / transitions).read_text(encoding="utf-8").splitlines()
    state = (episode_dir / simulator["initial_state_artifact"]["path"]).read_bytes()
    return manifest, [json.loads(line) for line in lines], state


def _same(what: str, recorded: Any, actual: Any) -> None:
    if recorded != actual:
        raise ReplayInvalidError(f"{what} differ: recorded {recorded}, simulator {actual}")


def _check_identity(
    episode_dir: Path, manifest: dict[str, Any], env: SimEnv, records: list[dict[str, Any]]
) -> None:
    """Refuse unless the episode and this simulator describe the same experiment."""
    simulator = manifest["simulator"]
    _same(
        "engine and version", [simulator["engine"], simulator["version"]], [env.engine, env.version]
    )
    _same("action spec fields", manifest["action_spec"], env.action_spec.to_manifest())
    _same("streams", manifest["streams"], [stream.to_manifest() for stream in env.stream_specs])
    _same(
        "assets",
        _read_json(episode_dir, simulator["asset_manifest_artifact"]),
        env.asset_manifest(),
    )
    configuration = manifest["configuration"]
    _same("stacks", _read_json(episode_dir, configuration["stack_artifact"]), env.stack_identity())
    _same(
        "configurations",
        _read_json(episode_dir, configuration["embodiment_artifact"]),
        env.configuration(),
    )
    _same("timebase clock domains", manifest["timebase"]["clock_domain"], CLOCK_DOMAIN)
    for record in records:
        expected = record["step"] * env.dt_ns
        if record["dt_ns"] != env.dt_ns or record["t_ns"] != expected:
            raise ReplayInvalidError(
                f"timebase differs at step {record['step']}: t_ns {record['t_ns']} and dt_ns "
                f"{record['dt_ns']}; the simulator gives t_ns {expected} and dt_ns {env.dt_ns}"
            )


def _values(packets: list[dict[str, Any]]) -> dict[str, Any]:
    return {packet["stream"]: packet["value"] for packet in packets}


def _check_continuity(records: list[dict[str, Any]]) -> None:
    """Each step's observations must be the state the previous step ended in."""
    for before, after in pairwise(records):
        if _values(after["observations"]) != _values(before["next_observations"]):
            raise ReplayInvalidError(
                f"observations at step {after['step']} differ from the state step "
                f"{before['step']} ended in"
            )


def _check_recorded_outcome(
    episode_dir: Path, manifest: dict[str, Any], records: list[dict[str, Any]], rubric: PlaceRubric
) -> str:
    """Refuse unless the manifest and its artifacts state what the rubric gives on the records."""
    assessed = assess(samples_from_records(records), rubric)
    recorded = manifest["outcome"]
    _same("recorded success values", recorded["success"], assessed.success)
    _same("rubric versions", recorded["rubric_version"], rubric.rubric_version)
    if not recorded["reason"].startswith(f"{assessed.label}:"):
        raise ReplayInvalidError(
            f"recorded reason {recorded['reason']!r} does not match outcome {assessed.label}"
        )
    _same(
        "rubrics",
        _read_json(episode_dir, manifest["task"]["criteria_artifact"]),
        asdict(rubric),
    )
    final = recorded["final_assessment_artifact"]
    if final is None:
        raise ReplayInvalidError("episode has no final assessment artifact")
    _same("final assessments", _read_json(episode_dir, final), asdict(assessed))
    return assessed.label


def _deviation(
    recorded: list[dict[str, Any]], actual: Packet, compare: list[str]
) -> tuple[float, str, dict[str, float]]:
    """Largest absolute error per stream. A non-finite error counts as infinite."""
    values = _values(recorded)
    per_stream: dict[str, float] = {}
    for stream in compare:
        expected, seen = values.get(stream), actual.get(stream)
        if expected is None or seen is None or len(expected) != len(seen):
            raise ReplayInvalidError(f"stream {stream} cannot be compared")
        errors = [abs(float(a) - float(b)) for a, b in zip(expected, seen, strict=True)]
        per_stream[stream] = max(errors) if all(map(math.isfinite, errors)) else math.inf
    worst_stream = max(compare, key=lambda stream: per_stream[stream])
    return per_stream[worst_stream], worst_stream, per_stream


def _observations(env: SimEnv, packet: Packet) -> list[dict[str, Any]]:
    return [
        {"stream": stream.name, "valid": True, "value": packet[stream.name]}
        for stream in env.stream_specs
    ]


def _replay_once(
    repeat: int,
    env: SimEnv,
    state: bytes,
    records: list[dict[str, Any]],
    tolerance: ReplayTolerance,
    rubric: PlaceRubric,
    force_state: bool,
) -> RepeatResult:
    packet = env.restore_state(state)
    worst, worst_stream, first = _deviation(
        records[0]["observations"], packet, tolerance.compare_streams
    )
    worst_step = 0
    per_step = [first]
    replayed: list[dict[str, Any]] = []
    for record in records:
        before = env.restore_state(state) if force_state else packet
        packet = env.step(record["action"]["requested"])
        replayed.append(
            {
                "observations": _observations(env, before),
                "next_observations": _observations(env, packet),
            }
        )
        deviation, stream, errors = _deviation(
            record["next_observations"], packet, tolerance.compare_streams
        )
        per_step.append(errors)
        if deviation > worst:
            worst, worst_stream, worst_step = deviation, stream, record["step"] + 1
    outcome = assess(samples_from_records(replayed), rubric)
    return RepeatResult(
        repeat, worst, worst_step, worst_stream, outcome.label, outcome.success, per_step
    )


def replay_episode(
    episode_dir: str | Path,
    env: SimEnv,
    tolerance: ReplayTolerance,
    rubric: PlaceRubric,
    mode: str = INITIAL_STATE_ONLY,
) -> ReplayReport:
    """Replay and report. Raises the contract's error, or ``ReplayInvalidError``, before running."""
    if mode not in _MODES:
        raise ValueError(f"unknown replay mode {mode}")
    _check_tolerance(tolerance)
    base = Path(episode_dir)
    manifest, records, state = _load_episode(base)
    if tolerance.max_episode_steps is not None and len(records) > tolerance.max_episode_steps:
        raise ReplayInvalidError(
            f"{len(records)} steps exceed the frozen limit of {tolerance.max_episode_steps}"
        )
    _check_identity(base, manifest, env, records)
    _check_continuity(records)
    recorded = _check_recorded_outcome(base, manifest, records, rubric)

    def report(valid: bool, reason: str, repeats: list[RepeatResult]) -> ReplayReport:
        return ReplayReport(
            manifest["episode_id"], mode, valid, reason, recorded, len(records), tolerance, repeats
        )

    restores_before = env.state_restores
    force_state = mode == FORCED_INTERMEDIATE_STATES
    results = [
        _replay_once(i, env, state, records, tolerance, rubric, force_state)
        for i in range(tolerance.repeats)
    ]
    restores = env.state_restores - restores_before
    if restores != tolerance.repeats:
        return report(
            False, f"state was restored {restores} times over {tolerance.repeats} repeats", results
        )
    for result in results:
        if result.max_deviation > tolerance.max_state_deviation:
            reason = (
                f"repeat {result.repeat} deviated {result.max_deviation} on {result.worst_stream} "
                f"at step {result.worst_step}; tolerance {tolerance.max_state_deviation}"
            )
            return report(False, reason, results)
        if result.outcome_label != recorded:
            reason = (
                f"repeat {result.repeat} gave outcome {result.outcome_label}; recorded {recorded}"
            )
            return report(False, reason, results)
    if recorded == "insufficient_evidence":
        return report(
            False, "the recorded outcome is undecided, so there is nothing to confirm", results
        )
    return report(True, "all repeats within tolerance with the recorded outcome", results)


def env_for_manifest(episode_dir: Path, manifest: dict[str, Any]) -> SimEnv:
    """Build the real simulator an episode names. Raises if it is unknown or cannot start."""
    engine = manifest["simulator"]["engine"]
    if engine != ManiSkillPickCube.engine:
        raise SimulatorUnavailableError(f"no adapter for engine {engine}")
    configuration = _read_json(episode_dir, manifest["configuration"]["embodiment_artifact"])
    return ManiSkillPickCube(
        env_id=configuration["env_id"], max_episode_steps=configuration["max_episode_steps"]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode", type=Path, required=True)
    parser.add_argument("--tolerance-file", type=Path, required=True)
    parser.add_argument("--repeats", type=int, required=True)
    parser.add_argument("--out", type=Path, help="write-once report path")
    parser.add_argument(
        "--status-ledger", type=Path, default=_REPO_ROOT / "work_orders" / "STATUS.jsonl"
    )
    args = parser.parse_args(argv)
    if args.out is not None and args.out.exists():
        print(f"REFUSED: {args.out} already exists; reports are write-once")
        return 2
    try:
        require_frozen_file(args.tolerance_file, args.status_ledger)
    except (ValueError, OSError) as exc:
        print(f"REFUSED: {exc}")
        return 2
    tolerance, rubric = load_frozen(args.tolerance_file)
    if args.repeats != tolerance.repeats:
        print(f"REFUSED: the frozen protocol says {tolerance.repeats} repeats, not {args.repeats}")
        return 2
    manifest = json.loads((args.episode / "episode.json").read_text(encoding="utf-8"))
    try:
        env = env_for_manifest(args.episode, manifest)
    except SimulatorUnavailableError as exc:
        print(f"NOT RUN: {exc}")
        return 3
    try:
        report = replay_episode(args.episode, env, tolerance, rubric)
    except (ValueError, OSError) as exc:
        print(f"REFUSED: {exc}")
        return 2
    text = json.dumps(asdict(report), indent=2, sort_keys=True)
    if args.out is not None:
        with args.out.open("x", encoding="utf-8") as stream:
            stream.write(text + "\n")
    print(text)
    return 0 if report.claim_valid else 1


if __name__ == "__main__":
    sys.exit(main())
