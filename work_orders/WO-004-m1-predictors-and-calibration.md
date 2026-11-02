# WO-004 | M1 predictors on the Mac: nominal + residual ensemble, state-based latent model, calibration
**Phase:** M1
**Exit tests advanced:** ET-M1-1, ET-M1-3
**Size:** L (milestone-level stub; expand into full detail when it becomes the next WO)
**Prerequisites:** phase M0 `passed`; `evals/M1-exit-tests.json` frozen (WO-001 step 7); WO-012's compute split accepted; WO-014 accepted, and its findings reported to the owner before training is scaled.
**Authorization:** AGENTS §2.1 only: it runs on the owner's M3 Pro. Any paid GPU time would need §2.3 approval and a new estimate from a measured need (`docs/BUDGET_AND_LAUNCHER.md`).
**Files:** `src/vishwaroop/models/`, `src/vishwaroop/data/registry.py`, `tests/`, `evals/M1-*`, `work_orders/`, `docs/`, `START_HERE.md`, `artifacts/manifests/`, `reports/WO-004-m1-predictors-and-calibration.md`, ignored `runs/`, `artifacts/sha256/`.

## Objective
Train and evaluate the first predictors on the M0 dataset: a nominal-dynamics-plus-learned-residual ensemble (3 members) in state space, then a compact recurrent latent model on state observations; report multi-step error versus horizon against constant/linear and nominal baselines, and calibrate uncertainty against actual error. The visual version of the latent model moved to WO-013, because no exit test needs it (`reports/WO-012-m1-compute-split.md`).

## Scope
Data loaders over contract episodes (train/dev only; sealed untouched); baselines; ensemble training with seeds recorded; latent model with observation-update and imagination modes; multi-step rollout evaluation at horizons 1..H; calibration analysis; a frozen plan that brings `dev` to at least the 200 episodes ET-M1-1 and ET-M1-3 require (M0 has 60), collected before any dev metric is computed; run time per experiment in the report.

ET-M1-1's streams are frozen in `evals/M1-definitions.json`, the stricter reading, by owner decision. Before any dev result, freeze ET-M1-3's streams the same way. A state-based latent model satisfies M1's "compact latent predictor" (owner decision, 2026-11-01). Any run over 30 minutes must be resumable (`AGENTS.md §13.9`).

### Stage A, train data only, before scaling (owner, 2026-11-01)
The owner approved this order, on the Mac, at $0, with no M3 work. How family results are used is frozen in `evals/M1-family-holdouts.json`: report-only, with no per-family threshold, and ET-M1-1 stays exactly as frozen. That file also freezes the two rules below, before their results.
1. **Sweep.** `carry-contact-beta` with each of the seven train families held out whole, seeds 0, 1 and 2, 30 epochs, in own units. About 52 minutes (**estimated**, from WO-014's timings), so it is resumable, and a real stop is tested on it.
2. **Contact.** `carry-contact-beta` against `carry-beta`, holding out `missed-grasp`. Contact may be the missing signal there even though it added nothing on the seed holdout. `carry-contact-beta` already has that input and missed, so this can only show whether removing it makes things worse or better.
3. **Free fall.** The owner approved a free-fall nominal term, judged on the `early-release` holdout first. A released cube above the table keeps its last step and gains gravity (9.81 m/s², 50 ms control period), stopping at the 12.5 mm rest height, and only when it is more than 1 mm above that height. Its constants are physics and the protocol. The 1 mm margin and the choice to keep horizontal velocity came from a no-training look at train data with `early-release` excluded.
4. **Repeat the sweep** with any adopted variant, and report it the same way.

**Resume.** Every run over 30 minutes is resumable, no exceptions (`AGENTS.md §13.9`). A training run's unit is the epoch, and a sweep's finished unit is a holdout, variant and seed. `python -m vishwaroop.models.family_sweep --resume-from runs/<id>` refuses different settings or changed code under `src/`. Negative tests: `tests/test_family_sweep.py`, including that a resumed training equals an unbroken one, bit for bit, on CPU.

**The report must record** that the out-of-family failures motivate M3 (synthetic failure data), as a link for later (`docs/PHASES.md`, `docs/SYNTHETIC_DATA_M3.md`).

### Stage B, scaled training and the exit tests
Frozen in `evals/M1-stage-b.json` and `evals/M1-dev-topup-plan.json` before any dev metric, after stage A's report section was written: the final variant, the rule for the epochs, the dev top-up plan and ET-M1-3's streams. `src/vishwaroop/models/m1_evaluate.py` is the only code that reads dev for a predictor, requires that plan's hash, and scores once.

Order, each at a clean commit with the run ledger committed between:
1. **Epochs.** `carry-contact-beta-fall` at 100 epochs on the seed holdout, `early-release` and `missed-grasp`, about 80 minutes (**estimated**), resumable, and decided by the frozen rule. Also one unbroken `carry-contact-beta` on `early-release`, seed 2, because that cell is the one the hard kill stopped: comparing them tests a resume on MPS, where the unit test can only use CPU.
2. **Latent.** `python -m vishwaroop.models.latent_predictor --manifest artifacts/manifests/m0-dataset-v1.json`, seeds 0, 1 and 2, 30 epochs, resumable, train data only.
3. **Top-up.** `python -m vishwaroop.sim.collect --config evals/M1-dev-topup-plan.json --partition dev --tolerance-file evals/M0-exit-tests.json --out data/derived/m1-dev-topup/<commit>`, then `python -m vishwaroop.data.registry build --root data/derived/m1-dev-topup/<commit> --plan evals/M1-dev-topup-plan.json --out artifacts/manifests/m1-dev-topup-v1.json`. The registry exits 1 because 150 episodes are under ET-M0-6's 200, which this set does not claim. The manifest is still written and is what counts.
4. **Score dev, once.** `python -m vishwaroop.models.m1_evaluate`, with the arguments in its docstring.

WO-014 chose what this scales: `carry-contact-beta`, the carrying nominal with the contact input and beta-NLL at 0.5 (`reports/WO-014-m1-cube-prediction-diagnosis.md`). Three conditions follow from it. Every stream is measured in its own units, and no normalized number decides anything, because one joint with a 0.009 rad spread dominates the normalized joint error. Before scaling and before any dev metric, run each of the seven train families held out whole, and report them: `missed-grasp` and `early-release` missed 20% when held out. Before training longer, test a free-fall term in the nominal against those holdouts, because 100 epochs barely moved the worst value and the fall after release is the largest remaining cube error.

## Out of scope
Planner, scorer, evaluator, synthetic data, real data, the visual latent model (WO-013), any threshold change after results are seen.

## Verification
`make check`, then Stage A and Stage B's commands above. Expected: exit 0 from each training and scoring run, whether or not an exit test passes; dev metrics tables with intervals; a calibration table; all run ids and hashes in the report. Negative tests: `tests/test_family_sweep.py` and `tests/test_m1_evaluate.py`, including a changed plan, a second scoring, a train seed in dev, a repeated episode, too few episodes, an unfinished model, a missing stream, and a verdict one horizon short. The evaluator refuses a model that no longer reproduces its train-side numbers.

## Exit criteria
Done when the report gives ET-M1-1 and ET-M1-3 as passed or failed under the frozen rules, on at least 200 dev episodes, and carries the latent model's report-only tables and the M3 link. A miss is a finished result. It closes exit tests, so `AGENTS.md §13.8` requires a full independent review on a clean clone.

## Stop conditions
Missing frozen thresholds; paid compute without approval; dev-set leakage detected by `audit_splits.py`; any need to use sealed data.

## Report
`reports/WO-004-m1-predictors-and-calibration.md`
