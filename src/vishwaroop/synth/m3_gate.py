"""The M3 reproducibility gate, by ``evals/M3-protocol.md`` section 4.

Before a scene is used for a recorded episode that enters training or evaluation, the episode is
replayed from its saved initial state 3 times. It fails the gate when a repeat deviates by more than
the frozen 0.001 (``evals/M0-exit-tests.json``, in the compared streams' units: joint positions in
rad, object and target positions in m) or when a repeat's outcome label differs from the recorded
one, so that the label is identical on every repeat.

The tolerance is built here from ``evals/M0-exit-tests.json`` with the M3 protocol version, not by
``sim.replay.load_frozen``, whose protocol stamp is M0's; the frozen files' sha256s are checked by
``et_m3_6_guard.check_frozen``, not through ET-M3-1's or M0's ledger state.

``sim.replay.replay_episode`` refuses a recorded ``insufficient_evidence`` label, but section 4
excludes a scene only for the tolerance or a label that differs between repeats. WO-022's agent
detail 1 proposes following section 4: an undecided label that repeats identically, within the
tolerance, passes. That choice is the single constant ``UNDECIDED_REPEATS_PASS``, so the owner's
veto is a one-line change.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..outcome.pickplace import PlaceRubric
from ..sim.env import SimEnv
from ..sim.replay import ReplayReport, ReplayTolerance, replay_episode
from .protocol import PROTOCOL_VERSION

# WO-022 agent detail 1 (owner may veto): an undecided label repeated identically passes the gate.
UNDECIDED_REPEATS_PASS = True
UNDECIDED = "insufficient_evidence"
GATE_REPEATS = 3
GATE_MAX_DEVIATION = 0.001
# sim/replay.py's reason for a valid replay of an undecided recording; checked by a test.
REPLAY_UNDECIDED_REASON = "the recorded outcome is undecided, so there is nothing to confirm"


class GateSpecificationError(ValueError):
    """The frozen replay numbers are not the ones protocol section 4 names."""


@dataclass(frozen=True)
class GateResult:
    """One episode's gate. ``labels`` and ``max_deviations`` are per repeat."""

    episode_id: str
    passed: bool
    reason: str
    recorded_label: str
    labels: list[str]
    max_deviations: list[float]
    undecided: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "passed": self.passed,
            "reason": self.reason,
            "recorded_label": self.recorded_label,
            "labels": list(self.labels),
            "max_deviations": [
                value if math.isfinite(value) else str(value) for value in self.max_deviations
            ],
            "undecided": self.undecided,
        }


def gate_tolerance(
    m0_exit_tests: Path = Path("evals/M0-exit-tests.json"),
) -> tuple[ReplayTolerance, PlaceRubric]:
    """The gate's tolerance and the frozen rubric, from M0's exit tests, stamped with M3's protocol.

    Refuses numbers other than section 4's: 3 repeats, 0.001, and identical labels required.
    """
    frozen = json.loads(Path(m0_exit_tests).read_text(encoding="utf-8"))
    replay = frozen["replay"]
    if int(replay["repeats"]) != GATE_REPEATS:
        raise GateSpecificationError(f"{replay['repeats']} repeats, not {GATE_REPEATS}")
    if float(replay["max_state_deviation"]) != GATE_MAX_DEVIATION:
        raise GateSpecificationError(
            f"tolerance {replay['max_state_deviation']}, not {GATE_MAX_DEVIATION}"
        )
    if replay.get("require_identical_outcome_label") is not True:
        raise GateSpecificationError("the frozen replay does not require identical labels")
    tolerance = ReplayTolerance(
        compare_streams=list(replay["compare_streams"]),
        max_state_deviation=float(replay["max_state_deviation"]),
        repeats=int(replay["repeats"]),
        max_episode_steps=int(frozen["task"]["max_episode_steps"]),
        env_id=frozen["task"]["env_id"],
        task_version=frozen["task"]["version"],
        protocol_version=PROTOCOL_VERSION,
    )
    return tolerance, PlaceRubric.from_mapping(frozen["place_rubric"])


def decide(report: ReplayReport, undecided_pass: bool = UNDECIDED_REPEATS_PASS) -> GateResult:
    """The gate's verdict from a replay report.

    Fails when the replay did not run ``GATE_REPEATS`` times, any repeat exceeds the tolerance, or
    any repeat's label differs from the recorded one. A replay that ``sim.replay`` declares valid
    passes. One it declares invalid only because the recorded label is undecided passes when
    ``undecided_pass`` holds; any other invalid replay fails with ``sim.replay``'s reason.
    """
    tolerance = report.tolerance
    labels = [result.outcome_label for result in report.repeats]
    deviations = [result.max_deviation for result in report.repeats]
    undecided = report.recorded_label == UNDECIDED

    def result(passed: bool, reason: str) -> GateResult:
        return GateResult(
            report.episode_id, passed, reason, report.recorded_label, labels, deviations, undecided
        )

    if len(report.repeats) != GATE_REPEATS:
        return result(False, f"{len(report.repeats)} repeats, not {GATE_REPEATS}")
    for repeat in report.repeats:
        if not repeat.max_deviation <= tolerance.max_state_deviation:
            return result(
                False,
                f"repeat {repeat.repeat} deviated {repeat.max_deviation} on {repeat.worst_stream} "
                f"at step {repeat.worst_step}; tolerance {tolerance.max_state_deviation}",
            )
        if repeat.outcome_label != report.recorded_label:
            return result(
                False,
                f"repeat {repeat.repeat} gave {repeat.outcome_label}; "
                f"recorded {report.recorded_label}",
            )
    if report.claim_valid:
        return result(True, "3 repeats within tolerance, each with the recorded label")
    if undecided and report.reason == REPLAY_UNDECIDED_REASON:
        if undecided_pass:
            return result(
                True,
                "3 repeats within tolerance, each with the recorded undecided label "
                "(protocol section 4; WO-022 agent detail 1)",
            )
        return result(False, "undecided label; agent detail 1 vetoed")
    return result(False, report.reason)


def run_gate(
    episode_dir: Path, env: SimEnv, tolerance: ReplayTolerance, rubric: PlaceRubric
) -> GateResult:
    """Replay a recorded episode 3 times from its saved initial state and decide the gate.

    Raises ``sim.replay.ReplayInvalidError`` (or the contract's error) when the episode and the
    simulator do not describe one experiment: that is a refusal, not a failed scene.
    """
    if tolerance.repeats != GATE_REPEATS:
        raise GateSpecificationError(f"{tolerance.repeats} repeats, not {GATE_REPEATS}")
    return decide(replay_episode(Path(episode_dir), env, tolerance, rubric))
