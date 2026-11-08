"""The M3 reproducibility gate, by ``evals/M3-protocol.md`` section 4.

Before a scene is used for a recorded episode that enters training or evaluation, the episode is
replayed from its saved initial state 3 times. It fails the gate when a repeat deviates by more than
the frozen 0.001 (``evals/M0-exit-tests.json``, in the compared streams' units: joint positions in
rad, object and target positions in m) or when a repeat's outcome label differs from the recorded
one, so that the label is identical on every repeat.

The tolerance is built here from ``evals/M0-exit-tests.json`` with the M3 protocol version, not by
``sim.replay.load_frozen``, whose protocol stamp is M0's; the frozen files' sha256s are checked by
``et_m3_6_guard.check_frozen``, not through ET-M3-1's or M0's ledger state.

``sim.replay.replay_episode`` refuses a recorded ``insufficient_evidence`` label. WO-022's agent
detail 1 proposed letting an undecided label that repeats identically pass; the owner vetoed it on
2026-11-08 (``approvals-20261108T081923998845Z-b8daa5a7``). So an episode whose recorded label is
``insufficient_evidence`` always fails the gate, with the reason category ``insufficient_evidence``,
and is listed among the skipped by that reason. Definite failures, planning failures included, are
kept when they pass the replay.

Every verdict carries a ``category`` (``CATEGORIES``), so a recording's exclusions are counted by
reason.
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

UNDECIDED = "insufficient_evidence"
# Agent detail 1 was vetoed by the owner: an undecided label never passes the gate.
UNDECIDED_POLICY = (
    "insufficient_evidence refused and listed by reason "
    "(owner veto of WO-022 agent detail 1, approvals-20261108T081923998845Z-b8daa5a7)"
)
PASSED = "passed"
CATEGORIES = (PASSED, UNDECIDED, "repeats", "tolerance", "label_changed", "replay_invalid")
GATE_REPEATS = 3
GATE_MAX_DEVIATION = 0.001
# sim/replay.py's reason for refusing a faithful replay of an undecided recording, which the gate
# keeps refusing (owner veto of agent detail 1); a test checks the text still matches sim/replay.py.
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
    category: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "passed": self.passed,
            "reason": self.reason,
            "category": self.category,
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


def decide(report: ReplayReport) -> GateResult:
    """The gate's verdict from a replay report.

    Fails, in this order: a recorded ``insufficient_evidence`` label (the owner's veto of agent
    detail 1), whatever its repeats did; a replay that did not run ``GATE_REPEATS`` times; a repeat
    past the tolerance; a repeat whose label differs from the recorded one; and any other replay
    ``sim.replay`` declares invalid, with its reason. Only a replay ``sim.replay`` declares valid
    passes, so a definite failure, a planning failure included, is kept when it replays faithfully.
    """
    tolerance = report.tolerance
    labels = [result.outcome_label for result in report.repeats]
    deviations = [result.max_deviation for result in report.repeats]
    undecided = report.recorded_label == UNDECIDED

    def result(passed: bool, reason: str, category: str) -> GateResult:
        return GateResult(
            report.episode_id,
            passed,
            reason,
            report.recorded_label,
            labels,
            deviations,
            undecided,
            category,
        )

    if undecided:
        return result(False, f"recorded label {UNDECIDED}: {UNDECIDED_POLICY}", UNDECIDED)
    if len(report.repeats) != GATE_REPEATS:
        return result(False, f"{len(report.repeats)} repeats, not {GATE_REPEATS}", "repeats")
    for repeat in report.repeats:
        if not repeat.max_deviation <= tolerance.max_state_deviation:
            return result(
                False,
                f"repeat {repeat.repeat} deviated {repeat.max_deviation} on {repeat.worst_stream} "
                f"at step {repeat.worst_step}; tolerance {tolerance.max_state_deviation}",
                "tolerance",
            )
        if repeat.outcome_label != report.recorded_label:
            return result(
                False,
                f"repeat {repeat.repeat} gave {repeat.outcome_label}; "
                f"recorded {report.recorded_label}",
                "label_changed",
            )
    if report.claim_valid:
        return result(True, "3 repeats within tolerance, each with the recorded label", PASSED)
    return result(False, report.reason, "replay_invalid")


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
