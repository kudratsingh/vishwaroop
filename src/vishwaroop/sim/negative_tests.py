"""The five ways an episode's evidence must fail (ET-M0-4).

The undamaged episode is replayed first, as a positive control: rejections from an episode that was
already broken would prove nothing. Each case then damages a temporary copy, and the original is
never touched. A case counts as rejected only for the reason it names. Damage a file hash would
catch by itself is re-hashed, so the semantic check under test is what rejects it.

Exit codes: 0 all rejected, 1 something was accepted, 2 refused, 3 simulator not run,
4 the undamaged episode failed its own replay.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..outcome.pickplace import PlaceRubric
from .contract import validator
from .env import SimEnv, SimulatorUnavailableError
from .replay import (
    FORCED_INTERMEDIATE_STATES,
    INITIAL_STATE_ONLY,
    ReplayInvalidError,
    ReplayTolerance,
    env_for_manifest,
    load_frozen,
    replay_episode,
)

Damage = Callable[[Path], None]


class PositiveControlError(ValueError):
    """The undamaged episode does not replay, so the negative tests would prove nothing."""


@dataclass(frozen=True)
class NegativeResult:
    """``rejected`` is True when the case failed for the reason it names."""

    name: str
    rejected: bool
    reason: str


def _manifest(episode: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((episode / "episode.json").read_text(encoding="utf-8"))
    return loaded


def _write_manifest(episode: Path, manifest: dict[str, Any]) -> None:
    text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    (episode / "episode.json").write_text(text, encoding="utf-8")


def _swap_action_labels(episode: Path) -> None:
    manifest = _manifest(episode)
    labels = manifest["action_spec"]["labels"]
    labels[0], labels[1] = labels[1], labels[0]
    _write_manifest(episode, manifest)


def _break_artifact_hash(episode: Path) -> None:
    manifest = _manifest(episode)
    path = episode / manifest["simulator"]["initial_state_artifact"]["path"]
    path.write_bytes(path.read_bytes() + b" ")


def _remove_asset_manifest(episode: Path) -> None:
    manifest = _manifest(episode)
    (episode / manifest["simulator"]["asset_manifest_artifact"]["path"]).unlink()


def _shift_timebase(episode: Path) -> None:
    """Shift every time field by the same amount: internally consistent, and still wrong."""
    manifest = _manifest(episode)
    artifact = manifest["data"]["transitions_artifact"]
    path = episode / artifact["path"]
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    shift = 1_000_000
    for record in records:
        record["t_ns"] += shift
        action = record["action"]
        action["decision_t_ns"] += shift
        action["valid_until_t_ns"] += shift
        for packet in (*record["observations"], *record["next_observations"]):
            packet["capture_t_ns"] += shift
            packet["received_t_ns"] += shift
    text = "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)
    path.write_text(text, encoding="utf-8")
    artifact["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    _write_manifest(episode, manifest)


def _no_damage(_: Path) -> None:
    return None


CASES: list[tuple[str, Damage, str, str]] = [
    ("corrupted_action_semantics", _swap_action_labels, INITIAL_STATE_ONLY, "action spec"),
    ("broken_artifact_hash", _break_artifact_hash, INITIAL_STATE_ONLY, "checksum mismatch"),
    ("missing_asset", _remove_asset_manifest, INITIAL_STATE_ONLY, "missing or escaped artifact"),
    ("wrong_timebase", _shift_timebase, INITIAL_STATE_ONLY, "timebase differs"),
    ("intermediate_state_forcing", _no_damage, FORCED_INTERMEDIATE_STATES, "state was restored"),
]


def _run_case(
    episode: Path,
    damage: Damage,
    mode: str,
    env: SimEnv,
    tolerance: ReplayTolerance,
    rubric: PlaceRubric,
) -> tuple[bool, str]:
    """Return (claim was invalidated, why)."""
    damage(episode)
    contract_error = validator().ContractError
    try:
        report = replay_episode(episode, env, tolerance, rubric, mode=mode)
    except (contract_error, ReplayInvalidError) as exc:
        return True, f"{type(exc).__name__}: {exc}"
    return (not report.claim_valid), report.reason


def run_negative_tests(
    episode_dir: str | Path, env: SimEnv, tolerance: ReplayTolerance, rubric: PlaceRubric
) -> list[NegativeResult]:
    """Run the positive control, then all five cases, each on its own temporary copy."""
    control = replay_episode(episode_dir, env, tolerance, rubric)
    if not control.claim_valid:
        raise PositiveControlError(f"the undamaged episode fails: {control.reason}")
    results: list[NegativeResult] = []
    for name, damage, mode, expected in CASES:
        with tempfile.TemporaryDirectory(prefix="negative-test-") as tmp:
            copy = Path(tmp) / "episode"
            shutil.copytree(episode_dir, copy)
            invalidated, reason = _run_case(copy, damage, mode, env, tolerance, rubric)
        results.append(NegativeResult(name, invalidated and expected in reason, reason))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode", type=Path, required=True)
    parser.add_argument("--tolerance-file", type=Path, default=Path("evals/M0-exit-tests.json"))
    args = parser.parse_args(argv)
    tolerance, rubric = load_frozen(args.tolerance_file)
    try:
        env = env_for_manifest(args.episode, _manifest(args.episode))
    except SimulatorUnavailableError as exc:
        print(f"NOT RUN: {exc}")
        return 3
    try:
        results = run_negative_tests(args.episode, env, tolerance, rubric)
    except PositiveControlError as exc:
        print(f"CONTROL FAILED: {exc}")
        return 4
    except (ValueError, OSError) as exc:
        print(f"REFUSED: {exc}")
        return 2
    print(json.dumps([asdict(result) for result in results], indent=2))
    distinct = len({result.reason for result in results}) == len(results)
    return 0 if distinct and all(result.rejected for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
