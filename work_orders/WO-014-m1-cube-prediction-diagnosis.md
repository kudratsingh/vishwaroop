# WO-014 | Diagnose why the pilot predictor did not learn the cube
**Phase:** M1
**Exit tests advanced:** none directly (decides the model structure WO-004 scales for ET-M1-1)
**Size:** S, at most 1 day (owner's bound)
**Prerequisites:** WO-012 accepted.
**Authorization:** AGENTS §2.1 only. The owner's Mac, no paid compute.
**Files:** `src/vishwaroop/models/`, `tests/test_cube_phases.py`, `evals/M1-definitions.json`, `work_orders/`, `docs/`, `AGENTS.md §13.9`, `START_HERE.md`, `artifacts/manifests/`, `reports/WO-014-m1-cube-prediction-diagnosis.md`, ignored `runs/`.

## Objective
Owner instruction, 2026-11-01: before training for ET-M1-1, run a bounded study of the cube failure WO-012 found. Does the nominal model carry a grasped cube with the gripper? Does cube error differ between grasped and free phases? Fix the model structure if that is the cause, and report before scaling training.

Also from the same instruction: record the stricter ET-M1-1 reading, the state-based latent reading, the resume rule for runs over 30 minutes, and the M2a estimate in WO-005's plan.

## Scope
Written before any trained result of this study. The first look at the data (no training) measured the step table in Method 1, and shaped the variants below.

### Method
1. **Step table, no training.** For every train transition: its phase, its share of the cube's squared motion, and the one-step error of holding the cube against moving it by the tool point's true displacement.
2. **Trained comparison.** Same data, loss form, optimizer, sizes and holdout as WO-012's predictor (26 train episodes chosen by seed), seeds 0, 1 and 2, in two runs of about 30 minutes each from one-epoch timings: first every variant at 30 epochs, then `hold` and the chosen variant at 100 epochs. All five at 100 epochs would take about 90 minutes (**estimated**) and tell the structure question little more, since WO-012 saw the cube unchanged from 30 to 300 epochs:

| Variant | Nominal | Inputs | Loss |
|---|---|---|---|
| `hold` | WO-012's: joint lag, cube held still | state, action, history | Gaussian NLL |
| `hold-contact` | same | adds cube minus tool point | Gaussian NLL |
| `carry` | the cube moves by the predicted tool displacement, scaled by the grasp flag | state, action, history | Gaussian NLL |
| `carry-contact` | same as `carry` | adds cube minus tool point | Gaussian NLL |
| `carry-contact-beta` | same as `carry` | adds cube minus tool point | beta-NLL, beta 0.5 |

3. **Baselines.** Constant, linear, the holding nominal, and the carrying nominal. A carrying nominal is a stronger baseline, so it counts in the best baseline: fixing the nominal must not make the learned model's job easier.
4. **Phases, per rollout window, from the true trajectory.** `resting`, `moved_before_grasp`, `moved_after_grasp`, `grasp_onset`, `held`, `release`. A move is a step of at least 0.1 mm. These labels are analysis only and are never model inputs.
5. **How much the flag matters.** Each carrying variant is also rolled out with the true flag as its gate. This is an upper bound for diagnosis, not a legitimate predictor or baseline.

### Added after the first run, on 2026-11-01
The first run gave `carry-contact-beta` a far larger gain than the question predicted, and the frozen table cannot say why, so these were added after seeing it. They are train-only, labelled as additions, and change neither the decision rule nor the frozen variants.
- **Attribution.** `hold-beta` and `carry-beta` at 30 epochs, seeds 0, 1 and 2, because beta-NLL was never tested without carrying and contact.
- **Whole families held out.** The chosen variant at 30 epochs, seeds 0 and 1, holding out each of `m0-scripted-noisy-actions`, `m0-scripted-wrong-place`, `m0-scripted-missed-grasp` and `m0-scripted-early-release`. The seed holdout shares families with the fit data, while ET-M1-1's dev set holds out whole families, so the seed holdout may flatter a model.
- **Uncertainty, a first look.** Rank correlation of predicted standard deviation against absolute error, and 90% interval coverage, by stream, because a changed loss can damage what ET-M1-3 measures. ET-M1-3's streams are not frozen, and this is not ET-M1-3 evidence.

### Decision rule
- **Q1, does the nominal carry?** Answered by the code and the step table.
- **Q2, does error differ by phase?** Answered by the per-phase table, in millimetres.
- **Q3, is the structure the cause?** Yes if, on all three seeds and in both runs, a carrying variant has lower all-phase `object_position` RMSE than `hold` at every horizon 1 to 10. Whatever the answer, report the reduction against the full best baseline, because that is what ET-M1-1 will measure.
- **What WO-004 scales:** the variant whose worst value is highest, taking the worst seed, the worst horizon and the worse of `joint_position` and `object_position`, at 30 epochs. If the best variant still misses 20% on this holdout, say so and name the remaining phase.

## Out of scope
Training past 100 epochs in this work order; dev or sealed data; an exit-test result; a threshold change; WO-004's models, top-up or calibration; renting a machine.

## Deliverables
`src/vishwaroop/models/cube_phases.py`, `src/vishwaroop/models/cube_study.py`, `artifacts/manifests/m1-cube-diagnosis-v1.json`, `evals/M1-definitions.json`, the updates to WO-004 and WO-005, and the report.

## Verification
`make check`, then `python -m vishwaroop.models.cube_study --manifest artifacts/manifests/m0-dataset-v1.json` from the repository root in the robotics environment, at a clean commit, and again with `--variants hold,<chosen> --epochs 100`. Expected: exit 0, `cube_study.json` in a new run directory, each run about 30 minutes. A run is simply repeated if it stops, so nothing here relies on resuming; a run projected well over 30 minutes stops and gets resume first. Negative tests: `tests/test_cube_phases.py` classifies fabricated trajectories into each phase, and shows that the carry error is near zero for a cube fixed to the tool and that an incomplete window is refused. A dev seed is refused by `pilot_data.load_train`, already tested.

## Exit criteria
Closes no exit test. Done when the report answers Q1 to Q3 and names what WO-004 scales. This work order closes no exit test and touches no contract, so `AGENTS.md §13.8` asks for CI only.

## Stop conditions
Any need for dev or sealed data, or for paid compute; a run projected well over 30 minutes without resume; memory pressure on the owner's machine; disk below 5 GB free; more than 1 day of agent time.

## Report
`reports/WO-014-m1-cube-prediction-diagnosis.md`
