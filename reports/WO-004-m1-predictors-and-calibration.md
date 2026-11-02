# WO-004 — M1 predictors on the Mac: nominal + residual ensemble, state-based latent model, calibration

**Status:** partial
**Date:** 2026-11-01 · **Author:** claude-code-vishwaroop · **Work order:** WO-004 · **Phase:** M1 · **Protocol version:** `m0-protocol-2`, `evals/M1-exit-tests.json` sha256 `145858ec1ff0f1d259e24756b832f2ce2ffe3497a0a769d799f5008d70388f07`, `evals/M1-definitions.json` sha256 `389b6dd9602911aa4dfa82a7244b05f0318523dea4d6a5d91b598e9e9c402e21`, `evals/M1-family-holdouts.json` sha256 `b7e0efa629ac16debd429449ab749ccfce228b0feb928ae71ab52f7b494ccc81`
**Program link:** PROGRAM §5.2 → vishwaroop M1

> Four words with fixed meanings throughout this report: **measured** (ran here, evidence attached), **estimated** (arithmetic from stated assumptions), **mocked/fixture** (fabricated for tests), **not run**.

## 1. Claim and scope
Stage A only so far. Stage A is **measured**, in simulation, on the train partition, and is report-only under `evals/M1-family-holdouts.json`. None of it is exit-test evidence. Stage B is **not run**.

## 4. Results

### Stage A: decisions
Each rule was frozen in `evals/M1-family-holdouts.json` before its result. Own units throughout. Every reduction is against the lowest of five baselines at that horizon: constant, linear, and the holding, carrying and carrying-with-fall nominals.

| Question | Rule's answer | What decided it |
|---|---|---|
| Does `carry-beta` replace `carry-contact-beta`, on `missed-grasp` held out? | **No, `carry-contact-beta` stays.** Neither is better by the rule. | `carry-beta` is lower on the cube at every horizon on all three seeds, and on the joints at every horizon on seeds 1 and 2. On seed 0 its joints are higher at horizons 8, 9 and 10 (6.41, 6.64, 6.86 mrad against 6.33, 6.32, 6.34), so it fails "every horizon, all three seeds". |
| Is the free-fall term adopted? | **Yes.** `carry-contact-beta-fall`. | (a) On `early-release` held out, cube RMSE is lower at all 10 horizons on all 3 seeds. (b) The worst seed-holdout value rises by 10.0 points, from 30.9% to 40.9%, so it does not fall by more than 2. |

**Contact.** Contact is not the missing signal on `missed-grasp`. `carry-contact-beta` already had it and missed, and removing it does not make things worse: the worst values are -16.8% to -18.7% on the joints and -146.7% to -184.8% on the cube without it, against -36.0% to -48.8% and -199.0% to -249.1% with it. The rule still keeps contact, narrowly, and I applied it as frozen.

**Free fall.** The term is what `early-release` lacked. At horizon 10 on that holdout, cube error goes from 4.9 to 2.9 mm, and in the `moved_after_grasp` phase from about 21.5 to 5.2 mm. The worst reduction goes from -143.9% to 12.1%. That -143.9% is against the new fall baseline: it was 4.2% in WO-014 against the old baselines, and the model's error did not change. The baseline alone beats the model at short horizons there, which is why it counts. On the seed holdout the term is what lifts the worst cube value above 50%, from 30.9% to 56.5%.

### Stage A: every family, worst seed, percent reduction

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
