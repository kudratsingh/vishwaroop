# WO-016 — Retest ET-M1-5 with a calibration split that includes perturbed chunks

**Status:** passed
**Date:** 2026-11-02 · **Author:** claude-code-vishwaroop · **Work order:** WO-016 · **Phase:** M1 · **Protocol version:** `m0-protocol-2`, `evals/M1-exit-tests.json` sha256 `145858ec1ff0f1d259e24756b832f2ce2ffe3497a0a769d799f5008d70388f07`, `evals/M1-et5-retest.json` sha256 `aa9c128a46be3219d5194bef3a65969689537b8a8779944a860f18baeff7ebcb`, with WO-005's `evals/M1-planner-scorer.json` and its four amendments
**Program link:** PROGRAM §5.2 → vishwaroop M1

> Four words with fixed meanings throughout this report: **measured** (ran here, evidence attached), **estimated** (arithmetic from stated assumptions), **mocked/fixture** (fabricated for tests), **not run**.

## 1. Claim and scope
**ET-M1-5 passes on fresh states.** The only change from WO-005 is that the interval scales and the abstention threshold now come from branches of the calibration split, perturbed chunks included. On 191 fresh states:
- **Abstention** is 9.4%, within the 20% cap, which stays.
- **AUROC** on the chunks kept is 0.922, with a bootstrap interval of 0.887 to 0.952.
- **The nominal model** scores 0.632 on the same chunks.

All of it is **measured**, in simulation, and scored once. With WO-004 and WO-005, all five M1 exit tests now pass.

**M1's primary result, as the owner asked, with one exception the data shows.** The learned model matched the nominal model on planning success: 184 of 200 each, with the scripted controller at 183 (WO-005). On this deterministic simulated task, learned dynamics showed no planning advantage. M2 and M3 are where it must prove itself.

On constraint prediction, the learned model also matched the nominal, with one exception: chunks that change the gripper command. Split by chunk kind, on the fresh states, chunks kept:

| Chunks | Kept | Violations | Learned AUROC | Nominal AUROC |
|---|---|---|---|---|
| Arm offset (0.05 and 0.15 rad) | 310 | 20 | 0.882 | 0.890 |
| Gripper inverted | 191 | 26 | 0.944 | 0.405 |

In WO-005, over every chunk, the same split gives 0.736 against 0.672 for arm offsets and 0.888 against 0.347 for the inverted gripper. The nominal model cannot predict a grasp or a release, so it cannot foresee a drop. The learned model can, and that is the whole of its pooled lead (0.922 against 0.632). Pooling across kinds also rewards telling the kinds apart, not only telling violating chunks from safe ones. Where the arm simply moves differently, learned dynamics add nothing measurable here.

## 2. Frozen method
`evals/M1-et5-retest.json` was committed before the fresh episodes existed and before any branch of either set. Everything else is WO-005's unchanged, with one addition in the scorer. It also returns "not decidable" when the kept chunks lack a violating or a safe chunk, where AUROC is undefined. That did not apply: 46 of the 692 kept chunks violate. The scorer itself (`score_et5_retest.py`, at `e9aa100`) was written after both branch runs and before any score. It reuses WO-005's reviewed functions. The rest is unchanged: the model (plain A, WO-004 seed-0 ensemble), the four chunks per state, the branch protocol and its four amendments, the violation definition and score, AUROC with ties as half, the bootstrap over states, the 10-violation minimum and the rule.
- **Calibration.** 116 states of the calibration split (block 9, seeds 9050 to 9089), branched into 464 chunks of all four kinds. Scales are split-conformal at 90%, per stream and horizon. The threshold is the 90th percentile of calibrated cube std at the last step: 34.78 mm.
- **Evaluation.** 191 states from 210 fresh episodes (block 9, seeds 9300 to 9369, never simulated before), 764 chunks. 12 episodes were too short and 7 were excluded because their recording did not reproduce (0.0010 to 0.0059).

## 3. Reproduction
```bash
python -m vishwaroop.sim.collect --config evals/M1-et5-eval-plan.json --partition dev --tolerance-file evals/M0-exit-tests.json --out data/derived/m1-et5-eval/<commit>
python -m vishwaroop.data.registry build --root data/derived/m1-et5-eval/<commit> --plan evals/M1-et5-eval-plan.json --out artifacts/manifests/m1-et5-eval-v1.json
python -m vishwaroop.sim.branches --set calibration
python -m vishwaroop.sim.branches --set evaluation
python -m vishwaroop.scoring.score_et5_retest
```
The registry exits 1 because 210 episodes do not claim M0's minimum. That is expected.

| Item | Value |
|---|---|
| `artifacts/manifests/m1-et5-eval-v1.json` | sha256 `d78ec0876692ff037cfa20829c7b39514c0e6ac7209554d869c2dc246b9bcde7` |
| `artifacts/manifests/m1-et5-retest-v1.json`, raw result | sha256 `f7d3f85e19df0ca688fb9847cf845d74eb3a9cfc4eab628942c738ae83b237da` |
| Collection | `20261102T120608Z_b621cdd4`, 210 episodes, 9 sampled replays valid |
| Calibration branches | `20261102T120807Z_2f1c5a1b`, branches.json sha256 `cb76b15d…` |
| Evaluation branches | `20261102T120907Z_a102fd9a`, branches.json sha256 `0121862d…` |
| **The one scoring** | `20261102T121222Z_a866effd`, at `e9aa100`, clean |

## 4. Results
| Measure | WO-016, fresh states | WO-005 |
|---|---|---|
| States, chunks | 191, 764 | 201, 804 |
| Violating chunks (knock / drop) | 49 (42 / 8; one chunk is both) | 44 (37 / 13; some are both) |
| Abstention | **9.4%** | 37.7% |
| Violating chunks kept | 46 of 49 | 16 of 44 |
| AUROC on chunks kept | **0.922** (0.887 to 0.952) | 0.766 |
| AUROC on every chunk | 0.912 | 0.790 |
| Nominal, chunks kept | 0.632 | 0.764 |
| Nominal, every chunk | 0.661 | 0.551 |
| Abstained by chunk: recorded / 0.05 / 0.15 / gripper | 0% / 13% / 25% / 0% | 9% / 42% / 43% / 56% |
| **Verdict** | **passed** | failed (abstention) |

**Why the scales are large.** On the perturbed calibration chunks, errors run up to 7 times the predicted std (the cube scale is 1.87 at horizon 1 and 6.97 at horizon 10). Calibrated this way, the intervals are honest for unusual chunks, and wide. That is why abstention now falls mostly on the largest arm offsets.

## 5. Failure analysis
- **Different state samples, different AUROC.** The scorer is identical, but its AUROC on every chunk differs between WO-005's states and these fresh ones: 0.790 against 0.912. Part of the gain is the sample, not the calibration. Calibration changes only which chunks are kept.
- **Abstained violations.** 3 of 49 violating chunks were abstained on.
- **Abstention near 10% is close to guaranteed by construction.** The threshold is the calibration chunks' 90th percentile, and the evaluation chunks have the same kinds. Passing the cap mostly confirms there is no shift between the two sets.
- **Repeatability.** 7 of 198 eligible states did not reproduce their recording within tolerance and were excluded, as in WO-005.

## 6. Cost and latency
$0, the owner's Mac. Collection took about 1 minute and branching about 3 minutes. Scoring took 5 seconds.

## 7. Sealed access
None.

## 8. Exit tests and acceptance
| Exit test | Threshold (frozen) | Result | Evidence | Pass? |
|---|---|---|---|---|
| ET-M1-5 | AUROC ≥ 0.75 on chunks kept; abstention ≤ 20%; ≥ 10 violations | 0.922; 9.4%; 49 | `20261102T121222Z_a866effd` | yes |

**M1.** All five exit tests pass:
- ET-M1-1 and ET-M1-3 in WO-004.
- ET-M1-2 and ET-M1-4 in WO-005.
- ET-M1-5 here, on its retest; WO-005's first test of it failed.

**Review.** One review plus one recheck, in the PR.

## 9. Limits
- **Simulation only.** No claim about a physical arm or VLA policies.
- **A second attempt.** ET-M1-5 passed on its second attempt, after the first failed. The owner chose the retest, the cap was kept, and every rule was frozen before the fresh data existed. It is still a second chance that the other exit tests did not get.
- **The grasp flag.** The model and the planners read the simulator's grasp flag. The owner accepted it as a simulation-only input for M1, to be excluded from M2a onward.

## 10. Next bounded work order
- **Owner, the headline.** Confirm the M1 headline in section 1 and in `docs/CONTEXT_AND_DECISIONS.md`. Your "matched" holds for planning, and for constraint prediction except where the gripper command changes.
- **WO-017.** The 30-minute Mac pilot for M2a's observation model, as instructed. No rental until it gives a number.
- **Rollback.** Reverting this PR removes the retest code and evals. Runs and data stay.

## 11. Retro note
Calibrating on the kind of data the scorer would face was the whole fix. WO-005's freeze should have asked for it. Size: S, as estimated.

## Errata (append-only)
