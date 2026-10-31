# WO-004 | M1 predictors: nominal + residual ensemble, compact latent model, calibration
**Phase:** M1
**Exit tests advanced:** ET-M1-1, ET-M1-3
**Size:** L (milestone-level stub; expand into full detail when it becomes the next WO)
**Prerequisites:** phase M0 `passed`; `evals/M1-exit-tests.json` frozen (WO-001 step 7); GPU access with an approval line if rented.
**Authorization:** §2.3 approval required for any paid GPU time (measured pilot first, `docs/BUDGET_AND_LAUNCHER.md`).
**Files:** `src/world_model/models/`, `tests/`, `evals/M1-*`, `reports/WO-004-m1-predictors-and-calibration.md`, ignored `runs/`, `artifacts/sha256/`.

## Objective
Train and evaluate the first predictors on the M0 dataset: a nominal-dynamics-plus-learned-residual ensemble (3 members) in state space, then a compact recurrent latent model with a frozen visual encoder; report multi-step error versus horizon against constant/linear and nominal baselines, and calibrate uncertainty against actual error.

## Scope
Data loaders over contract episodes (train/dev only; sealed untouched); baselines; ensemble training with seeds recorded; latent model with observation-update and imagination modes; multi-step rollout evaluation at horizons 1..H; calibration analysis; one measured GPU pilot before any longer run; cost per experiment in the ledger.

## Out of scope
Planner, scorer, evaluator, synthetic data, real data, any threshold change after results are seen.

## Verification
Commands and expected results are written when this WO is expanded. Minimum: `make check`; training runs created via `core.runs.new_run_dir`; dev metrics tables with intervals; calibration table; all run ids and hashes in the report.

## Stop conditions
Missing frozen thresholds; paid compute without approval; dev-set leakage detected by `audit_splits.py`; any need to use sealed data.

## Report
`reports/WO-004-m1-predictors-and-calibration.md`
