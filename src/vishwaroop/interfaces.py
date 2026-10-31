"""Typed interfaces for the modules the work orders implement.

These are ``Protocol`` classes: they fix the shape, units and failure behaviour of each component so
that work orders implement against a stable contract and tests can use fakes. Nothing here is a
working model. Every implementation must:

- state units and frames of every array in its docstring (the contract's action_spec is the source);
- return uncertainty alongside predictions, never a bare point estimate;
- be able to abstain (return ``None`` or raise ``InsufficientEvidenceError``) outside its validated
  range;
- never hold command authority: outputs are proposals and scores, consumed by a caller that decides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class InsufficientEvidenceError(Exception):
    """Raised when a component's inputs are outside the range it was validated on."""


@dataclass(frozen=True)
class Prediction:
    """A multi-step prediction with per-step uncertainty.

    ``mean`` and ``std`` are lists indexed by horizon step; each entry is a list of floats in the
    units declared by ``units`` (one label per dimension, matching the episode's stream or action
    labels). ``horizon_dt_ns`` is the step length. ``model_id`` names the exported manifest.
    """

    mean: list[list[float]]
    std: list[list[float]]
    units: list[str]
    horizon_dt_ns: int
    model_id: str
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChunkScore:
    """Scores for one candidate action chunk from one observed history.

    All scores are in [0, 1] unless stated. ``abstained`` is True when the scorer declined to score
    because the inputs were outside its validated range; the other fields are then None.
    """

    progress: float | None
    clearance_margin: float | None  # metres; None if not applicable to the embodiment
    constraint_violation_prob: float | None
    uncertainty: float | None
    abstained: bool
    reason: str


@dataclass(frozen=True)
class EvaluationResult:
    """Closed-loop evaluation of one policy checkpoint on one task suite (M2)."""

    checkpoint_id: str
    training_run_id: str
    predicted_success: float | None  # None when abstained
    interval_low: float | None
    interval_high: float | None
    abstained: bool
    n_imagined_episodes: int
    judge_id: str  # the independent success judge's identity, never the training reward's
    notes: str


@runtime_checkable
class Predictor(Protocol):
    """Action-conditioned state or latent predictor (M1)."""

    def predict(self, history: dict[str, Any], actions: list[list[float]]) -> Prediction:
        """Predict consequences of ``actions`` (one list per step, action_spec units) after history.

        ``history`` carries the observed streams up to decision time, in contract-v1 shapes. Must
        raise ``InsufficientEvidenceError`` when history or actions are outside the validated range.
        """


@runtime_checkable
class Planner(Protocol):
    """Sampling MPC over a Predictor (M1). Returns a proposal, never a command."""

    def plan(
        self, history: dict[str, Any], goal: dict[str, Any]
    ) -> tuple[list[list[float]], dict[str, Any]]:
        """Return (action_sequence, diagnostics).

        Diagnostics include cost terms, uncertainty penalty, candidates evaluated and wall time.
        Admissibility (limits, clearance) is also checked by the caller; the planner must never emit
        actions outside action_spec bounds.
        """


@runtime_checkable
class ChunkScorer(Protocol):
    """Open-loop action-chunk scorer (M1). Scores chunks; makes no full-episode success claim."""

    def score(self, history: dict[str, Any], chunk: list[list[float]]) -> ChunkScore: ...


@runtime_checkable
class SuccessJudge(Protocol):
    """Independent task-outcome judge; shares no weights, labels or code with a training reward."""

    def judge(self, episode_dir: str) -> tuple[bool | None, str]:
        """Return (success, evidence_note); ``None`` means the evidence does not decide."""


@runtime_checkable
class ObservationModel(Protocol):
    """Action-conditioned observation rollout reproducing every input a policy expects (M2a)."""

    def step(self, state: dict[str, Any], action: list[float]) -> dict[str, Any]:
        """Advance one control step; return the next observation packet in the policy's exact format
        (image resolution and history, proprioception, instruction persistence, timing)."""


@runtime_checkable
class PolicyEvaluator(Protocol):
    """Closed-loop evaluator over an ObservationModel and a SuccessJudge (M2)."""

    def evaluate(self, checkpoint_ref: dict[str, Any], suite_id: str) -> EvaluationResult: ...


@runtime_checkable
class TrajectoryGenerator(Protocol):
    """Synthetic-demonstration generation on matched scenes (M3, pipeline B)."""

    def generate(self, scene_ref: dict[str, Any], instruction: str, n: int) -> list[str]:
        """Return directories of ``imagined`` episodes whose provenance names the parent scene and
        generator. Replay-checking them is a separate step that writes new physics_sim episodes."""
