# WO-004 | M1 predictors on the Mac: nominal + residual ensemble, state-based latent model, calibration
**Phase:** M1
**Exit tests advanced:** ET-M1-1, ET-M1-3
**Size:** L (milestone-level stub; expand into full detail when it becomes the next WO)
**Prerequisites:** phase M0 `passed`; `evals/M1-exit-tests.json` frozen (WO-001 step 7); WO-012's compute split accepted; WO-014 accepted, and its findings reported to the owner before training is scaled.
**Authorization:** AGENTS §2.1 only: it runs on the owner's M3 Pro. Any paid GPU time would need §2.3 approval and a new estimate from a measured need (`docs/BUDGET_AND_LAUNCHER.md`).
**Files:** `src/vishwaroop/models/`, `tests/`, `evals/M1-*`, `reports/WO-004-m1-predictors-and-calibration.md`, ignored `runs/`, `artifacts/sha256/`.

## Objective
Train and evaluate the first predictors on the M0 dataset: a nominal-dynamics-plus-learned-residual ensemble (3 members) in state space, then a compact recurrent latent model on state observations; report multi-step error versus horizon against constant/linear and nominal baselines, and calibrate uncertainty against actual error. The visual version of the latent model moved to WO-013, because no exit test needs it (`reports/WO-012-m1-compute-split.md`).

## Scope
Data loaders over contract episodes (train/dev only; sealed untouched); baselines; ensemble training with seeds recorded; latent model with observation-update and imagination modes; multi-step rollout evaluation at horizons 1..H; calibration analysis; a frozen plan that brings `dev` to at least the 200 episodes ET-M1-1 and ET-M1-3 require (M0 has 60), collected before any dev metric is computed; run time per experiment in the report.

ET-M1-1's streams are frozen in `evals/M1-definitions.json`, the stricter reading, by owner decision. Before any dev result, freeze ET-M1-3's streams the same way. A state-based latent model satisfies M1's "compact latent predictor" (owner decision, 2026-11-01). Any run over 30 minutes must be resumable (`AGENTS.md §13.9`).

WO-014 chose what this scales: `carry-contact-beta`, the carrying nominal with the contact input and beta-NLL at 0.5 (`reports/WO-014-m1-cube-prediction-diagnosis.md`). Three conditions follow from it. Every stream is measured in its own units, and no normalized number decides anything, because one joint with a 0.009 rad spread dominates the normalized joint error. Before scaling and before any dev metric, run each of the seven train families held out whole, and report them: `missed-grasp` and `early-release` missed 20% when held out. Before training longer, test a free-fall term in the nominal against those holdouts, because 100 epochs barely moved the worst value and the fall after release is the largest remaining cube error.

## Out of scope
Planner, scorer, evaluator, synthetic data, real data, the visual latent model (WO-013), any threshold change after results are seen.

## Verification
Commands and expected results are written when this WO is expanded. Minimum: `make check`; training runs created via `core.runs.new_run_dir`; dev metrics tables with intervals; calibration table; all run ids and hashes in the report.

## Stop conditions
Missing frozen thresholds; paid compute without approval; dev-set leakage detected by `audit_splits.py`; any need to use sealed data.

## Report
`reports/WO-004-m1-predictors-and-calibration.md`
