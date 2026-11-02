# WO-014 — Diagnose why the pilot predictor did not learn the cube

**Status:** passed
**Date:** 2026-11-01 · **Author:** claude-code-vishwaroop · **Work order:** WO-014 · **Phase:** M1 · **Protocol version:** `m0-protocol-2`, `evals/M1-exit-tests.json` sha256 `145858ec1ff0f1d259e24756b832f2ce2ffe3497a0a769d799f5008d70388f07`, `evals/M1-definitions.json` sha256 `389b6dd9602911aa4dfa82a7244b05f0318523dea4d6a5d91b598e9e9c402e21`
**Program link:** PROGRAM §5.2 → vishwaroop M1

> Four words with fixed meanings throughout this report: **measured** (ran here, evidence attached), **estimated** (arithmetic from stated assumptions), **mocked/fixture** (fabricated for tests), **not run**.

## 1. Claim and scope
**The cube failure had two causes, and fixing both clears 20% on the seed holdout but not on two of the four families held out whole.** All numbers are **measured**, in simulation, on the train partition. None is ET-M1-1 evidence.

| Question | Answer |
|---|---|
| Q1, does the nominal model carry a grasped cube? | **No.** The pilot's nominal holds the cube still. |
| Q2, does cube error differ by phase? | **Yes, by orders of magnitude.** At horizon 10, `hold` is 0.12 mm while the cube rests, 14.03 mm while held and 18.75 mm through a release. |
| Q3, is the structure the cause? | **Yes by the frozen rule, but it is only part of the cause.** Carrying alone takes the worst cube reduction from -73.9% to 22.1%. Changing the loss alone takes it to 38.4%. Both take it to 50.2%. |
| What WO-004 scales | **`carry-contact-beta`**, by the frozen rule. Its worst value at 30 epochs is 40.9%, on the joints at horizon 1. |

**Three findings change what WO-004 should do:**
1. **More epochs is not the lever.** From 30 to 100 epochs, the worst value moves from 40.9% to 42.2%. The cube improves at short horizons only.
2. **Whole-family generalization is the risk.** With `missed-grasp` held out, the worst reductions are -46.1% on the joints and -220.2% on the cube. With `early-release` held out, the cube reaches only 4.2% to 17.3%.
3. **Normalized joint numbers misled.** One joint with a 0.009 rad spread dominated them. `hold`'s worst joint reduction is -0.3% normalized and 38.5% in radians. So the joints were never failing on this holdout, and WO-012's joint table should not be read as a radian result.

## 2. Frozen method
The method and decision rule are in `work_orders/WO-014-m1-cube-prediction-diagnosis.md`, written before any trained result. Thresholds are unchanged. Train data only: `pilot_data.load_train` refuses a dev seed, and no dev or sealed data was loaded.

- **Data.** 260 train episodes. The seed holdout is the 26 with seeds divisible by 10, as in WO-012, leaving 234 to fit.
- **Model.** WO-012's: a 3-member residual ensemble, 3 hidden layers of 256, 10-step rollout loss, batch 256, 35,192 windows per epoch.
- **Baselines.** Constant, linear, the holding nominal and the carrying nominal. Every reduction is against the lowest of the four at that horizon, so fixing the nominal raises the bar.
- **Metric.** Root mean square error in the stream's own units, as `evals/M1-definitions.json` requires. Cube values are also given as 3D distance in millimetres, which leaves the reduction unchanged.

**Added after seeing results, and labelled as additions in the work order:** `hold-beta` and `carry-beta`; the four family holdouts; the uncertainty first look; recording joints in radians. The frozen rule was first applied to normalized joints, the only form then recorded. Section 4 applies it in radians, and the choice is the same.

## 3. Reproduction
```bash
python -m vishwaroop.models.cube_study --manifest artifacts/manifests/m0-dataset-v1.json
python -m vishwaroop.models.cube_study --manifest artifacts/manifests/m0-dataset-v1.json \
    --variants hold,hold-beta,carry-beta,carry-contact-beta
python -m vishwaroop.models.cube_study --manifest artifacts/manifests/m0-dataset-v1.json \
    --variants hold,carry-contact-beta --epochs 100
python -m vishwaroop.models.cube_study --manifest artifacts/manifests/m0-dataset-v1.json \
    --variants carry-contact-beta --seeds 0,1 --holdout-family m0-scripted-<family>
```
Run from the repository root in the robotics environment. Stack: `config/stack-lock.resolved.v2.json`, sha256 `f8db517142b3d720192fa51e23965d6637667d90c492519764503d79f6da19be`, torch 2.15.0, M3 Pro on MPS. Dataset manifest sha256 `267d77ead98119715350f0fc82987e715f7ce41a4d0337401b7469206711b9c7`. Results are in `artifacts/manifests/m1-cube-diagnosis-v1.json`.

| Run | Commit, clean | Purpose |
|---|---|---|
| `20261101T224248Z_7c4fbe9a` | `fea948a` | the five frozen variants, 30 epochs |
| `20261102T001718Z_55717241` | `21b917e` | `hold`, `hold-beta`, `carry-beta`, `carry-contact-beta`, 30 epochs, radians |
| `20261102T005324Z_e7094bcb` | `dc8b5d0` | `hold`, `carry-contact-beta`, 100 epochs, radians |
| `20261102T003457Z_120ddf18` | `a7a8eaf` | `noisy-actions` held out |
| `20261102T003926Z_07e55083` | `4854786` | `wrong-place` held out |
| `20261102T004402Z_2aa4f9fb` | `7a2b9a9` | `missed-grasp` held out |
| `20261102T004842Z_95139598` | `c3c1f6b` | `early-release` held out |
| `20261101T231526Z_f3c0c1ed`, `...232428Z_85bfb825`, `...232915Z_b8eeca11`, `...233408Z_df1f18eb`, `...233903Z_91ddd301`, `...234402Z_6325b5b5` | clean | the same comparisons before radians were recorded; `runs/` only |
| `20261101T224235Z_07d8b8e4` | dirty | stopped because the tree was dirty, not evidence |
| `20261101T224120Z_a6b0af1d`, `20261101T231407Z_a92092e5` | not used | short trials, not evidence |

**Reproducibility.** Six repeated variant and run pairs gave cube errors identical to the recorded precision on this machine (maximum difference 0.0 mm). That says nothing about another machine.

## 4. Results
**Where the cube's motion is, all 260 train episodes, no training.** One step, using the true next joints.

| Step phase | Steps | Share of steps | Share of squared cube motion | Hold, rms mm | Carry, rms mm |
|---|---:|---:|---:|---:|---:|
| `resting` | 25,160 | 59.4% | 0.0% | 0.004 | 1.755 |
| `moved_before_grasp` | 1,051 | 2.5% | 1.0% | 0.887 | 1.167 |
| `flag_turns_on` | 207 | 0.5% | 0.1% | 0.716 | 0.732 |
| `held` | 15,557 | 36.7% | 69.1% | 1.883 | 0.182 |
| `flag_turns_off` | 162 | 0.4% | 2.2% | 3.317 | 2.744 |
| `moved_after_grasp` | 203 | 0.5% | 27.5% | 10.400 | 10.478 |

Carrying explains the held cube, which is 69.1% of its squared motion. It cannot explain the fall after release, which is 27.5% of that motion in 0.5% of the steps.

**`object_position` reduction against the best baseline, seed holdout, seeds 0, 1 and 2.** Mean across seeds; the last column is the worst seed and horizon.

| Variant, 30 epochs unless stated | h1 | h2 | h3 | h5 | h8 | h10 | Worst |
|---|---:|---:|---:|---:|---:|---:|---:|
| `hold` | -24.5% | -29.1% | -36.2% | -50.3% | -66.7% | -73.5% | -73.9% |
| `hold-contact` | -24.3% | -28.8% | -35.9% | -50.0% | -66.2% | -72.9% | -73.4% |
| `carry` | 22.3% | 24.1% | 26.0% | 27.7% | 27.7% | 27.4% | 22.1% |
| `carry-contact` | 22.5% | 24.3% | 26.3% | 28.2% | 28.6% | 28.5% | 22.4% |
| `hold-beta` (added) | 38.9% | 51.9% | 60.9% | 67.2% | 70.2% | 71.5% | 38.4% |
| `carry-beta` (added) | 51.7% | 62.2% | 71.6% | 75.8% | 76.8% | 77.3% | 50.2% |
| `carry-contact-beta` | 51.5% | 61.7% | 71.3% | 75.4% | 76.3% | 76.8% | 50.5% |
| `hold`, 100 epochs | -26.6% | -31.7% | -39.3% | -54.5% | -72.3% | -79.9% | -80.1% |
| `carry-contact-beta`, 100 epochs | 68.4% | 72.7% | 74.7% | 75.3% | 74.9% | 75.1% | 68.2% |

**`joint_position` reduction, in radians, same holdout.** `hold-contact`, `carry` and `carry-contact` were **not run** in radians. They cannot change the choice, because their cube values already cap them at 22.4% or below.

| Variant, 30 epochs unless stated | h1 | h2 | h3 | h5 | h8 | h10 | Worst |
|---|---:|---:|---:|---:|---:|---:|---:|
| `hold` | 38.6% | 43.8% | 48.3% | 55.0% | 60.9% | 62.8% | 38.5% |
| `hold-beta` (added) | 40.7% | 45.9% | 50.5% | 57.5% | 63.9% | 66.5% | 40.4% |
| `carry-beta` (added) | 40.7% | 45.9% | 50.4% | 57.3% | 63.8% | 66.4% | 40.5% |
| `carry-contact-beta` | 40.9% | 46.0% | 50.5% | 57.3% | 63.8% | 66.4% | 40.9% |
| `hold`, 100 epochs | 39.6% | 43.8% | 48.0% | 54.6% | 60.6% | 62.5% | 37.6% |
| `carry-contact-beta`, 100 epochs | 42.3% | 46.6% | 50.7% | 57.5% | 64.1% | 66.7% | 42.2% |

For contrast, normalized joint reductions at 30 epochs are 1.0% to 48.0% for `hold` and 48.4% to 82.5% for `carry-contact-beta`. Joint index 4, counting from 0, has a standard deviation of 0.009 rad and the others 0.13 to 0.36 rad, so normalizing gives it far more weight than its radians.

**Cube error by phase, seed holdout, 30 epochs, mean across seeds, mm at h1 / h10.**

| Window phase | Windows | Carrying nominal, no residual | `hold` | `carry` | `carry-contact-beta` | Its share of squared error at h10 |
|---|---:|---:|---:|---:|---:|---:|
| `resting` | 2,044 | 0.00 / 0.01 | 0.01 / 0.12 | 0.01 / 0.11 | 0.04 / 0.27 | 0.02 |
| `moved_before_grasp` | 177 | 0.26 / 1.96 | 0.25 / 1.75 | 0.25 / 1.74 | 0.28 / 2.09 | 0.12 |
| `grasp_onset` | 210 | 0.39 / 7.30 | 0.34 / 5.99 | 0.34 / 5.45 | 0.35 / 2.87 | 0.28 |
| `held` | 1,416 | 1.10 / 5.53 | 1.61 / 14.03 | 0.26 / 0.62 | 0.23 / 0.60 | 0.08 |
| `release` | 160 | 1.06 / 18.58 | 1.88 / 18.75 | 0.84 / 17.31 | 0.94 / 3.92 | 0.39 |
| `moved_after_grasp` | 21 | 10.48 / 16.03 | 10.48 / 15.89 | 10.50 / 16.45 | 5.93 / 5.46 | 0.10 |
| All windows | 4,028 | 1.03 / 5.36 | 1.28 / 9.30 | 0.80 / 3.89 | 0.50 / 1.25 | 1.00 |

**The decision rule.**
- **Q3:** every carrying variant beat `hold` on all three seeds at every horizon in the first run, and `carry-contact-beta` did so at 100 epochs. `carry` and `carry-contact` were not part of the second run.
- **What WO-004 scales**, the worst value across seeds, horizons and the two required streams, in own units: `carry-contact-beta` 40.9%, `carry-beta` 40.5%, `hold-beta` 38.4%, `carry-contact` at most 22.4%, `carry` at most 22.1%, the two holding Gaussian variants negative. The first-applied normalized form gives the same choice, 45.2% against 44.9%.
- **The contact input earns nothing measurable.** The rule names `carry-contact-beta` by 0.4 points, within what these runs can distinguish, and it costs no measurable time.

**Whole families held out, `carry-contact-beta`, 30 epochs, seeds 0 and 1.** Added after the first run. Mean at h1 and h10, then the worst seed and horizon, in own units. The best baseline is recomputed on each family.

| Held out | Fit / held-out episodes | Joints h1 | Joints h10 | Joints worst | Cube h1 | Cube h10 | Cube worst | Clears 20% on both? |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `noisy-actions` | 220 / 40 | 43.2% | 82.0% | 43.1% | 41.8% | 68.6% | 41.7% | yes |
| `wrong-place` | 230 / 30 | 83.9% | 90.1% | 83.8% | 39.3% | 83.9% | 38.8% | yes |
| `missed-grasp` | 230 / 30 | -41.0% | 6.7% | -46.1% | -57.7% | -208.2% | -220.2% | **no, both streams** |
| `early-release` | 230 / 30 | 72.6% | 81.6% | 72.2% | 4.3% | 17.6% | 4.2% | **no, the cube** |

Holding out `no-release`, `timeout` and `nominal` was **not run**. The four above were picked before any family result.

**Uncertainty, a first look, across all horizons. Not ET-M1-3 evidence; its streams are not frozen.** Rank correlation of predicted standard deviation with absolute error, and coverage of the 90% interval.

| Holdout, model | Joints: correlation | Joints: coverage | Cube: correlation | Cube: coverage |
|---|---:|---:|---:|---:|
| Seed, `hold`, 30 epochs | 0.58 to 0.70 | 0.97 | 0.78 to 0.83 | 0.94 |
| Seed, `carry-contact-beta`, 30 epochs | 0.63 to 0.65 | 0.97 | 0.67 to 0.76 | 0.96 to 0.97 |
| Seed, `carry-contact-beta`, 100 epochs | 0.61 to 0.63 | 0.95 | 0.70 to 0.73 | 0.92 to 0.94 |
| `noisy-actions` held out, 30 epochs | 0.65 to 0.70 | 0.86 to 0.87 | 0.68 to 0.77 | 0.86 to 0.87 |
| `wrong-place` held out, 30 epochs | 0.54 to 0.60 | 0.98 | 0.71 to 0.75 | 0.97 to 0.98 |
| `missed-grasp` held out, 30 epochs | 0.76 to 0.77 | 0.84 to 0.86 | 0.85 to 0.86 | 0.80 to 0.87 |
| `early-release` held out, 30 epochs | 0.59 to 0.64 | 0.97 | 0.71 to 0.78 | 0.95 |

The chosen variant's cube correlation is about 0.1 lower than `hold`'s on the seed holdout. Those errors are also much smaller, so the two rows are not measuring the same thing. Coverage is above 90% on the seed holdout and falls to 80% to 87% on two whole families, which is the direction that matters for planning and worth checking in ET-M1-3.

## 5. Failure analysis
**Why `hold` learned nothing about the cube.** Its all-phase error at h10 is 9.30 mm, against 9.71 mm for its own nominal with no residual, and more training did not help: 9.64 to 9.66 mm at 100 epochs. The Gaussian loss can absorb hard phases by raising predicted variance rather than fitting the mean, and beta-NLL exists to limit that. The results fit that account, but I did not test the mechanism directly.

**The two fixes do different work.** Carrying fixes `held`, from 14.03 to 0.62 mm at h10, and leaves `release` at 17.31 mm. The loss change is what reaches `release`, at 3.92 mm. `hold-beta` shows the loss alone also improves `held`, to 1.38 to 1.47 mm, though less than carrying does.

**`missed-grasp` held out.** This is the only family with no grasp, so 95% of its windows are `resting`.
- At h10, 88% and 87.7% of the squared cube error, on seeds 0 and 1, is in `resting` windows: 6.52 mm and 6.01 mm where the true cube barely moves.
- Using the true flag only reduces the cube from 6.76 to 5.88 mm and from 6.25 to 4.77 mm, so a wrong flag is not the whole cause. The residual moves the cube as well.
- Its joints reach further than most families': joint index 1 down to -0.483 rad and index 2 up to 0.900 rad, against -0.17 and 0.59 rad for most families, with `wrong-place` the closest at -0.403 and 0.811. I did not test why the joint prediction fails there.

**`early-release` held out.** Release windows are 90% of the squared cube error at h10, at 33.63 mm on seed 0. The cube moves up to 29.9 mm in a step in this family, and at most 12.9 mm in any other. Its 99.9th percentile step is 28.4 mm, against at most 5.8 mm elsewhere. Without this family, the model has almost never seen a fall that fast. Its baseline is hard too: the carrying nominal's release error is 38.29 mm.

**The remaining joint error on the seed holdout** is mostly joint index 1: 0.0025 rad at h1 for the learned model and 0.0025 rad for the nominal, and 0.0063 rad for both at h10. No variant improves it. That joint sets the worst value of 40.9%. Its nominal error at h1 is about seven to eight times larger on `missed-grasp` than on the other held-out families, which suggests the cause, but I did not test it.

**What this means for ET-M1-1.** Dev's families are `dev-grasp-offset`, `dev-noisy-actions` and `dev-place-offset` (`artifacts/manifests/m0-dataset-v1.json`), and 11 of the 20 `dev-grasp-offset` episodes never lift the cube. Training for ET-M1-1 will include `missed-grasp` and `early-release`, so these holdouts are harder in one way than dev should be. They still show that a 50% seed-holdout result does not carry over to a behaviour missing from training. Nothing here predicts the dev result.

## 6. Cost and latency
$0: the owner's Mac, no line in `ledgers/costs.jsonl`. No GPU was rented. About 2.7 hours of machine time in total (**measured**, from the run ledger), within the 1-day bound.

| Variant | Seconds per epoch, MPS | 30 epochs, one seed |
|---|---:|---:|
| `hold`, `hold-beta` | 0.95 | 29 s |
| `hold-contact` | about 3 | about 90 s |
| The carrying variants | 4.9 to 5.4 | 130 to 165 s |

Carrying takes about 5 times as long, because of the forward kinematics in every rollout step. It stays practical: a 100-epoch `carry-contact-beta` seed took 490 to 650 s across the two runs. The per-seed time varied by about 30% on this shared machine.

**One run went over the 30-minute line.** The second 100-epoch run took 36.3 minutes, against 29.6 minutes for the same run earlier, so it was not projected to pass 30 and was not stopped. It did not stop or rely on resume, and `AGENTS.md §13.9` applies to the next one. WO-004's longer runs must resume.

## 7. Sealed access
None.

## 8. Exit tests and acceptance
This work order closes no exit test and touches no contract, so `AGENTS.md §13.8` asks for CI only.

| Exit test | Threshold (frozen) | Result | Evidence | Pass? |
|---|---|---|---|---|
| ET-M1-1 | `evals/M1-exit-tests.json`, with `evals/M1-definitions.json` | not run | this report is train-only | not run |

Also done, as the owner instructed on 2026-11-01:
- ET-M1-1's stricter reading is frozen in `evals/M1-definitions.json`.
- The state-based latent reading is recorded in WO-004, with the visual model staying in WO-013.
- The resume rule is `AGENTS.md §13.9`.
- WO-005's plan must estimate the GPU needs of M2a's observation model, and rents nothing.

**Not run:** any dev data; any exit test; a resumable run; three of the seven family holdouts; a free-fall term in the nominal; training past 100 epochs.

## 9. Limits
- **Train data and one simulator.** Nothing here extends to dev, sealed data or a physical arm.
- **Small seed holdout.** 26 episodes, with only 21 `moved_after_grasp` windows and 160 `release` windows, and no intervals. It shares families with the fit data.
- **Windows overlap.** Windows from one episode are correlated, so the window counts overstate the independent evidence.
- **Seeds share data.** They vary the initialization and batching, so seed-to-seed agreement says nothing about a different split.
- **Additions were chosen after seeing results.** The attribution variants and family holdouts are explanatory. Only the frozen variants were chosen under the rule.
- **Family holdouts have 2 seeds, at 30 epochs.** They were not run at 100 epochs, so more training could change them, though the seed holdout gives little reason to expect that.
- **A stronger baseline is a higher bar.** Whether `carry-contact-beta` clears 20% on dev against its carrying nominal is unknown.

## 10. Next bounded work order
**WO-004**, on the Mac, on `carry-contact-beta`, with three conditions now in the work order:
1. Measure every stream in its own units, with no normalized number deciding anything.
2. Before scaling and before any dev metric, run all seven train families held out, in radians and millimetres, and report them.
3. Make any run over 30 minutes resumable.

The results point at failure behaviours and the fall after release, rather than at more epochs. So WO-004 should test a free-fall term in the nominal against the same family holdouts before training longer. Rollback: reverting this work removes the study code and these documents, and changes no data, threshold or earlier result.

## 11. Retro note
Normalized error hid the joints' real state through WO-012 and most of this study. I should have recorded own units from the first run, since `evals/M1-definitions.json` had just been written that way, and doing so would have saved the 70-minute rerun. Size S was right: well inside the 1-day bound.

## Appendix
Code: `src/vishwaroop/models/cube_phases.py`, `src/vishwaroop/models/cube_study.py`; tests: `tests/test_cube_phases.py`, `tests/test_compute_pilot.py`.

## Errata (append-only)
