# WO-004 | M1 predictors on the Mac: nominal + residual ensemble, state-based latent model, calibration
**Phase:** M1
**Exit tests advanced:** ET-M1-1, ET-M1-3
**Size:** L (milestone-level stub; expand into full detail when it becomes the next WO)
**Prerequisites:** phase M0 `passed`; `evals/M1-exit-tests.json` frozen (WO-001 step 7); WO-012's compute split accepted.
**Authorization:** AGENTS §2.1 only: it runs on the owner's M3 Pro. Any paid GPU time would need §2.3 approval and a new estimate from a measured need (`docs/BUDGET_AND_LAUNCHER.md`).
**Files:** `src/vishwaroop/models/`, `tests/`, `evals/M1-*`, `reports/WO-004-m1-predictors-and-calibration.md`, ignored `runs/`, `artifacts/sha256/`.

## Objective
Train and evaluate the first predictors on the M0 dataset: a nominal-dynamics-plus-learned-residual ensemble (3 members) in state space, then a compact recurrent latent model on state observations; report multi-step error versus horizon against constant/linear and nominal baselines, and calibrate uncertainty against actual error. The visual version of the latent model moved to WO-013, because no exit test needs it (`reports/WO-012-m1-compute-split.md`).

## Scope
Data loaders over contract episodes (train/dev only; sealed untouched); baselines; ensemble training with seeds recorded; latent model with observation-update and imagination modes; multi-step rollout evaluation at horizons 1..H; calibration analysis; a frozen plan that brings `dev` to at least the 200 episodes ET-M1-1 and ET-M1-3 require (M0 has 60), collected before any dev metric is computed; run time per experiment in the report.

Before any dev result, freeze which streams ET-M1-1's RMSE and ET-M1-3's error cover and how they are combined. The frozen file does not say, and WO-012's pilot shows that it matters: joints and the cube behave very differently, and `target_position` never moves. This adds a definition and changes no threshold.

## Out of scope
Planner, scorer, evaluator, synthetic data, real data, the visual latent model (WO-013), any threshold change after results are seen.

## Verification
Commands and expected results are written when this WO is expanded. Minimum: `make check`; training runs created via `core.runs.new_run_dir`; dev metrics tables with intervals; calibration table; all run ids and hashes in the report.

## Stop conditions
Missing frozen thresholds; paid compute without approval; dev-set leakage detected by `audit_splits.py`; any need to use sealed data.

## Report
`reports/WO-004-m1-predictors-and-calibration.md`
