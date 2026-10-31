"""Replay an exported episode from its saved initial state only, through physics.

The claim is that the recorded actions reproduce the episode. It holds only when every repeat stays
inside the frozen tolerance, gives the recorded outcome label, and restored state exactly once per
repeat. Forcing state during a replay is incompatible with the claim, so that mode exists only to
show it gets rejected.

Exit codes for the command line: 0 claim valid, 1 claim invalid, 2 refused, 3 simulator not run.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..outcome.pickplace import PlaceRubric, assess, samples_from_records
from .contract import validator
from .env import ManiSkillPickCube, Packet, SimEnv, SimulatorUnavailableError

INITIAL_STATE_ONLY = "initial_state_only"
FORCED_INTERMEDIATE_STATES = "forced_intermediate_states"


class ReplayInvalidError(ValueError):
    """The episode and this simulator do not describe the same experiment; nothing was replayed."""


@dataclass(frozen=True)
class ReplayTolerance:
    """Frozen replay numbers. ``max_state_deviation`` is in the compared streams' units."""

    compare_streams: list[str]
    max_state_deviation: float
    repeats: int


@dataclass(frozen=True)
class RepeatResult:
    """One replay. ``max_deviation`` is the largest absolute difference on any compared value."""

    repeat: int
    max_deviation: float
    worst_step: int
    worst_stream: str
    outcome_label: str
    success: bool | None


@dataclass(frozen=True)
class ReplayReport:
    """The claim and its evidence."""

    episode_id: str
    mode: str
    claim_valid: bool
    reason: str
    recorded_label: str
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
    )
    return tolerance, PlaceRubric.from_mapping(frozen["place_rubric"])


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


def _check_identity(manifest: dict[str, Any], env: SimEnv) -> None:
    simulator = manifest["simulator"]
    if (simulator["engine"], simulator["version"]) != (env.engine, env.version):
        raise ReplayInvalidError(
            f"recorded on {simulator['engine']} {simulator['version']}; "
            f"this simulator is {env.engine} {env.version}"
        )
    labels = manifest["action_spec"]["labels"]
    if labels != env.action_spec.labels:
        raise ReplayInvalidError(
            f"action labels differ: recorded {labels}, simulator {env.action_spec.labels}"
        )


def _deviation(
    recorded: list[dict[str, Any]], actual: Packet, compare: list[str]
) -> tuple[float, str]:
    values = {packet["stream"]: packet["value"] for packet in recorded}
    worst, worst_stream = 0.0, compare[0]
    for stream in compare:
        expected, seen = values.get(stream), actual.get(stream)
        if expected is None or seen is None or len(expected) != len(seen):
            raise ReplayInvalidError(f"stream {stream} cannot be compared")
        deviation = max(abs(float(a) - float(b)) for a, b in zip(expected, seen, strict=True))
        if deviation > worst:
            worst, worst_stream = deviation, stream
    return worst, worst_stream


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
) -> RepeatResult:
    packet = env.restore_state(state)
    worst, worst_stream = _deviation(records[0]["observations"], packet, tolerance.compare_streams)
    worst_step = 0
    replayed: list[dict[str, Any]] = []
    for record in records:
        before = packet
        packet = env.step(record["action"]["requested"])
        replayed.append(
            {
                "observations": _observations(env, before),
                "next_observations": _observations(env, packet),
            }
        )
        deviation, stream = _deviation(
            record["next_observations"], packet, tolerance.compare_streams
        )
        if deviation > worst:
            worst, worst_stream, worst_step = deviation, stream, record["step"] + 1
    outcome = assess(samples_from_records(replayed), rubric)
    return RepeatResult(repeat, worst, worst_step, worst_stream, outcome.label, outcome.success)


def replay_episode(
    episode_dir: str | Path,
    env: SimEnv,
    tolerance: ReplayTolerance,
    rubric: PlaceRubric,
    mode: str = INITIAL_STATE_ONLY,
) -> ReplayReport:
    """Replay and report. Raises the contract's error, or ``ReplayInvalidError``, before running."""
    manifest, records, state = _load_episode(Path(episode_dir))
    _check_identity(manifest, env)
    recorded = assess(samples_from_records(records), rubric).label

    def report(valid: bool, reason: str, repeats: list[RepeatResult]) -> ReplayReport:
        episode_id = manifest["episode_id"]
        return ReplayReport(episode_id, mode, valid, reason, recorded, tolerance, repeats)

    if mode != INITIAL_STATE_ONLY:
        return report(False, f"mode {mode} forces state, so it cannot show executability", [])
    restores_before = env.state_restores
    results = [
        _replay_once(i, env, state, records, tolerance, rubric) for i in range(tolerance.repeats)
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
    return report(True, "all repeats within tolerance with the recorded outcome", results)


def env_for_manifest(manifest: dict[str, Any]) -> SimEnv:
    """Build the real simulator a manifest names. Raises if it is unknown or cannot start."""
    engine = manifest["simulator"]["engine"]
    if engine != ManiSkillPickCube.engine:
        raise SimulatorUnavailableError(f"no adapter for engine {engine}")
    return ManiSkillPickCube()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode", type=Path, required=True)
    parser.add_argument("--tolerance-file", type=Path, required=True)
    parser.add_argument("--repeats", type=int, required=True)
    parser.add_argument("--out", type=Path, help="write-once report path")
    args = parser.parse_args(argv)
    tolerance, rubric = load_frozen(args.tolerance_file)
    if args.repeats != tolerance.repeats:
        print(f"REFUSED: the frozen protocol says {tolerance.repeats} repeats, not {args.repeats}")
        return 2
    manifest = json.loads((args.episode / "episode.json").read_text(encoding="utf-8"))
    try:
        env = env_for_manifest(manifest)
    except SimulatorUnavailableError as exc:
        print(f"NOT RUN: {exc}")
        return 3
    try:
        report = replay_episode(args.episode, env, tolerance, rubric)
    except (ValueError, OSError) as exc:
        print(f"REFUSED: {exc}")
        return 2
    text = json.dumps(asdict(report), indent=2, sort_keys=True)
    if args.out:
        with args.out.open("x", encoding="utf-8") as stream:
            stream.write(text + "\n")
    print(text)
    return 0 if report.claim_valid else 1


if __name__ == "__main__":
    sys.exit(main())
