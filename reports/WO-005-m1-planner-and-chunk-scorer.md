# WO-005 — M1 planner (CEM MPC) and action-chunk scorer with simulator-branch validation

**Status:** partial: ET-M1-2 and ET-M1-4 passed, ET-M1-5 failed
**Date:** 2026-11-02 · **Author:** claude-code-vishwaroop · **Work order:** WO-005 · **Phase:** M1 · **Protocol version:** `m0-protocol-2`, `evals/M1-exit-tests.json` sha256 `145858ec1ff0f1d259e24756b832f2ce2ffe3497a0a769d799f5008d70388f07`, `evals/M1-planner-scorer.json` sha256 `88c952ed4ee1ca91db359e5ff964a913f460e6cfc67ef6fdeee79e7a420453bf` with four amendments, `evals/M1-planner-settings.json` sha256 `e5354588f554f966a205f153933d56b27c87ec6e987030750a573a01b7af8f96`
**Program link:** PROGRAM §5.2 → vishwaroop M1

> Four words with fixed meanings throughout this report: **measured** (ran here, evidence attached), **estimated** (arithmetic from stated assumptions), **mocked/fixture** (fabricated for tests), **not run**.

## 1. Claim and scope
**ET-M1-2 and ET-M1-4 pass and ET-M1-5 fails, on the frozen rules.** The learned model ranks action chunks the way physics does (96.3%). Learned-model MPC succeeds exactly as often as nominal-model MPC (184 of 200 each), and both match the scripted controller (183). The scorer predicts constraint violations above the AUROC bar (0.766 kept, 0.790 on everything), but abstains on 37.7% of chunks against the 20% cap I froze, so ET-M1-5 fails.

Stage 0 carried the owner's two follow-ups from WO-004:
- **Free cube.** Plain A is adopted, and its free-cube gap is measured in millimetres. The dev-informed refinement failed its frozen rule on fresh data.
- **Calibration.** On a held-out calibration split, coverage is 89.9% to 90.0%, for information.

**A contract issue the review found, which changes no verdict.** The planners read the simulator's grasp flag, `object_grasped`, which `sim/env.py` declares `reference_only`, to choose their stage. WO-004's model also takes it as an input and predicts it. `docs/EVALUATION_PROTOCOL.md` keeps reference streams out of policy inputs for experiments that claim independence. Learned and nominal planners use it identically, so ET-M1-4's comparison stands as a simulation comparison. A real controller would not have this signal, and the scripted controller does not use it. Whether it is acceptable for M1 is an owner decision (section 10).

**Not done:** the visual latent model (WO-013), M3, real data. Phase M1 has now run all five exit tests. With ET-M1-5 failed, M1 is not passed.

All results are **measured** in simulation, on a simulated SO-100 under scripted and model-predictive controllers. Nothing here says anything about a physical arm or about any VLA policy, and chunk scores are not policy success.

| Exit test | Frozen requirement | Result |
|---|---|---|
| **ET-M1-2** | At least 50 states, at least 2 chunks each, pairwise ordering accuracy at least 0.8 | **Passed.** 96.3% on 294 pairs from 60 states (Wilson 93.4% to 97.9%). Nominal model: 90.5%. |
| **ET-M1-4** | Learned-model MPC success at least nominal-model MPC success minus 5 points | **Passed.** 184 of 200 against 184 of 200: a difference of 0.0 points, paired 95% interval −5.5 to +5.5. Scripted: 183 of 200. |
| **ET-M1-5** | AUROC at least 0.75 for predicting a constraint violation; abstention reported (agent's frozen cap: at most 20%) | **Failed.** AUROC is 0.766 on the chunks kept, but it abstains on 37.7% of chunks. On every chunk the AUROC is 0.790, against the nominal model's 0.551. On the kept chunks the nominal scores 0.764, as good as the learned. |

## 2. Frozen method
Each rule was committed before the result it governs. Amendments were all made before any score, and each records what had been seen.

| File | Freezes | Committed before |
|---|---|---|
| `evals/M1-followups.json`, `-v2.json` | the first two free-cube designs and their check; the dev calibration split | each design's result |
| `evals/M1-refinement-accept.json`, `evals/M1-confirmation-plan.json` | the refinement's accept rule and its fresh data | the data existed |
| `evals/M1-planner-scorer.json` | the model, the calibration split, ET-M1-2, ET-M1-4 and ET-M1-5 | any branch, scorer or planner result |
| amendment 1 | branch states start from the episode's saved initial state, as M0 replay does | any result; the first branch attempt stopped at its first state |
| amendment 2 | M0's frozen replay tolerance (0.001) for a reached state, replacing the agent's 1e-6 | any result; a reached state was 2.46e-5 off |
| amendment 3 | ET-M1-5 also uses an extension of every remaining dev episode | any score; only the count of violating chunks, 8, had been seen |
| amendment 4 | states whose recording does not reproduce are excluded and listed | any score |
| `evals/M1-planner-settings.json` | every planner setting | any suite episode |

- **Model.** `carry-contact-beta-fall-still-reach` (plain A), on the WO-004 seed-0 ensemble. The nominal model is the same structure with no residual.
- **Calibration split.** The owner asked for scales fitted on a held-out calibration split, never on training data. This one is 120 dev-family episodes from block 9, seeds 9050 to 9089, used for nothing else.
- **Scored once.** The ET-M1-2 and ET-M1-5 scorer refuses a second run, as does each stage-0 check. The ET-M1-2/5 scorer had a focused independent review before it ran, and that review found no defect.

## 3. Reproduction
```bash
python -m vishwaroop.models.m1_followups                    # stage 0, first design
python -m vishwaroop.models.m1_followups --design second    # stage 0, second design (plain A)
python -m vishwaroop.sim.collect --config evals/M1-confirmation-plan.json --partition train --tolerance-file evals/M0-exit-tests.json --out data/derived/m1-confirmation/<commit>
python -m vishwaroop.sim.collect --config evals/M1-confirmation-plan.json --partition dev --tolerance-file evals/M0-exit-tests.json --out data/derived/m1-confirmation/<commit>
python -m vishwaroop.models.m1_confirm                      # the refinement, once
python -m vishwaroop.sim.collect --config evals/M1-calibration-plan.json --partition dev --tolerance-file evals/M0-exit-tests.json --out data/derived/m1-calibration/<commit>
python -m vishwaroop.sim.branches
python -m vishwaroop.sim.branches --extension
python -m vishwaroop.scoring.score_branches                 # ET-M1-2 and ET-M1-5, once
python -m vishwaroop.planning.suite --planner learned       # likewise nominal, scripted; and
python -m vishwaroop.planning.suite --planner learned --no-penalty --seeds 9100:9150
```
Each data set gets `python -m vishwaroop.data.registry build --root <dir> --plan <plan> --out <manifest>`. The registry exits 1 on each, because none claims M0's 200-episode minimum. Stack: `config/stack-lock.resolved.v2.json`, sha256 `f8db517142b3d720192fa51e23965d6637667d90c492519764503d79f6da19be`. Mac M3 Pro, with the planners on CPU and 3 threads each.

| Artifact | sha256 |
|---|---|
| `artifacts/manifests/m1-confirmation-v1.json` | `5e6097320145f815c75494a6742228fd27c4346baf4d721cb5be4bd26627657d` |
| `artifacts/manifests/m1-calibration-v1.json` | `6051c08e48117d1f92c81bad612a46317ec5060cd3a05e1cf10a901d63e2ad19` |
| `artifacts/manifests/m1-free-cube-v1.json`, first design, raw | `cf02abaeb92611ccd31944b863073dfa1fca7e3166466c62eed69e8ea73abc54` |
| `artifacts/manifests/m1-free-cube-v2.json`, plain A, raw | `20f8978ec5277d95f43a0fdb739ece692fb6f25fe2152f6cd7ac1a3deeda3551` |
| `artifacts/manifests/m1-refinement-confirmation-v1.json`, raw | `d2f42219c264c3d6bf39e87f549bd98e41aaea5d4d450c8fd7c7c7ace712174b` |
| `artifacts/manifests/m1-branch-scores-v1.json`, raw | `c371170fa10aa19438562a68b3fabc22cf6f43bcb8857d297a462aae75230580` |
| `artifacts/manifests/m1-suite-1-v1.json`, every episode | `4d8411a054d898e91e3170754f1db98234245de19752170dcd6e107073710691` |

| Run | Purpose |
|---|---|
| `20261102T084832Z_d576b428` | stage 0, first design; failed on an MPS float64 error before writing anything |
| `20261102T085011Z_27167da9` | stage 0, first design |
| `20261102T085542Z_4764e650` | stage 0, second design (plain A) |
| `20261102T090450Z_fe8f41bc`, `20261102T090534Z_9e0dc3f9` | confirmation data, train and dev families |
| `20261102T090745Z_686205f7` | the refinement's one scoring |
| `20261102T091154Z_19248079` | calibration split |
| `20261102T091549Z_3f46594f`, `20261102T091725Z_ba36f246` | branches, failed at a state check, before amendments 1 and 2 |
| `20261102T091817Z_47852f39` | ET-M1-2's branches |
| `20261102T092142Z_0703186b`, `20261102T092313Z_2b2e4cc7` | extension, failed at seed 8030, before amendment 4 and its fix |
| `20261102T092433Z_4ebe32df` | ET-M1-5's extension |
| `20261102T093253Z_10e98c31` | **the one scoring of ET-M1-2 and ET-M1-5** |
| `20261102T093827Z_427f7114`, `20261102T094108Z_8a03e26b` | tuning record, learned and nominal, seeds 5000 to 5007 |
| `20261102T094328Z_ea6e1a6d`, `20261102T094359Z_691fb281`, `20261102T094429Z_418c945e` | **m1-suite-1**: learned, nominal, scripted |
| `20261102T094459Z_febd3237` | learned without the penalty, seeds 9100 to 9149 |

Every run listed was at a clean commit. Every failed run wrote no result.

## 4. Results

### Stage 0: the free cube (owner, 2026-11-02)
On train data, the first design (cube stays put when free) and the second (a grasp counts only within 15 mm) both failed the strict check, "never worse than stays-put in every never-held phase, at every horizon, on every seed". The owner withdrew that requirement and adopted the second design, plain A, with the criterion "not materially worse in absolute terms".

Cube RMSE at horizon 10, per coordinate:

| Phase, data | WO-004 model | Plain A | Stays put |
|---|---|---|---|
| Resting, all dev | 0.567 mm | 0.035 mm | 0.006 mm |
| Pushed before a grasp, all dev | 3.124 mm | 2.637 mm | 1.848 mm |
| Never held, all dev | 1.114 mm | 0.813 mm | 0.612 mm |
| Never held, fresh confirmation set, all | 0.887 mm | 0.664 mm | 0.648 mm |
| Never held, fresh, dev families | 1.161 mm | 0.799 mm | 0.416 mm |
| Never held, fresh, train families | 0.371 mm | 0.461 mm | 0.840 mm |

Seed 0 is shown. Seeds 1 and 2 differ by up to 0.11 mm in the WO-004 column, and by less in the others.

**The known gap.** Plain A is still worse than stays-put on free cubes: 0.015 to 0.020 mm worse at horizon 10 over the fresh set, and 0.38 mm on its dev families. Two things cause it: a grasp predicted a step early with the gripper beside the cube, and a grasp predicted where the gripper only pushes.

**Plain A's cost.** It drops a held cube whose gripper sits more than 15 mm away. That happens on `dev-grasp-offset`, whose grasps are about 12 mm off. On the fresh set's dev families, held-cube error at horizon 10 is 3.3 to 3.5 mm, against 0.68 to 0.76 mm for the WO-004 model.

**The refinement.** It checks reach only when a grasp starts, and it is dev-informed. It cut held-cube error to the WO-004 model's level: 0.52 to 0.58 mm overall at horizon 10, against plain A's 2.2 to 2.35. But free-cube error rose, from horizon 4 on seeds 0 and 2 and from horizon 5 on seed 1, by up to 0.041 mm. That fails "free-cube error does not get worse", so plain A stands (run `20261102T090745Z_686205f7`).

### Calibration, information only
Fitted on one half of dev and measured on the other, both ways, calibrated coverage is **89.9% to 90.0%** on joints and cube, every seed and horizon pooled over both folds (runs `20261102T085011Z_27167da9` and `20261102T085542Z_4764e650`). ET-M1-3 stays as recorded, at 80.03% to 86.06% with train-family scales. WO-004's report carries this as an erratum.

### ET-M1-2: does the learned model rank chunks the way physics does?
From each of 60 dev states, 4 chunks of 10 steps were each executed through physics from the same restored start. The chunks are the recorded actions, two constant arm offsets (0.05 and 0.15 rad), and an inverted gripper. 294 of 360 pairs differ by at least 5 mm in simulated cost; the other 66 are excluded.

| Model | Right | Accuracy | Wilson 95% |
|---|---|---|---|
| Learned | 283 of 294 | **96.3%** | 93.4% to 97.9% |
| Nominal | 266 of 294 | 90.5% | 86.6% to 93.3% |

All 60 states contribute a pair. Predicted progress correlates with simulated progress at 0.84 (Pearson), over all 804 chunks of both branch runs.

### ET-M1-5: does the scorer predict a constraint violation?
- **Data.** 201 states and 804 chunks: ET-M1-2's 60 states plus the extension's 141, with 3 states excluded because their physics did not repeat. 44 chunks violate a constraint, 8 in the first part and 36 in the extension. Across them there are 37 knocks and 13 drops, and no table contact.
- **Abstention.** The threshold is 1.512 mm calibrated cube std at the last step, the 90th percentile on the calibration split. It abstains on 303 of 804 chunks.

| Measure | Value |
|---|---|
| AUROC on chunks kept | 0.766 (bootstrap 0.693 to 0.830, resampling states) |
| Abstention | **37.7%**, over the frozen 20% cap |
| AUROC on every chunk | 0.790 |
| Nominal model's AUROC, every chunk | 0.551 |
| Nominal model's AUROC, chunks kept | 0.764 |
| Violating chunks abstained on | 28 of 44 |
| Non-violating chunks abstained on | 275 of 760 |
| Abstained, by chunk: recorded / offset 0.05 / offset 0.15 / gripper inverted | 9% / 42% / 43% / 56% |

**What the failure means.** On the chunks the test is decided on, with only 16 violations among them, the learned model is no better than the nominal: 0.766 against 0.764. Its advantage, 0.790 against 0.551, is on the chunks it abstains on. The calibration split holds scripted trajectories only. The branch chunks are deliberately unusual, so the model's spread is larger on exactly those, and that includes most violations. The abstention is doing what abstention should, but more often than the 20% cap I froze.

### ET-M1-4: model-predictive control on m1-suite-1
200 episodes per planner on seeds 9100 to 9299, the same seeds for each, and at most 200 steps. Both model-based planners use identical frozen settings: 256 samples, 5 iterations and horizon 10.

| Planner | Success | Wilson 95% | Failures | Median decision |
|---|---|---|---|---|
| Learned-model MPC | **184 / 200** (92.0%) | 87.4% to 95.0% | 15 never lifted, 1 outside target | 103 ms |
| Nominal-model MPC | **184 / 200** (92.0%) | 87.4% to 95.0% | 16 never lifted | 90 ms |
| Scripted controller | 183 / 200 (91.5%) | 86.8% to 94.6% | 17 never lifted | under 1 ms |
| Learned, no penalty, first 50 seeds | 46 / 50 | | 3 never lifted, 1 outside target | 98 ms |

- **Paired comparison.** Learned minus nominal is **0.0 points**. Each wins 14 episodes the other loses. The paired 95% interval (Newcombe, hybrid score) is −5.5 to +5.5 points, and exact McNemar gives p = 1.0.
- **Decision.** The frozen threshold is −5 points as a point estimate, so this **passes**. The interval's lower end reaches −5.5, so non-inferiority at a 5-point margin is not shown with 95% confidence. The frozen rule decides on the point estimate.
- **Not degenerate.** Both planners succeed far above the 10% floor.
- **Uncertainty penalty.** On the first 50 seeds, learned MPC succeeds 46 times with the penalty and 46 without. It changed 8 outcomes, 4 each way, so its net effect was 0 and no gain from it was measured.
- **Different failures.** Only 2 seeds fail for both model-based planners, and none for all three. The scripted controller's 17 failures fall on other seeds. Each planner's failures are its own.

## 5. Failure analysis
- **ET-M1-5's abstention.** This is the failure that matters. Scales and the abstention threshold came from a calibration split of scripted trajectories. The branch chunks are deliberately off-distribution (offset joints, an inverted gripper), so the model is less certain on them, as it should be. It abstains on 9% of recorded chunks, but on 42% to 56% of perturbed ones. Fixing this would need either a calibration split with perturbed chunks or a different cap. Both are changes after seeing the result, so neither is made here.
- **Planner failures.** All but one are `never_lifted`: the grasp did not close on the cube within 200 steps. Learned and nominal fail on different seeds, so neither model is systematically worse at grasping. The one `outside_target` is a learned-planner place outside the 15.6 mm radius.
- **The learned model adds no success.** Over the nominal, it adds nothing at this task and cost: 184 against 184. The staged cost and the nominal kinematics carry most of the work. ET-M1-2 shows the learned model ranks chunks better (96.3% against 90.5%), but that did not turn into more successes here.
- **Free cube.** See stage 0. Plain A still moves a free cube near a grasp, and drops a held cube whose gripper is more than 15 mm away.

## 6. Cost and latency
$0: the owner's Mac, no paid compute, nothing in `ledgers/costs.jsonl`. **Measured** from ledger times:
- Stage 0: about 2 minutes of runs.
- Data collection: about 3 minutes for 325 episodes.
- Branches: about 2 minutes.
- Scoring: 6 seconds.
- Suite: about 70 minutes, with the four planners in parallel on CPU (the scripted run took 1 minute).

Median decision time per control step is 103 ms for the learned model and 90 ms for the nominal model, at most 199 ms, on CPU with 3 threads while four processes ran. That is about twice the 50 ms control period, so these planners do not run in real time at 20 Hz on this machine. Without contention, in the ledgered tuning runs, the medians were 96 and 83 ms.

## 7. Sealed access
None.

## 8. Exit tests and acceptance
| Exit test | Threshold (frozen) | Result | Evidence | Pass? |
|---|---|---|---|---|
| ET-M1-2 | ≥ 50 states; ≥ 2 chunks each; pairwise accuracy ≥ 0.8 | 60 states, 4 chunks, 96.3% | `20261102T093253Z_10e98c31` | yes |
| ET-M1-4 | learned minus nominal success ≥ −5 points, point estimate | 0.0 points (paired −5.5 to +5.5) | `20261102T094328Z_ea6e1a6d`, `20261102T094359Z_691fb281` | yes |
| ET-M1-5 | AUROC ≥ 0.75 on chunks kept; abstention ≤ 20% (agent's frozen cap) | 0.766; abstention 37.7% | `20261102T093253Z_10e98c31` | **no** |

With WO-004's ET-M1-1 and ET-M1-3, phase M1 has run all five exit tests and passed four. **M1 is not passed, because ET-M1-5 failed.** What happens next is the owner's call (section 10).

**Review.** `AGENTS.md §13.8` requires a full independent review, because this work order closes exit tests. A focused review of the ET-M1-2 and ET-M1-5 scorer ran before its one scoring and found no defect. The full review, on a clean clone at `3dfb09c`, reproduced all three verdicts from the artifacts. It found the grasp-flag issue, the hidden kept-chunk comparison, a resume defect and several number errors, all fixed or disclosed above.

## 9. Limits
- **Simulation only.** A simulated SO-100 under scripted and planned controllers. No claim about a physical arm, VLA policies or full-episode success from chunk scores.
- **Hand-built, staged cost.** The planner's cost comes from known geometry. Its success is that cost's success as much as the model's.
- **Dev has been used more than once.** Stage 0's information-only looks and the branch states both use dev. ET-M1-2 and ET-M1-5 were each scored once.
- **Physics is not always repeatable.** 3 of 144 extension states reproduced their recording only to 0.0011 to 0.005, and were excluded. 12 states had chunk starts up to 0.9 mm apart (measured by the review).
- **The grasp flag.** The planners and the model read `object_grasped`, declared `reference_only`; see section 1.
- **ET-M1-2's cost** uses the 3D distance to the goal site, which sits 16 to 91 mm above the table in these states. The rubric uses its xy on the table. Simulation and prediction use the same function, so the accuracy is unbiased, but this is not the rubric's task cost.
- **Reached-state deviation.** The branch data records only chunk 0's deviation, which is 0.0 for every state. Up to 0.897 mm occurs on other chunks of 12 states (measured by the review). The code now records the largest over all chunks.
- **Changed after the runs.** These changes alter no recorded result. The planner reseeds per episode, so a resumed suite equals an unbroken one; a test covers it, and the recorded runs used one stream per process and resumed nothing. The suite checks the settings file's hash, and every recorded run carried the frozen one.
- **Tuning was not ledgered.** The scratch runs on train seeds 5000 to 5007 were not ledgered. The ledgered run on the same seeds records the frozen settings.

## 10. Next bounded work order
**Two owner decisions.**

**1. The grasp flag** (section 1). Accept `object_grasped` as a simulation-only input for M1's predictor and planners, recorded as a protocol note. Or require WO-004 and WO-005 to be redone without it, deriving held from the gripper joint and the cube's height. I recommend accepting it for M1, labelled as privileged simulation state, and excluding it from M2a onward. Redoing it costs the most and claims nothing new in simulation.

**2. ET-M1-5.** Three options:
- **(a)** Accept the failure and close M1 with a recorded negative.
- **(b)** A new work order with a calibration split that includes perturbed chunks, frozen before any score and on fresh states. Branch block 9 has room, from seed 9300.
- **(c)** Revisit the 20% abstention cap. It was mine, frozen before results and not owner-set, so changing it now would be a change after seeing the result.

For reference: on ET-M1-2's 60 states alone, as `evals/M1-exit-tests.json` first said, ET-M1-5 is not decidable, with 8 violations. Without the agent's cap, 0.766 and 0.790 would both clear 0.75. The extension (amendment 3) and the cap were both mine, and both made the result stricter.

**Recommendation: (b).** It tests the scorer properly, at about an hour of Mac time and $0.

After M1, M2a's observation model is the first work that likely needs a GPU (estimate in WO-005's plan). Rollback: reverting this PR removes the planner, scorer, branches and evals. Runs and data stay where they are.

## 11. Retro note
- **Amendments.** Four were needed, all before any score. Each came from a property of the data: restore, tolerance, too few violations, and repeatability. A dry run of the branch generator on two states before freezing would have caught the first two.
- **A hidden failure.** `make check | tail` hid one type failure once. A failure shows now through an exit code checked by itself.
- **An untested cap.** The abstention cap I froze was not tested against off-distribution chunks before freezing, and it decided ET-M1-5.
- **Size:** L, as estimated. About 4 hours of agent time and 1.5 hours of machine time.

## Errata (append-only)
- **2026-11-02, owner decisions and the retest; nothing above is changed.**
  - **The grasp flag** is accepted as a simulation-only input for M1 and excluded from M2a onward. The disclosure above is sufficient.
  - **ET-M1-5** was retested under option (b) in `reports/WO-016-m1-et5-retest.md`, with the cap kept. It **passed** on fresh states: AUROC 0.922 on the chunks kept, abstention 9.4%. The failure above stands as WO-005's first test.
  - **M1's primary result.** The learned model matched the nominal model on planning success (184 against 184). On constraint prediction it matched on WO-016's fresh states, except on chunks that change the gripper command, where it leads. On this work order's chunks it was also ahead on arm offsets, 0.736 against 0.672. See `docs/CONTEXT_AND_DECISIONS.md` §7.
  - **The 100 ms planner against the 50 ms period** is logged as a prerequisite before M4's shadow mode.

