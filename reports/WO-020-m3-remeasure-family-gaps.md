# WO-020 — M3: re-measure the family-holdout gaps under plain A, and pick M3's target family

**Status:** passed
**Date:** 2026-11-06 · **Author:** claude-code-vishwaroop · **Work order:** WO-020 · **Phase:** M3 · **Protocol version:** `evals/M3-remeasure.json` sha256 `133ae3c484868b4747ecc42d639a23c4d9b6f6bd7abe982ff857f373a9deada7`, recorded in the status ledger before the run
**Program link:** PROGRAM §8.3 → vishwaroop M3

> Four words with fixed meanings throughout this report: **measured** (ran here, evidence attached), **estimated** (arithmetic from stated assumptions), **mocked/fixture** (fabricated for tests), **not run**.

## 1. Claim and scope
**Under the current model (plain A), the −237% `missed-grasp` cube gap is gone: −0.5%. `missed-grasp` is still M3's target, by the frozen rule, because of its joints, at −62.9%.** That value is at horizon 1 and is unchanged by plain A. All values are **measured** on train data in simulation. The run reproduced WO-005 stage 0 exactly; as the freeze said in advance, it is not a blind re-measurement.

## 2. Frozen method
`evals/M3-remeasure.json`:
- **Model.** Plain A applied at inference to WO-004's family-holdout ensembles (`runs/20261102T041509Z_93dd348c`, seeds 0, 1 and 2, 30 epochs).
- **Holdouts.** Each of the seven train families held out in turn.
- **Metric.** WO-004's reductions against the lowest of five baselines.
- **Check.** All 420 values must reproduce `runs/20261102T085542Z_4764e650` within 1e-6 before the rule is applied.
- **Rule.** The target is whichever of `missed-grasp` and `early-release` has the lower worst reduction.

## 3. Reproduction
`python -m vishwaroop.models.m3_remeasure`, run `20261107T071013Z_ce7e7942` at `d3957a3`, clean, on MPS, in 39 s. Result: `artifacts/manifests/m3-remeasure-v1.json`, sha256 `4f37778a0c9ebdc7a3b6dba104e37f484012a29e3baaad4d9340dd24f1c1559b`.

## 4. Results
**Reproduction:** 420 of 420 values within 1e-6.

| Family held out | Worst reduction under plain A | Stream, horizon, seed |
|---|---|---|
| `missed-grasp` | **−62.9%** | joints, h1, seed 0 |
| `early-release` | 11.9% | cube, h2, seed 0 |
| `timeout` | 22.2% | cube, h1, seed 0 |
| `no-release` | 30.1% | cube, h1, seed 1 |
| `nominal` | 34.1% | cube, h1, seed 1 |
| `noisy-actions` | 42.1% | joints, h1, seed 2 |
| `wrong-place` | 43.2% | cube, h1, seed 0 |

**Target, by the frozen rule: `m0-scripted-missed-grasp`.** Its worst value is −62.9% on the joints, below `early-release`'s 11.9%. On the cube alone it would also be chosen: −0.5% against 11.9%.

**Where the target's remaining error sits.** Joint RMSE at horizon 1, seed 0:
- `moved_before_grasp`: 7.1 mrad, over 244 windows.
- `resting`: 2.0 mrad, over 4,436 windows.

The family never holds the cube. The error is in the arm's motion while it closes on nothing, which the other six families do not show. So M3's operators for this target should aim at the arm's motion around a missed closing, not at the cube.

## 5. Failure analysis
- **The motivating number was out of date.** The −237% that motivated M3 was WO-004's model. Plain A fixed the cube part of it in WO-005, before M3 was drafted. The draft said this was not run, which was wrong, and it is corrected.
- **No baseline by phase for the joints.** Joint RMSE by phase is given for the model only. The baselines' joint errors by phase were not recorded, so "worse than baseline in `moved_before_grasp`" is not shown, only where the model's own error sits.

## 6. Cost and latency
$0, the Mac, 39 seconds.

## 7. Sealed access
None.

## 8. Exit tests and acceptance
None; this feeds the proposed held-out-family test. CI only (`AGENTS.md §13.8`).

## 9. Limits
- **Train data only.** No dev data was used.
- **One model.** These are WO-004's ensembles with plain A applied at inference.

## 10. Next bounded work order
M3's next Mac work order, the design draft's protocol and scene engine. Before any operator data exists, it should freeze the held-out-family test (proposed ET-M3-6) with `missed-grasp` as its target, and aim the operators at the arm's motion around a missed closing.

## 11. Retro note
The draft's "not run" claim was caught at the freeze review, not after a run. Re-reading the earlier evidence before drafting the next phase would have caught it sooner.

## Errata (append-only)
