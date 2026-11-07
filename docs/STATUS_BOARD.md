# Status board — vishwaroop

_Derived from `work_orders/STATUS.jsonl` and `config/phases.json` by `ironclad-status`. Do not edit by hand._

Generated: 2026-11-07 07:13 UTC · ledger records: 125

## Phases

| Phase | Name | State | Exit tests (passed / frozen / total) | Prerequisites | Work orders |
|---|---|---|---|---|---|
| M0 | Grounded development environment | **passed** | 6 / 6 / 6 | — | WO-001, WO-002, WO-003, WO-007, WO-008, WO-009, WO-010, WO-011 |
| M1 | Compact predictor, latent planner, action-chunk scorer | **passed** | 5 / 5 / 5 | M0 | WO-004, WO-005, WO-006, WO-012, WO-013, WO-014, WO-015, WO-016 |
| M2a | Closed-loop policy evaluator (simulation) | **not_started** | 0 / 0 / 5 | M1 | WO-017, WO-018 |
| M2b | Real-arm evaluator validation | **not_started** | 0 / 0 / 4 | M2a | — |
| M3 | Synthetic-data engine (SFT route) | **not_started** | 0 / 0 / 5 | M0 | WO-020 |
| M4 | Drone dynamics adaptation (offline and shadow only) | **not_started** | 0 / 2 / 4 | M1 | WO-019 |
| M5 | Future: verifier at test time (best-of-N action chunks) | **not_started** | 0 / 0 / 2 | M2b | — |
| M6 | Future: verifier as reward for real-robot RL | **not_started** | 0 / 0 / 2 | M5 | — |
| M7 | Future: data curation loop | **not_started** | 0 / 0 / 1 | M3, M5 | — |
| M8 | Future: new embodiment (LEAP hand on a stand) | **not_started** | 0 / 0 / 1 | M2b | — |

## Exit tests

| Exit test | Phase | Statement | Threshold | State | Report |
|---|---|---|---|---|---|
| ET-M0-1 | M0 | CPU-tier checks (contract tests, unit tests, lint, types, hash locks) pass before and after adapter work. | 100% of CPU-tier checks green | passed | reports/WO-001-m0-grounded-environment.md |
| ET-M0-2 | M0 | One real simulator episode is exported through contracts/v1/writer.py and validates, including every referenced artifact hash, with a fully resolved stack lock. | validate.py returns contract_valid; zero null pins in the simulator section | passed | reports/WO-001-m0-grounded-environment.md |
| ET-M0-3 | M0 | Replay from the saved INITIAL state only, executing recorded actions through physics, reproduces the episode on the pinned stack across repeats. | frozen: max per-step deviation <= 0.001 (joints in rad; object and target positions in m) on all 3 repeats, identical outcome label (evals/M0-exit-tests.json) | passed | reports/WO-001-m0-grounded-environment.md |
| ET-M0-4 | M0 | The task outcome is computed independently from simulator state by code that shares nothing with the policy or any reward model, agrees with inspection on one success and one failure episode, and every negative test is rejected. | 5/5 negative tests fail validation or invalidate the replay claim; 2/2 inspected outcomes agree | passed | reports/WO-001-m0-grounded-environment.md |
| ET-M0-5 | M0 | The evaluation specification is frozen and hashed before any neural training: task rubric, split specification, group ids, policy-holdout plan (by training run/family), sealed opening budget, baselines. | all listed files present and hashed; policy-holdout plan names run/family grouping | passed | reports/WO-001-m0-grounded-environment.md |
| ET-M0-6 | M0 | A dataset of scripted and perturbed-policy episodes containing both successes and failures is collected, validated, and split-audited. | frozen: >= 200 episodes, >= 30% failures across >= 3 distinct failure modes, audit passes (evals/M0-exit-tests.json) | passed | reports/WO-002-m0-dataset-successes-and-failures.md |
| ET-M1-1 | M1 | Multi-step prediction error versus horizon is reported for the learned predictors against constant/linear and nominal baselines on held-out dev episodes. | frozen: learned predictor RMSE at least 20% below the best baseline at every horizon 1..10 steps (evals/M1-exit-tests.json) | passed | reports/WO-004-m1-predictors-and-calibration.md |
| ET-M1-2 | M1 | Action sensitivity is validated against physics: from each restored initial state at least two alternative action chunks are executed in the simulator and the predictor's ranking of their outcomes agrees with the simulator's. | frozen: >= 50 initial states; pairwise ordering accuracy >= 80% (evals/M1-exit-tests.json) | passed | reports/WO-005-m1-planner-and-chunk-scorer.md |
| ET-M1-3 | M1 | Predictive uncertainty is calibrated against actual error on held-out data. | frozen: Spearman(predicted std, |error|) >= 0.5 and 90% interval coverage within +/- 10 points (evals/M1-exit-tests.json) | passed | reports/WO-004-m1-predictors-and-calibration.md |
| ET-M1-4 | M1 | Learned-model MPC is compared with nominal-model MPC and the scripted baseline on the frozen task suite with matched interaction budgets, reporting success with Wilson intervals, compute and latency. | frozen: learned-model MPC success non-inferior to nominal within 5 points on m1-suite-1, or a reported negative result (evals/M1-exit-tests.json) | passed | reports/WO-005-m1-planner-and-chunk-scorer.md |
| ET-M1-5 | M1 | The action-chunk scorer scores progress, clearance, constraint violations and uncertainty for logged prefixes plus candidate chunks, abstains when uncertain, and is validated against executed simulator branches. It makes no full-episode success claim. | frozen: AUROC >= 0.75 for predicting a constraint violation; abstention rate and coverage reported (evals/M1-exit-tests.json) | passed | reports/WO-016-m1-et5-retest.md |
| ET-M2a-1 | M2a | Policy-compatibility suite: the evaluator supplies images (resolution, history), proprioception, instruction and timing exactly as the checkpoint expects. | 100% of compatibility tests pass for each supported checkpoint family | not_run | — |
| ET-M2a-2 | M2a | Branch consistency: evaluator rollouts of a checkpoint from restored initial states agree with simulator rollouts in outcome. | proposed default: outcome agreement >= 85% on dev initial states | not_run | — |
| ET-M2a-3 | M2a | Ranking reliability on held-out policy runs (holdout by training run/family, never adjacent checkpoints). | proposed default: Spearman >= 0.7; top-1 correct on >= 80% of pairs with a pre-declared visible gap | not_run | — |
| ET-M2a-4 | M2a | False optimism is measured at the chosen decision threshold and the evaluator abstains with 'insufficient evidence' outside its validated range. | proposed default: false optimism <= 10%; abstention behaviour demonstrated on out-of-range inputs | not_run | — |
| ET-M2a-5 | M2a | The success judge used for evaluation is independent of any training reward model, and reward-vs-judge disagreement tracking is in place. | no shared weights or labels between training reward and final judge; disagreement report produced | not_run | — |
| ET-M2b-1 | M2b | The physical protocol is frozen (objects, placement template, camera mounts and calibration ids, reset procedure, timeout, rubric, sensors, blinding) and the rubric is double-labelled on about 20 mixed episodes. | proposed default: reviewer agreement >= 90% with adjudication rules recorded | not_run | — |
| ET-M2b-2 | M2b | Ranking on held-out real checkpoint pairs using matched placements with randomized within-pair order and paired analysis. | proposed default: selection regret <= 5 points; false optimism <= 10%; sample size frozen from a precision plan | not_run | — |
| ET-M2b-3 | M2b | Physical episodes saved at the validated selection error and cost per evaluated checkpoint are reported. | reported with denominators; no threshold on the value itself | not_run | — |
| ET-M2b-4 | M2b | One sealed confirmation suite is opened once under logged owner authorization and the result is reported regardless of outcome. | exactly one opening; frozen candidate hashes recorded before access | not_run | — |
| ET-M3-1 | M3 | Generation starts from initial frames rendered from known simulator scenes whose initial state and asset hashes were saved first; scene-consistency checks reject injected mismatches. | 100% of injected mismatches rejected | not_run | — |
| ET-M3-2 | M3 | Inverse-dynamics actions are replayed from the initial state only and judged on task predicates; executability and false accept/reject rates are measured on an audited sample. | proposed default: false acceptance <= 10% on >= 100 audited trajectories | not_run | — |
| ET-M3-3 | M3 | Matched-budget downstream ablation on the SFT route: real-only, real plus ordinary augmentation, real plus generated, with multiple seeds and held-out success with intervals. | proposed default: >= 3 seeds per arm; a benefit is claimed only if real+generated beats real+augmentation by a frozen margin; a negative result is a valid delivery | not_run | — |
| ET-M3-4 | M3 | Total generation, filtering and training cost per accepted trajectory is reported including rejected generations. | reported; no threshold on the value | not_run | — |
| ET-M3-5 | M3 | Generated demonstrations feed only the SFT route; GRPO uses on-policy samples only. | no code path routes IDM-labelled data into the GRPO objective | not_run | — |
| ET-M4-1 | M4 | Drone episodes are imported read-only through the contract and validate. | frozen: 100% of imported episodes contract_valid (evals/M4-exit-tests.json) | frozen | — |
| ET-M4-2 | M4 | The residual model predicts 1 s of open-loop motion better than the nominal model on held-out flight families (evals/M4-exit-tests.json). | frozen (owner, 2026-11-06): learned RMSE <= 0.85 x nominal RMSE, where RMSE is the square root of the equal-weight mean over held-out families of each family's mean squared 3-D position error at step 20 of a 20-step open-loop rollout (evals/M4-exit-tests.json) | frozen | — |
| ET-M4-3 | M4 | Uncertainty is calibrated and a gating rule (trust the learned model only when calibrated uncertainty is below a bound) is proposed and evaluated offline; shadow predictions are logged only. | no code path can emit a setpoint; gating rule documented with offline evidence | not_run | — |
| ET-M4-4 | M4 | An exported model manifest (contracts/v1/model-manifest.template.json) records inputs, normalization, timestep, horizon, uncertainty outputs and validity limits; command_authority is false. | manifest complete; command_authority == false | not_run | — |
| ET-M5-1 | M5 | Real-arm success versus N is measured with paired trials against N=1 and the GRPO-tuned policy. | to be frozen when the phase becomes next | not_run | — |
| ET-M5-2 | M5 | Compute per episode and the N at which gains stop are reported. | reported | not_run | — |
| ET-M6-1 | M6 | Human labels saved at matched success are measured; reward-vs-independent-assessment disagreement is tracked throughout. | to be frozen when the phase becomes next | not_run | — |
| ET-M6-2 | M6 | Failure modes (reward hacking, false optimism) are documented with examples. | reported | not_run | — |
| ET-M7-1 | M7 | Scaling curves of held-out real success versus data volume and curation strategy with intervals. | to be frozen when the phase becomes next | not_run | — |
| ET-M8-1 | M8 | Selection regret versus real on held-out hand policies, with and without cheap tactile input. | to be frozen when the phase becomes next | not_run | — |

## Work orders

| WO | Title | Phase | State | Last event (UTC) | Report |
|---|---|---|---|---|---|
| WO-001 | M0 grounded environment: one reproducible simulator episode and its evidence chain | M0 | **accepted** | 2026-11-01T05:32:28.583459Z | reports/WO-001-m0-grounded-environment.md |
| WO-002 | M0 dataset: scripted and perturbed episodes with successes and failures | M0 | **accepted** | 2026-11-01T05:57:18.655278Z | reports/WO-002-m0-dataset-successes-and-failures.md |
| WO-003 | Supervised resource and spend enforcement (local, no paid execution) | M0 | **superseded** | 2026-11-01T00:40:56.445935Z | — |
| WO-004 | M1 predictors on the Mac: nominal + residual ensemble, state-based latent model, calibration | M1 | **accepted** | 2026-11-02T07:23:55.235946Z | reports/WO-004-m1-predictors-and-calibration.md |
| WO-005 | M1 planner (CEM MPC) and action-chunk scorer with simulator-branch validation | M1 | **accepted** | 2026-11-02T12:22:18.272597Z | reports/WO-005-m1-planner-and-chunk-scorer.md |
| WO-006 | Read-only arm snapshot import and policy-holdout registry | M1 | **created** | 2026-10-31T07:51:48.074460Z | — |
| WO-007 | Program-wide rename of this repository and package to vishwaroop | M0 | **accepted** | 2026-10-31T22:15:23.725834Z | reports/WO-007-program-rename-vishwaroop.md |
| WO-008 | Fix three starter-kit tooling defects found during the rename review | M0 | **accepted** | 2026-10-31T22:15:23.768846Z | reports/WO-008-starter-kit-tooling-fixes.md |
| WO-009 | Designate the private GitHub remote and create the repository | M0 | **accepted** | 2026-10-31T10:19:25.741665Z | reports/WO-009-designate-github-remote.md |
| WO-010 | Protect accepted work orders, widen the secret scan, restore the broad ignore rule | M0 | **accepted** | 2026-10-31T22:15:23.806356Z | reports/WO-010-status-freeze-and-token-scan.md |
| WO-011 | Adopt ironclad v1.1.0 and remove the vendored shared files | M0 | **accepted** | 2026-11-01T04:59:08.566289Z | reports/WO-011-adopt-ironclad.md |
| WO-012 | Split M1 between the Mac and a GPU, from a measured pilot | M1 | **accepted** | 2026-11-01T07:57:36.907206Z | reports/WO-012-m1-compute-split.md |
| WO-013 | M1 visual latent model, on the Mac first | M1 | **created** | 2026-11-01T07:48:28.393883Z | — |
| WO-014 | Diagnose why the pilot predictor did not learn the cube | M1 | **accepted** | 2026-11-02T01:39:57.993547Z | reports/WO-014-m1-cube-prediction-diagnosis.md |
| WO-015 | Bump the ironclad pin to v1.2.0 | M1 | **accepted** | 2026-11-01T23:09:05.286326Z | reports/WO-015-ironclad-v1.2.0.md |
| WO-016 | Retest ET-M1-5 with a calibration split that includes perturbed chunks | M1 | **accepted** | 2026-11-02T12:22:18.309434Z | reports/WO-016-m1-et5-retest.md |
| WO-017 | M2a observation model: a 30-minute Mac pilot to check the GPU estimate | M2a | **accepted** | 2026-11-02T12:55:18.599343Z | reports/WO-017-m2a-mac-pilot.md |
| WO-018 | M2a: a GPU pilot to measure the speedup over the Mac, then one full run if it fits | M2a | **ready** | 2026-11-02T13:08:19.541210Z | — |
| WO-019 | M4: import banshee's D1 simulation episodes, read-only, and validate them | M4 | **created** | 2026-11-02T13:19:20.243311Z | — |
| WO-020 | M3: re-measure the family-holdout gaps under plain A, and pick M3's target family | M3 | **accepted** | 2026-11-07T07:13:29.084289Z | reports/WO-020-m3-remeasure-family-gaps.md |

