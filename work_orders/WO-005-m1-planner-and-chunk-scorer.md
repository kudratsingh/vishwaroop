# WO-005 | M1 planner (CEM MPC) and action-chunk scorer with simulator-branch validation
**Phase:** M1
**Exit tests advanced:** ET-M1-2, ET-M1-4, ET-M1-5
**Size:** L (milestone-level stub; expand when next)
**Prerequisites:** WO-004 accepted; frozen task suite and baselines from `evals/M0-protocol.md`; WO-012's compute split accepted.
**Authorization:** AGENTS §2.1 only: planner runs and simulator branches run on the owner's M3 Pro on CPU physics. Any paid GPU time would need §2.3 approval and a new estimate from a measured need.
**Files:** `src/vishwaroop/planning/`, `src/vishwaroop/scoring/`, `src/vishwaroop/sim/branches.py`, `tests/`, `reports/WO-005-m1-planner-and-chunk-scorer.md`.

## Objective
Build the sampling MPC planner over the learned and nominal models, the simulator-branch protocol (restore an initial state, execute ≥ 2 alternative action chunks through physics), and the action-chunk scorer with abstention; compare planners on the frozen suite with matched interaction budgets; validate the scorer against executed branches. Make no full-episode VLA claim.

## Scope
`branches.py` (controlled counterfactual evidence in sim); CEM planner with bounded actions, known costs, uncertainty penalty, admissibility checks; nominal-model MPC baseline; scorer heads (progress, clearance, constraint violation, uncertainty) with an abstention rule; evaluation tables with Wilson intervals; latency and compute per decision; report.

## Out of scope
Closed-loop VLA evaluation (M2a), synthetic data (M3), real arm, drone logs.

## Verification
Written when expanded. Minimum: branch dataset manifest; ranking agreement ≥ frozen threshold or a reported negative; planner comparison table; scorer AUROC and abstention coverage; `make check`.

## Stop conditions
Thresholds not frozen; "constraint violation" (ET-M1-5) not defined in a frozen file before any scorer result, since no frozen file defines it today; planner exploiting predictor errors without the uncertainty penalty being reported; any attempt to present chunk scores as policy success.

## Report
`reports/WO-005-m1-planner-and-chunk-scorer.md`
