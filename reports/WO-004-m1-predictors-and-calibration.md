# WO-004 — M1 predictors on the Mac: nominal + residual ensemble, state-based latent model, calibration

**Status:** passed
**Date:** 2026-11-01 · **Author:** claude-code-vishwaroop · **Work order:** WO-004 · **Phase:** M1 · **Protocol version:** `m0-protocol-2`, `evals/M1-exit-tests.json` sha256 `145858ec1ff0f1d259e24756b832f2ce2ffe3497a0a769d799f5008d70388f07`, `evals/M1-definitions.json` sha256 `389b6dd9602911aa4dfa82a7244b05f0318523dea4d6a5d91b598e9e9c402e21`, `evals/M1-family-holdouts.json` sha256 `b7e0efa629ac16debd429449ab749ccfce228b0feb928ae71ab52f7b494ccc81`, `evals/M1-stage-b.json` sha256 `41a64cb136bd683ba840aee6e7ddb5d2bb3cfe025a6f746dd1619505074f7339`
**Program link:** PROGRAM §5.2 → vishwaroop M1

> Four words with fixed meanings throughout this report: **measured** (ran here, evidence attached), **estimated** (arithmetic from stated assumptions), **mocked/fixture** (fabricated for tests), **not run**.

## 1. Claim and scope
**ET-M1-1 and ET-M1-3 pass on 210 dev episodes under the frozen rules, in simulation. ET-M1-3's coverage passes by 0.03 of a point, and the model is weak in places the overall number hides.** All numbers are **measured**, on a simulated SO-100 under scripted controllers. Nothing here says anything about a physical arm.

| Exit test | Frozen requirement | Result |
|---|---|---|
| **ET-M1-1** | Each stream at least 20% below the lowest baseline, at every horizon 1 to 10 | **Passed.** Worst value 45.2%, on the cube at horizon 1, seed 2. Lowest interval bound anywhere 39.2%. |
| **ET-M1-3**, rank | Spearman at least 0.5, each stream, every horizon | **Passed.** Lowest 0.591, on the joints at horizon 1, seed 0. |
| **ET-M1-3**, coverage | Calibrated 90% interval covers 80% to 100%, each stream, every horizon | **Passed, barely.** Lowest 80.03%, on the joints at horizon 1, seed 0. |

**Four things the headline hides:**
1. **Coverage is on the floor, and calibrating made it worse.** The scales came from the 26 train-holdout episodes, where the intervals were too wide, so they shrank the intervals. Dev errors are larger, so calibrated joint coverage is 80.03% to 83.51%. Uncalibrated it would be 89.6% to 93.5%, closer to the 90% it claims. The frozen test uses calibrated coverage, so that is the result, and a 0.03-point margin is not a comfortable pass.
2. **`dev-grasp-offset`'s cube misses 20% at horizon 1 and from horizon 5 on,** down to 3.2% at horizon 10 on the worst seed. It is report-only and does not change the verdict. It is also the family nearest a failed grasp, which is where ET-M1-4's planner will need the model most.
3. **While a cube is resting or has just been pushed, the model is worse than a baseline on the cube.** A resting cube is 0.64 mm against 0.01 mm at horizon 10. The overall reduction comes from `held`, `release` and `grasp_onset`.
4. **The Spearman pass leans on pooling joints.** Within single joints, pooled over horizons, it runs from 0.34 to 0.69, and four of six joints are under 0.5 on at least two seeds. Joints differ in scale, which probably raises the pooled rank correlation; I did not test that. The frozen rule pools coordinates, so I applied it as frozen.

**Not done by this work order:** ET-M1-2, ET-M1-4 and ET-M1-5, which belong to WO-005. Phase M1 is still open.

**Stage A's decisions:** `carry-contact-beta` kept over `carry-beta`, narrowly, and the free-fall term adopted, both by rules frozen first. The epochs rule chose 30 over 100.

## 2. Frozen method
Every rule was committed before the result it governs.

| File | Committed before | Freezes |
|---|---|---|
| `evals/M1-exit-tests.json`, `evals/M1-definitions.json` | any M1 result; any dev metric | thresholds; ET-M1-1's streams and own units |
| `evals/M1-family-holdouts.json`, at `fc0da6b` | the sweep | family results are report-only; the contact and free-fall rules |
| `evals/M1-stage-b.json`, `evals/M1-dev-topup-plan.json`, at `a0efb2a` | any dev metric, the top-up, the 100-epoch runs, the latent runs | final variant, epochs rule, top-up, ET-M1-3's reading, one scoring |

- **Model.** `carry-contact-beta-fall`: lag nominal, a cube carried with the gripper and falling after release, a contact input, a 3-member residual ensemble, beta-NLL at 0.5, 30 epochs, seeds 0, 1 and 2. Each seed is its own ensemble, and each must pass, so the worst seed decides.
- **Data.** 234 train episodes to fit, 26 to calibrate, and 210 dev episodes in three families never used in train. No sealed data exists in M1.
- **Baselines.** Constant, linear, and all three nominals: holding, carrying, carrying with fall. Counting all of them can only make ET-M1-1 harder.
- **ET-M1-3's reading.** The owner asked for its streams to be frozen like ET-M1-1's. I also chose to require every horizon, the stricter reading, before computing any per-horizon value.
- **One scoring.** `m1_evaluate.py` is the only code that reads a dev episode for a predictor. Its models and dev set are fixed in the code, and it refuses to run once a result exists. Nothing was changed after seeing dev.
- **The latent model is report-only,** so dev does not choose between two predictors.

## 3. Reproduction
```bash
F=m0-scripted-early-release,m0-scripted-missed-grasp,m0-scripted-no-release,m0-scripted-noisy-actions,m0-scripted-nominal,m0-scripted-timeout,m0-scripted-wrong-place
M=artifacts/manifests/m0-dataset-v1.json
python -m vishwaroop.models.family_sweep --manifest $M --holdouts $F --variants carry-contact-beta
python -m vishwaroop.models.family_sweep --manifest $M --holdouts m0-scripted-missed-grasp --variants carry-beta
python -m vishwaroop.models.family_sweep --manifest $M --holdouts m0-scripted-early-release --variants carry-contact-beta-fall
python -m vishwaroop.models.family_sweep --manifest $M --holdouts seed --variants carry-contact-beta,carry-contact-beta-fall
python -m vishwaroop.models.family_sweep --manifest $M --holdouts $F --variants carry-contact-beta-fall
python -m vishwaroop.models.family_sweep --manifest $M --holdouts seed,m0-scripted-early-release,m0-scripted-missed-grasp --variants carry-contact-beta-fall --epochs 100
python -m vishwaroop.models.latent_predictor --manifest $M
python -m vishwaroop.sim.collect --config evals/M1-dev-topup-plan.json --partition dev --tolerance-file evals/M0-exit-tests.json --out data/derived/m1-dev-topup/<commit>
python -m vishwaroop.data.registry build --root data/derived/m1-dev-topup/<commit> --plan evals/M1-dev-topup-plan.json --out artifacts/manifests/m1-dev-topup-v1.json
python -m vishwaroop.models.m1_evaluate
```
Run from the repository root in the robotics environment. Stack: `config/stack-lock.resolved.v2.json`, sha256 `f8db517142b3d720192fa51e23965d6637667d90c492519764503d79f6da19be`, torch 2.15.0, M3 Pro on MPS. `m1_evaluate` refuses to run a second time, so repeating it needs a new work order. `make check` passes.

| Artifact | sha256 |
|---|---|
| `artifacts/manifests/m0-dataset-v1.json` | `267d77ead98119715350f0fc82987e715f7ce41a4d0337401b7469206711b9c7` |
| `artifacts/manifests/m1-dev-topup-v1.json` | `0e3a19e8bb365fa8673b97b9b3e84c04122e3a36231c61c82edb2e8612b736e9` |
| `artifacts/manifests/m1-dev-evaluation-v1.json`, the scorer's output unchanged | `f326b81c99cc8fcddb03d149bc72a2f3a1359f837a3c7a5653b7d22c61275d1f` |
| `artifacts/manifests/m1-stage-a-v1.json` | `91942b373973164f7a219b35d17642c529f66b63540c58329f4554d03b69dce1` |
| `artifacts/manifests/m1-stage-b-train-v1.json` | `1b244cd9a7b727a9ffb1ebc73ea704b19d9b02a0e9ca9da25864efefda21c44c` |

| Run | Commit, clean | Purpose |
|---|---|---|
| `20261102T023457Z_62dee862` | `fc0da6b` | first sweep, killed on purpose after 420 s; ledger shows `started` only |
| `20261102T024157Z_3d1d1d32` | `8ea808c` | that sweep, resumed |
| `20261102T034042Z_b4c20c44` | `454c8a3` | `carry-beta` on `missed-grasp` |
| `20261102T034919Z_49f39d62` | `07b019c` | free fall on `early-release` |
| `20261102T035805Z_ddb5d0d0` | `425f2fb` | seed holdout with and without free fall; **the scored ensembles** |
| `20261102T041509Z_93dd348c` | `85663fd` | repeated sweep with free fall |
| `20261102T051607Z_15ed0a5e` | `a0efb2a` | unbroken cell, to test the resume on MPS |
| `20261102T051845Z_06b8d0e0` | `d85051f` | latent model; **the scored latent models** |
| `20261102T052738Z_64aeceff` | `fb1f2f1` | 100 epochs, for the epochs rule |
| `20261102T065334Z_e91733c1` | `1a25a85` | dev top-up |
| `20261102T071247Z_13f62861` | `a1128fc` | **the one dev scoring** |

**Models scored at a later commit.** The scored models were trained at earlier commits than the scorer. The scorer recomputes each model's train-holdout numbers first and refuses any difference over 1 part in 100,000, and all passed. A dry run of the scorer on train data, with the holdout standing in for dev, gave reductions equal to the recorded ones with a difference of 0.0.

## 4. Results
### ET-M1-1, ensemble, 210 dev episodes, 35,310 windows
Own units, per coordinate. The interval resamples whole episodes and does not decide the test.

| Stream | Horizon | Lowest baseline | Learned, worst seed | Reduction, worst seed | 95% interval, that seed | Best seed |
|---|---|---|---|---|---|---|
| joints | 1 | 1.892 mrad | 0.973 mrad | **48.6%** | 42.5% to 55.0% | 49.0% |
| joints | 2 | 2.892 mrad | 1.310 mrad | **54.7%** | 46.9% to 63.6% | 55.0% |
| joints | 3 | 3.686 mrad | 1.530 mrad | **58.5%** | 50.3% to 67.9% | 58.9% |
| joints | 4 | 4.339 mrad | 1.696 mrad | **60.9%** | 53.0% to 69.9% | 61.4% |
| joints | 5 | 4.885 mrad | 1.832 mrad | **62.5%** | 55.1% to 70.8% | 63.0% |
| joints | 6 | 5.342 mrad | 1.948 mrad | **63.5%** | 56.5% to 71.1% | 64.1% |
| joints | 7 | 5.730 mrad | 2.048 mrad | **64.3%** | 57.6% to 71.4% | 64.8% |
| joints | 8 | 6.059 mrad | 2.137 mrad | **64.7%** | 58.4% to 71.4% | 65.3% |
| joints | 9 | 6.337 mrad | 2.220 mrad | **65.0%** | 59.0% to 71.2% | 65.7% |
| joints | 10 | 6.571 mrad | 2.296 mrad | **65.1%** | 59.3% to 71.1% | 65.8% |
| cube | 1 | 0.466 mm | 0.255 mm | **45.2%** | 41.3% to 48.8% | 45.7% |
| cube | 2 | 0.744 mm | 0.367 mm | **50.6%** | 46.8% to 54.5% | 51.0% |
| cube | 3 | 0.985 mm | 0.476 mm | **51.6%** | 46.6% to 56.4% | 52.1% |
| cube | 4 | 1.195 mm | 0.583 mm | **51.2%** | 45.7% to 56.4% | 51.9% |
| cube | 5 | 1.388 mm | 0.693 mm | **50.1%** | 44.3% to 55.7% | 50.9% |
| cube | 6 | 1.573 mm | 0.805 mm | **48.8%** | 42.8% to 54.8% | 49.7% |
| cube | 7 | 1.756 mm | 0.916 mm | **47.8%** | 41.6% to 54.0% | 48.7% |
| cube | 8 | 1.941 mm | 1.028 mm | **47.1%** | 40.5% to 53.6% | 48.0% |
| cube | 9 | 2.132 mm | 1.141 mm | **46.5%** | 39.9% to 53.2% | 47.5% |
| cube | 10 | 2.329 mm | 1.257 mm | **46.0%** | 39.2% to 52.9% | 47.0% |

Reported only: `object_grasped` RMSE is 0.078 to 0.170 for seed 0, against a best baseline of 0.100 to 0.306.

### ET-M1-3, ensemble
Rank is unaffected by the per-horizon scale. A scale is the multiple of predicted std used as the interval.

| Stream | Horizon | Spearman, lowest seed | Calibrated coverage, seed range | Uncalibrated coverage, seed range | Scale, seed range |
|---|---|---|---|---|---|
| joints | 1 | 0.591 | 80.03% to 81.03% | 92.6% to 93.5% | 0.52 to 0.59 |
| joints | 2 | 0.612 | 80.70% to 82.00% | 92.5% to 93.4% | 0.74 to 0.83 |
| joints | 3 | 0.616 | 81.28% to 82.45% | 92.3% to 93.3% | 0.86 to 0.95 |
| joints | 4 | 0.618 | 81.39% to 82.61% | 92.0% to 93.0% | 0.93 to 1.02 |
| joints | 5 | 0.621 | 81.25% to 82.96% | 91.5% to 92.5% | 0.97 to 1.07 |
| joints | 6 | 0.625 | 81.16% to 83.20% | 91.1% to 92.0% | 0.99 to 1.11 |
| joints | 7 | 0.628 | 81.06% to 83.15% | 90.6% to 91.5% | 1.01 to 1.14 |
| joints | 8 | 0.633 | 81.22% to 83.29% | 90.2% to 91.3% | 1.03 to 1.17 |
| joints | 9 | 0.637 | 81.14% to 83.38% | 89.9% to 90.9% | 1.04 to 1.19 |
| joints | 10 | 0.641 | 81.29% to 83.51% | 89.6% to 90.6% | 1.06 to 1.21 |
| cube | 1 | 0.678 | 83.54% to 84.87% | 94.2% to 94.9% | 0.42 to 0.46 |
| cube | 2 | 0.708 | 83.88% to 84.83% | 93.3% to 94.2% | 0.66 to 0.71 |
| cube | 3 | 0.727 | 83.29% to 84.68% | 92.7% to 93.4% | 0.79 to 0.86 |
| cube | 4 | 0.738 | 83.08% to 84.13% | 92.0% to 92.7% | 0.90 to 0.93 |
| cube | 5 | 0.742 | 83.15% to 84.24% | 91.2% to 92.0% | 0.98 to 1.03 |
| cube | 6 | 0.740 | 83.19% to 84.25% | 90.2% to 91.2% | 1.07 to 1.12 |
| cube | 7 | 0.736 | 83.23% to 84.60% | 89.2% to 90.2% | 1.18 to 1.23 |
| cube | 8 | 0.731 | 83.05% to 84.43% | 88.0% to 89.1% | 1.29 to 1.30 |
| cube | 9 | 0.726 | 83.74% to 85.67% | 86.6% to 87.9% | 1.43 to 1.46 |
| cube | 10 | 0.723 | 84.15% to 86.06% | 85.3% to 86.7% | 1.55 to 1.59 |

### Dev families, ensemble, worst seed, percent reduction, report-only
| Dev family | Stream | h1 | h2 | h3 | h4 | h5 | h6 | h7 | h8 | h9 | h10 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `dev-grasp-offset` | joints | 26.4 | 30.9 | 34.8 | 37.8 | 39.7 | 40.9 | 41.5 | 41.7 | 41.6 | 41.3 |
| `dev-grasp-offset` | cube | 17.9 | 30.2 | 25.9 | 21.9 | 17.5 | 13.4 | 10.1 | 7.4 | 5.2 | 3.2 |
| `dev-noisy-actions` | joints | 52.6 | 63.2 | 69.2 | 72.2 | 73.8 | 74.7 | 75.4 | 76.0 | 76.5 | 77.0 |
| `dev-noisy-actions` | cube | 43.3 | 49.2 | 52.4 | 54.0 | 54.9 | 55.9 | 57.2 | 58.7 | 60.2 | 61.6 |
| `dev-place-offset` | joints | 80.7 | 83.0 | 84.2 | 84.5 | 84.8 | 85.3 | 85.7 | 86.1 | 86.5 | 86.7 |
| `dev-place-offset` | cube | 40.0 | 53.5 | 64.0 | 70.8 | 75.0 | 75.7 | 76.3 | 76.8 | 77.4 | 78.0 |

### Phases, ensemble, worst seed, report-only
Each stream's RMSE per coordinate, against the lowest baseline in that phase. Phases have no reduction, because a resting cube's baseline can be 0.

| Phase | Windows | Cube h1, model / best baseline (mm) | Cube h10, model / best baseline (mm) | Joints h1, model / best baseline (mrad) | Joints h10, model / best baseline (mrad) |
|---|---|---|---|---|---|
| `resting` | 19,427 | 0.02 / 0.00 | 0.64 / 0.01 | 0.61 / 1.43 | 1.07 / 4.52 |
| `moved_before_grasp` | 1,865 | 0.44 / 0.34 | 3.23 / 1.84 | 2.48 / 2.81 | 7.40 / 6.74 |
| `grasp_onset` | 1,760 | 0.51 / 0.50 | 2.45 / 4.84 | 1.65 / 2.05 | 4.13 / 7.86 |
| `held` | 10,146 | 0.28 / 0.74 | 0.55 / 2.91 | 0.77 / 2.30 | 1.14 / 9.30 |
| `release` | 1,653 | 0.53 / 0.81 | 2.83 / 5.88 | 0.85 / 1.97 | 2.01 / 4.99 |
| `moved_after_grasp` | 459 | 0.74 / 0.74 | 2.39 / 1.53 | 2.45 / 3.01 | 5.73 / 5.87 |

### Latent model, report-only
A recurrent state-space model on state observations, 179,226 parameters, with observation-update and imagination modes. It decides nothing, and its numbers do not choose a predictor.

| Measure | Joints | Cube |
|---|---|---|
| Worst reduction, any seed and horizon | 54.4% | 49.9% |
| Lowest Spearman | 0.480 | 0.617 |
| Calibrated coverage, range | 82.1% to 86.6% | 81.6% to 87.9% |
| Uncalibrated coverage, range | 78.8% to 87.6% | 78.4% to 91.7% |

It would clear ET-M1-1's threshold, and its worst value is higher than the ensemble's. Its rank would not clear ET-M1-3: 0.480 on the joints at horizon 1, seed 1. It is a single model per seed, so its uncertainty has no disagreement between members. Its calibrated coverage is also further from the floor, 81.6% to 87.9%, and its `dev-grasp-offset` cube is less weak, 13.1% at horizon 10 against the ensemble's 3.2%. None of this changes which model was scored, because dev does not choose. Its nominal structure is the same as the ensemble's, which is probably much of why it does well.

| Dev family | Stream | h1 | h2 | h3 | h4 | h5 | h6 | h7 | h8 | h9 | h10 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `dev-grasp-offset` | joints | 24.4 | 29.6 | 34.3 | 38.2 | 41.3 | 43.6 | 45.3 | 46.3 | 47.0 | 47.3 |
| `dev-grasp-offset` | cube | 19.6 | 34.4 | 32.3 | 30.5 | 28.0 | 24.9 | 21.7 | 18.6 | 15.7 | 13.1 |
| `dev-noisy-actions` | joints | 64.8 | 69.9 | 72.8 | 74.4 | 75.5 | 76.4 | 77.1 | 77.6 | 78.0 | 78.3 |
| `dev-noisy-actions` | cube | 50.7 | 51.6 | 53.1 | 54.5 | 55.9 | 57.1 | 58.3 | 59.3 | 60.1 | 60.7 |
| `dev-place-offset` | joints | 79.1 | 82.9 | 84.2 | 84.4 | 84.3 | 84.5 | 84.9 | 85.3 | 85.6 | 85.8 |
| `dev-place-offset` | cube | 35.1 | 53.8 | 64.2 | 70.6 | 74.7 | 75.4 | 76.0 | 76.6 | 77.2 | 77.6 |

### Stage A, train data: decisions
Each rule was frozen in `evals/M1-family-holdouts.json` before its result. Own units throughout. Every reduction is against the lowest of five baselines at that horizon: constant, linear, and the holding, carrying and carrying-with-fall nominals.

| Question | Rule's answer | What decided it |
|---|---|---|
| Does `carry-beta` replace `carry-contact-beta`, on `missed-grasp` held out? | **No, `carry-contact-beta` stays.** Neither is better by the rule. | `carry-beta` is lower on the cube at every horizon on all three seeds, and on the joints at every horizon on seeds 1 and 2. On seed 0 its joints are higher at horizons 8, 9 and 10 (6.41, 6.64, 6.86 mrad against 6.33, 6.32, 6.34), so it fails "every horizon, all three seeds". |
| Is the free-fall term adopted? | **Yes.** `carry-contact-beta-fall`. | (a) On `early-release` held out, cube RMSE is lower at all 10 horizons on all 3 seeds. (b) The worst seed-holdout value rises by 10.0 points, from 30.9% to 40.9%, so it does not fall by more than 2. |

**Contact.** Contact is not the missing signal on `missed-grasp`. `carry-contact-beta` already had it and missed, and removing it does not make things worse: the worst values are -16.8% to -18.7% on the joints and -146.7% to -184.8% on the cube without it, against -36.0% to -48.8% and -199.0% to -249.1% with it. The rule still keeps contact, narrowly, and I applied it as frozen.

**Free fall.** The term is what `early-release` lacked. At horizon 10 on that holdout, cube RMSE per coordinate goes from 4.9 to 2.9 mm, and 3D cube error in the `moved_after_grasp` phase goes from about 21.5 to 5.2 mm. The worst reduction goes from -143.9% to 12.1%. That -143.9% is against the new fall baseline: it was 4.2% in WO-014 against the old baselines, and the model's error did not change. The baseline alone beats the model at short horizons there, which is why it counts. On the seed holdout the term is what lifts the worst cube value above 50%, from 30.9% to 56.5%.

### Stage A, train data: every family, worst seed, percent reduction

`carry-contact-beta` (run `20261102T024157Z_3d1d1d32`):

| Family held out | Stream | h1 | h2 | h3 | h4 | h5 | h6 | h7 | h8 | h9 | h10 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `early-release` | joints | 72.2 | 74.0 | 75.9 | 77.4 | 78.6 | 79.7 | 80.5 | 80.8 | 80.5 | 80.3 |
| `early-release` | cube | -143.9 | -39.4 | -13.1 | -4.5 | 0.4 | 4.0 | 6.9 | 9.6 | 12.0 | 14.0 |
| `missed-grasp` | joints | -48.8 | -30.1 | -32.7 | -30.9 | -24.6 | -17.6 | -11.8 | -7.4 | -4.3 | -2.2 |
| `missed-grasp` | cube | -72.1 | -98.2 | -126.0 | -152.1 | -173.5 | -191.7 | -208.1 | -223.1 | -236.7 | -249.1 |
| `no-release` | joints | 72.3 | 80.5 | 81.6 | 82.2 | 82.9 | 83.8 | 84.6 | 85.3 | 85.7 | 86.1 |
| `no-release` | cube | 25.9 | 51.6 | 65.2 | 72.8 | 77.8 | 78.2 | 78.3 | 78.3 | 78.4 | 78.6 |
| `noisy-actions` | joints | 42.8 | 58.1 | 67.6 | 73.2 | 76.3 | 78.4 | 79.7 | 80.6 | 81.4 | 81.9 |
| `noisy-actions` | cube | 40.4 | 53.4 | 60.1 | 63.6 | 65.4 | 66.2 | 66.8 | 67.0 | 67.5 | 67.9 |
| `nominal` | joints | 78.5 | 81.0 | 82.5 | 83.3 | 84.0 | 84.6 | 85.2 | 85.7 | 86.0 | 86.2 |
| `nominal` | cube | 27.9 | 48.8 | 60.7 | 68.4 | 73.6 | 74.4 | 74.8 | 75.2 | 75.4 | 75.6 |
| `timeout` | joints | 75.9 | 81.7 | 83.6 | 84.6 | 85.7 | 87.1 | 88.3 | 89.0 | 89.5 | 89.8 |
| `timeout` | cube | 28.0 | 52.5 | 65.6 | 73.2 | 78.2 | 81.4 | 82.2 | 82.4 | 82.7 | 83.1 |
| `wrong-place` | joints | 83.8 | 85.7 | 86.9 | 87.6 | 88.0 | 88.6 | 89.0 | 89.3 | 89.5 | 89.8 |
| `wrong-place` | cube | 38.8 | 59.0 | 69.7 | 76.4 | 80.9 | 81.8 | 82.2 | 82.7 | 83.2 | 83.8 |

`carry-contact-beta-fall`, the repeated sweep (run `20261102T041509Z_93dd348c`):

| Family held out | Stream | h1 | h2 | h3 | h4 | h5 | h6 | h7 | h8 | h9 | h10 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `early-release` | joints | 72.4 | 74.7 | 76.9 | 78.4 | 79.7 | 80.9 | 81.9 | 82.2 | 82.3 | 82.5 |
| `early-release` | cube | 29.5 | 12.1 | 12.3 | 17.0 | 24.4 | 31.7 | 37.6 | 42.2 | 45.9 | 49.0 |
| `missed-grasp` | joints | -62.9 | -40.6 | -42.2 | -40.2 | -36.4 | -30.5 | -24.4 | -19.0 | -14.7 | -11.5 |
| `missed-grasp` | cube | -57.9 | -88.3 | -123.8 | -155.3 | -178.3 | -194.4 | -206.5 | -217.1 | -227.1 | -237.1 |
| `no-release` | joints | 74.0 | 81.8 | 82.8 | 83.4 | 84.1 | 84.9 | 85.6 | 86.1 | 86.5 | 86.8 |
| `no-release` | cube | 33.0 | 55.0 | 66.0 | 72.5 | 77.2 | 77.4 | 77.3 | 77.2 | 77.2 | 77.2 |
| `noisy-actions` | joints | 42.1 | 57.3 | 66.8 | 72.3 | 75.5 | 77.6 | 78.9 | 79.9 | 80.6 | 81.2 |
| `noisy-actions` | cube | 42.4 | 54.5 | 60.9 | 64.2 | 65.9 | 66.9 | 67.5 | 67.8 | 68.2 | 68.6 |
| `nominal` | joints | 78.7 | 81.0 | 82.3 | 83.1 | 83.8 | 84.4 | 85.0 | 85.5 | 85.9 | 86.1 |
| `nominal` | cube | 35.2 | 50.0 | 61.8 | 69.2 | 74.4 | 75.4 | 75.8 | 76.1 | 76.5 | 76.9 |
| `timeout` | joints | 75.7 | 81.5 | 83.3 | 84.3 | 85.2 | 86.5 | 87.6 | 88.3 | 88.8 | 89.2 |
| `timeout` | cube | 27.4 | 51.4 | 64.2 | 71.4 | 76.5 | 79.9 | 80.7 | 81.0 | 81.3 | 81.6 |
| `wrong-place` | joints | 83.1 | 85.0 | 86.3 | 87.0 | 87.5 | 88.0 | 88.4 | 88.7 | 89.0 | 89.2 |
| `wrong-place` | cube | 44.9 | 60.2 | 70.2 | 76.5 | 80.8 | 81.6 | 82.0 | 82.4 | 82.8 | 83.2 |

**What the sweep says.** Five of seven families clear 20% everywhere with or without the term. `early-release` misses on the cube at horizons 2 to 4, even with the term. `missed-grasp` is far below every baseline on both streams, and the term leaves it there: its cube goes from -249.1% to -237.1% and its joints from -48.8% to -62.9%. Almost all of its windows have a resting cube, where the holding nominal's error is 0.0 mm and the model's is 4.72 to 6.86 mm at horizon 10. The predicted flag explains only part of that: with the true flag as the gate, the error is still 3.37 to 5.27 mm, so most of it comes from the residual moving a cube that is not moving. The family-holdout `missed-grasp` models are not the final models, which fit on `missed-grasp` too.

**M3 link, for later, with no M3 work here.** These out-of-family failures motivate M3, synthetic failure data: `docs/PHASES.md`, `docs/SYNTHETIC_DATA_M3.md`. A predictor that has not seen a failure type does much worse than a baseline on it.

**Resume, measured.** The first sweep was stopped by `kill -9` after 420 s, with 2 cells finished and a third at epoch 5. It resumed at `20261102T024157Z_3d1d1d32`, reused those 2 cells, and continued the third from epoch 5. Seeds 0 and 1 on the four families WO-014 ran reproduce their RMSE with a difference of exactly 0.0, on both streams. The killed run `20261102T023457Z_62dee862` stays in the ledger as `started` with no finish, on purpose.

### Stage B, train side, before any dev metric
Frozen in `evals/M1-stage-b.json`, sha256 `41a64cb136bd683ba840aee6e7ddb5d2bb3cfe025a6f746dd1619505074f7339`, at `a0efb2a`, before these runs. Numbers: `artifacts/manifests/m1-stage-b-train-v1.json`.

**Epochs: 30, by the frozen rule.** Worst value, taking the worst seed, horizon and required stream:

| Holdout | 30 epochs | 100 epochs | Higher at 100? |
|---|---|---|---|
| Seed holdout | 40.90% | 42.03% | yes |
| `early-release` | 12.09% | 13.08% | yes |
| `missed-grasp` | -237.11% | -470.44% | **no** |

100 epochs needed to be higher on all three. It gains about a point on two and makes the unseen failure family's cube about twice as bad, so WO-014's finding stands: more epochs is not the lever, and on an unseen family it does harm. The models to score are the 30-epoch seed-holdout ensembles of `20261102T035805Z_ddb5d0d0`.

**Resume on MPS.** An unbroken run of the cell the kill stopped (`early-release`, seed 2, run `20261102T051607Z_15ed0a5e`) equals the resumed one with a difference of exactly 0.0 on both streams.

**Latent model, seed holdout, 30 epochs, report-only.** Worst reduction against the same baselines: joints 40.5% to 40.9% and cube 54.2% to 55.6% across seeds (run `20261102T051845Z_06b8d0e0`, 179,226 parameters, about 6 s per epoch). It keeps the nominal structure underneath, so this is mostly that structure's result.

**Dev top-up.** 150 episodes, seeds 8020 to 8069 of the three dev families, run `20261102T065334Z_e91733c1`, in about 1 minute, 56 MB, 9 sampled replays valid with maximum deviation 0.0. Manifest `artifacts/manifests/m1-dev-topup-v1.json`, sha256 `0e3a19e8bb365fa8673b97b9b3e84c04122e3a36231c61c82edb2e8612b736e9`. Its labels were seen, as a collection check, and no predictor metric was. The registry reports `et_m0_6_counts_met: false` for this set alone, because 150 is under M0's 200. This set claims nothing under M0.

**Review before scoring.** Because dev is scored once, the full independent review ran before scoring, on a clean clone at `1d79a00`. It found no fault in the metric or verdict arithmetic, which it checked end to end on fabricated data against a separate calculation. It did find that the command line could have scored the 100-epoch models the rule rejects, that a result file on disk did not stop a second scoring, that phase tables had no baselines, and four smaller things. All were fixed before scoring.

## 5. Failure analysis
- **Where the model is weakest on dev.** `dev-grasp-offset`'s cube: 17.9% at horizon 1, 30.2% at horizon 2, then down to 3.2% at horizon 10. 43 of its 70 dev episodes ended with the cube never lifted, so the cube often stays down where a nearby trajectory would have carried it. I did not test that explanation.
- **Where it is worse than a baseline.** At horizon 10: `resting`, `moved_before_grasp` and `moved_after_grasp` on the cube, and `moved_before_grasp` on the joints. At horizon 1: `moved_before_grasp` on the cube, 0.44 against 0.34 mm. They are 62% of windows, so the overall pass does not mean every state is predicted better.
- **Why coverage came out low.** Scales from 26 in-family episodes are below 1.645 at every joint horizon on all three seeds, so they narrow the interval. Dev is out of family, and errors are larger there. Scales from a family holdout might suit dev better. That is a hypothesis for later and was not tried, because any trial would use dev evidence.
- **Out of family, on train.** See Stage A: `missed-grasp` held out is far below baselines. That is the M3 link above.

## 6. Cost and latency
$0: the owner's Mac, no paid compute, nothing in `ledgers/costs.jsonl`. Ledger times, all **measured**: first sweep 7 minutes to the kill and 59 after it; contact 8; free fall 8; seed holdout 17; repeated sweep 55; unbroken cell 3; latent 9; 100 epochs 85; top-up 1; dev scoring 40 seconds. About 4 hours of machine time in all. An ensemble or a latent model costs about 5 to 6 s per epoch. Latency for control was not measured.

## 7. Sealed access
None.

## 8. Exit tests and acceptance
| Exit test | Threshold (frozen) | Result | Evidence | Pass? |
|---|---|---|---|---|
| ET-M1-1 | ≥ 20% below the best baseline, horizons 1 to 10, each required stream, ≥ 200 dev episodes | worst 45.2%, 210 episodes | `20261102T071247Z_13f62861`; `artifacts/manifests/m1-dev-evaluation-v1.json` | yes |
| ET-M1-3 | Spearman ≥ 0.5; 90% interval coverage within ±10 points, each required stream, every horizon, ≥ 200 dev episodes | lowest Spearman 0.591; coverage 80.03% to 86.06% | same | yes, at the floor |
| ET-M1-2, ET-M1-4, ET-M1-5 | as frozen | **not run** | WO-005 | no |

**Review.** `AGENTS.md §13.8` requires a full independent review, because this closes exit tests. It ran on a clean clone before scoring. Its recheck is in the PR.

## 9. Limits
- **Simulation only.** A simulated SO-100 under scripted controllers, not the owner's SO-101. No claim about any physical arm, about closed-loop control, or about whole-episode success.
- **Dev is scripted.** Its failures are offsets of scripted plans, and it says nothing about failure types the train data lacks.
- **One scoring, one block.** Dev is seed block 8, seeds 8000 to 8069. ET-M1-4's suite also uses blocks 8 and 9, under separate families.
- **Dev has now been seen.** Any change made because of this report needs fresh dev evidence.
- **Reproducibility.** Equal results across processes on this machine, MPS. Nothing about another machine.
- **Not done, on purpose:** the visual latent model (WO-013); calibrating on family holdouts; M3.

## 10. Next bounded work order
WO-005, planner and action-chunk scorer, for ET-M1-2, ET-M1-4 and ET-M1-5. No owner decision is needed to start it, and its plan carries the M2a GPU estimate. It should use `carry-contact-beta-fall`, knowing that a resting or nudged cube and failed grasps are its weak states. Rollback: reverting this PR removes the code and evals. Runs and data stay where they are.

## 11. Retro note
Reviewing before the one scoring paid off: it found that the command line could have scored the rejected 100-epoch models. A new stronger baseline changed earlier reductions without the model changing, which would have been easy to misread without the 0.0-difference check. One mechanism I first wrote from intuition, that the predicted flag explained the `missed-grasp` error, was wrong when checked against the true-flag diagnostic. Size: L, as estimated; about 4 hours of machine time.

## Errata (append-only)
- **2026-11-02, information only; nothing above is changed.**
  - **Calibration.** On the owner's instruction, interval scales were refitted on a held-out calibration split that is not training data. Dev was split in two by seed within each family, and each half's scales were applied to the other. Calibrated coverage is then 89.9% to 90.0% on both streams and all seeds (run `20261102T085011Z_27167da9`). ET-M1-3 stays as recorded above, at 80.03% to 86.06%. The recorded scales came from 26 episodes held out from fitting, but from the train families, which is why they were too narrow for dev.
  - **Resting or nudged cube.** WO-005 now uses a "free cube stays put" model, `carry-contact-beta-fall-still-reach`, in which a grasp counts only within 15 mm. Its known gap is reported in `reports/WO-005-m1-planner-and-chunk-scorer.md`.
- **2026-11-02, disclosure; nothing above is changed.** The predictor's 13 state values include `object_grasped`, which `sim/env.py` declares `reference_only`. The model takes it as an input and predicts it (the reach and stays-put gates read it too). `docs/EVALUATION_PROTOCOL.md` keeps reference streams out of policy inputs for experiments that claim independence. Nothing here claims independence, but a real controller would not have this signal. WO-005's review found it, and the owner is asked whether to accept it for M1 (`reports/WO-005-m1-planner-and-chunk-scorer.md`, section 10).

