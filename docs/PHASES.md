# PHASES.md — World Model & Planner: phases, exit tests, and how to track them

Machine-readable twin: `config/phases.json` (a test keeps the two in sync). Live state: `docs/STATUS_BOARD.md` (generated from `work_orders/STATUS.jsonl`). Rules: `AGENTS.md §5`. Program context: `PROGRAM.md §5.2, §6, §8`.

**How to read this file.** Each phase lists its deliverable, prerequisites, the work orders that implement it, and its exit tests (`ET-<phase>-<n>`). A phase is `passed` only when every exit test has run with evidence in a report. Thresholds marked *proposed default* must be frozen in `evals/<phase>-exit-tests.json` before the phase becomes `ready`; after that they do not change.

## Dependency order

```
M0 ──► M1 ──► M2a ──► M2b ──► M5 ──► M6
 │       │                       │
 │       └──► M4 (needs drone SITL logs; never waits for M2/M3)
 └──► M3 ───────────────────────► M7 (with M5)
                                 M8 (hand; after M2b)
```

M0 and M1 run entirely in simulation with data an agent can generate today, and on the owner's Mac (`reports/WO-012-m1-compute-split.md`). M2a needs arm checkpoints (immutable exports). M2b needs the real arm and the physical protocol. M3 needs matched sim scenes plus generator and downstream-policy access. M4 needs drone logs. Each waits only for its own input.

Phase states: `not_started → ready → in_progress → (blocked ↔) → passed | failed`.

---

## M0 — Grounded development environment

**Deliverable.** One genuinely reproducible simulator episode and its evidence chain: contract-v1 export via `writer.py`, replay from the saved initial state only, an independently computed outcome, a locked simulator stack, a frozen evaluation specification; then a dataset with both successes and failures.

**Prerequisites.** None (local simulator capability; no real arm). **Work orders.** WO-001 (environment, first episode, replay, negative tests, frozen spec), WO-002 (dataset of successes and failures).

| Exit test | Statement | Evidence | Threshold |
|---|---|---|---|
| ET-M0-1 | CPU-tier checks pass before and after adapter work | CI run ids | 100% green |
| ET-M0-2 | One real simulator episode exported through `writer.py` validates with every artifact hash and a fully resolved stack lock | `validate.py` output; `config/stack-lock.resolved.json` | `contract_valid`; zero null simulator pins |
| ET-M0-3 | Initial-state-only replay reproduces the episode across repeats on the pinned stack | replay report, 3 repeats, outcome labels | *frozen:* max per-step deviation ≤ 0.001 (joints in rad; object and target positions in m) on all 3 repeats, identical outcome |
| ET-M0-4 | Outcome computed independently from simulator state; agrees with inspection on one success and one failure; all negative tests rejected | outcome code hash; inspection notes; negative-test log | 5/5 negatives rejected (corrupted action semantics, broken hash, missing asset, wrong timebase, intermediate-state forcing); 2/2 inspections agree |
| ET-M0-5 | Evaluation specification frozen and hashed before any neural training (rubric, splits, group ids, policy-holdout plan by run/family, sealed opening budget, baselines) | `evals/M0-protocol.md`, `evals/M0-exit-tests.json` hashes; `frozen` events for M1 exit tests | all files present and hashed |
| ET-M0-6 | Dataset of scripted and perturbed-policy episodes with successes and failures, validated and split-audited | dataset manifest; `audit_splits.py` output; failure breakdown | *frozen:* ≥ 200 episodes, ≥ 30% failures across ≥ 3 failure modes |

**Honesty note.** If a faithful SO-101 simulation adapter is not yet available, use a readily available ManiSkill3 task, label the embodiment honestly, and make no transfer claim. The arm project's task configs and action space are the preferred target once exported (`PROGRAM.md §6`).

## M1 — Compact predictor, latent planner, action-chunk scorer

**Deliverable.** A state-based residual/ensemble predictor (PETS-style small ensemble, nominal dynamics plus learned correction) and a compact latent predictor with calibrated uncertainty; a sampling MPC planner (CEM) against nominal-model MPC and a scripted baseline; an action-chunk scorer validated against executed simulator branches. **No full-episode VLA success claim.**

**Prerequisites.** M0 passed. Arm policy snapshots are needed only for VLA-chunk comparisons. **Work orders.** WO-012 (where M1 runs, from a measured pilot), WO-004 (predictors and calibration), WO-005 (planner and scorer), WO-006 (read-only arm snapshot importer and policy-holdout registry; can run in parallel), WO-013 (visual latent model, no exit test depends on it).

| Exit test | Statement | Evidence | Threshold |
|---|---|---|---|
| ET-M1-1 | Multi-step error vs horizon for learned predictors vs constant/linear and nominal baselines on held-out dev episodes | tables with CIs | *frozen:* ≥ 20% lower RMSE than the best baseline at horizons 1–10 |
| ET-M1-2 | Action sensitivity validated against physics: ≥ 2 alternative chunks executed from each restored initial state; predictor ranking agrees with the simulator | branch dataset; agreement table | *frozen:* ≥ 50 initial states; pairwise ordering accuracy ≥ 80% |
| ET-M1-3 | Uncertainty calibrated against actual error | calibration data; coverage | *frozen:* Spearman(std, \|error\|) ≥ 0.5; 90% interval coverage within ±10 points |
| ET-M1-4 | Learned-model MPC vs nominal-model MPC vs scripted baseline on the frozen suite, matched budgets, Wilson intervals, compute and latency | comparison table; cost lines | *frozen:* non-inferior within 5 points on `m1-suite-1`, or a reported negative |
| ET-M1-5 | Action-chunk scorer scores progress, clearance, constraint violations and uncertainty; abstains when uncertain; validated on executed branches | scorer evaluation; abstention coverage | *frozen:* AUROC ≥ 0.75 for constraint-violation prediction |

**Boundaries.** Real logs validate executed actions only; counterfactual claims need the simulator branch protocol above. The scorer is an action-chunk scorer, not a policy evaluator.

## M2a — Closed-loop policy evaluator (simulation)

**Deliverable.** An action-conditioned observation model that supplies *every* input the evaluated checkpoint expects (images with the right resolution and history, proprioception, instruction, timing), branch-consistency tests against the simulator, a success judge separate from any training reward, calibration and abstention, validated on held-out policy runs.

**Prerequisites.** M1 passed; checkpoints with ids from immutable arm exports. **Work orders.** To be detailed when next (observation model; compatibility suite; judge; holdout evaluation).

| Exit test | Statement | Threshold |
|---|---|---|
| ET-M2a-1 | Policy-compatibility suite passes for each supported checkpoint family | 100% |
| ET-M2a-2 | Branch consistency: evaluator vs simulator rollouts agree in outcome | *proposed default:* ≥ 85% on dev |
| ET-M2a-3 | Ranking on held-out policy runs (run/family holdout) | *proposed default:* Spearman ≥ 0.7; top-1 correct on ≥ 80% of visibly-separated pairs |
| ET-M2a-4 | False optimism at the decision threshold; abstention outside validated range | *proposed default:* ≤ 10%; abstention demonstrated |
| ET-M2a-5 | Success judge independent of training reward; disagreement tracking in place | no shared weights/labels; report produced |

**Warning kept from review.** A task-conditioned demonstration generator is not an interactive policy environment. A feature-space adapter is checkpoint-specific and experimental; do not call it interchangeable with rendered observations without paired validation.

## M2b — Real-arm evaluator validation

**Deliverable.** Physical validation under the frozen protocol (`docs/EVALUATION_PROTOCOL.md`): ranking on held-out real checkpoint pairs with randomized within-pair order and paired analysis, false optimism, selection regret, episodes saved, one authorized sealed-suite opening.

**Prerequisites.** M2a passed; SO-101 operational; bench kit (fixed cameras, placement template, success sensors) in place; owner approval for arm motion (`AGENTS.md §2.3`).

| Exit test | Statement | Threshold |
|---|---|---|
| ET-M2b-1 | Physical protocol frozen; rubric double-labelled on ~20 mixed episodes | *proposed default:* agreement ≥ 90%, adjudication rules recorded |
| ET-M2b-2 | Ranking on held-out real pairs with paired analysis | *proposed default:* selection regret ≤ 5 points; false optimism ≤ 10%; sample size from a precision plan |
| ET-M2b-3 | Episodes saved at validated selection error; cost per evaluated checkpoint | reported with denominators |
| ET-M2b-4 | One sealed confirmation suite opened once under logged authorization; result reported regardless | exactly one opening; candidate hashes frozen first |

**Statistics.** At 20 episodes a 60% success rate has a 95% Wilson interval of roughly 39–78%; at 50, 46–72%. Start with visibly different candidates; close pairs only once the evaluator has earned that claim. Analyze pairs (McNemar or exact), block by session, predeclare exclusions.

## M3 — Synthetic-data engine (SFT route)

**Deliverable.** Two separate pipelines — A: known actions → predicted observations; B: task + initial image → generated demonstration → inverse-dynamics pseudo-actions — on matched, reconstructible simulated scenes; a physics-replay executability filter (initial state only); a matched-budget downstream ablation; cost per accepted trajectory.

**Prerequisites.** M0 passed (matched scenes); generator and IDM as scoped; downstream policy training access. Can start as a sim-only prototype without claiming real-arm improvement.

| Exit test | Statement | Threshold |
|---|---|---|
| ET-M3-1 | Generation from known sim scenes with initial state and asset hashes saved first; scene-consistency check rejects injected mismatches | *frozen:* 100% of 60 injected rejected, at most 3 of 60 controls falsely rejected (`evals/M3-exit-tests.json`) |
| ET-M3-2 | IDM actions replayed from initial state only; executability and false accept/reject measured on an audited sample | *proposed default:* false acceptance ≤ 10% on ≥ 100 audited |
| ET-M3-3 | Matched-budget ablation (real-only / real+augmentation / real+generated), ≥ 3 seeds, held-out success with intervals | benefit claimed only above a frozen margin; negative result is valid |
| ET-M3-4 | Cost per accepted trajectory including rejected generations | reported |
| ET-M3-5 | Generated demos feed SFT only; GRPO uses on-policy samples only | code-path audit clean |
| ET-M3-6 | Targeted synthetic failure data improves prediction on a failure family held out from training (owner D2, 2026-11-06); target `m0-scripted-missed-grasp` | *frozen:* F3 beats F1 at every horizon, both streams, all seeds, losing at most 2 points on the no-harm holdout (`evals/M3-exit-tests.json`) |

Details: `docs/SYNTHETIC_DATA_M3.md`.

## M4 — Drone dynamics adaptation (offline and shadow only)

**Deliverable.** Residual-dynamics model for the drone on imported SITL and later real flight logs; calibrated uncertainty and a proposed trust gate (the research question in `PROGRAM.md §8.2`); shadow-mode predictions logged only; exported model manifest at the contract boundary. **No command authority; live use is a future drone-owned work order.**

**Prerequisites.** M1 infrastructure; drone episodes exist (banshee D1 or later). Branches from M0/M1; never waits for M2/M3. **Before shadow mode (owner, 2026-11-02):** close the planner real-time gap. The M1 planner takes about 100 ms per decision against a 50 ms control period (`reports/WO-005-m1-planner-and-chunk-scorer.md`).

| Exit test | Statement | Threshold |
|---|---|---|
| ET-M4-1 | Drone episodes imported read-only and validated | *frozen:* 100% `contract_valid` (`evals/M4-exit-tests.json`) |
| ET-M4-2 | Residual model beats nominal on held-out flight families: 20-step (1 s) open-loop rollout from logged setpoints, step-20 position error, equal-weight family mean | *frozen (owner, 2026-11-06; amended 2026-11-07):* the 3-seed ensemble's RMSE ≤ 0.85 × nominal RMSE (`evals/M4-exit-tests.json`, `evals/M4-amendment-1.json`); each seed and per-family scores reported, not gated |
| ET-M4-3 | Uncertainty calibrated; gating rule evaluated offline; shadow logs only; no setpoint code path | code audit clean |
| ET-M4-4 | Exported model manifest complete with validity limits; `command_authority` false | manifest hash |

## Beyond M4 (milestone-level; detailed when they become next)

| Phase | Name | Question it answers | Prerequisites | Exit tests |
|---|---|---|---|---|
| M5 | Verifier at test time (best-of-N chunks) | Does best-of-N with the validated scorer/judge buy the same real-success gain as RL fine-tuning, and at what N does it stop? | M2b | ET-M5-1 (success vs N, paired, vs N=1 and GRPO), ET-M5-2 (compute per episode; N where gains stop) |
| M6 | Verifier as reward for real-robot RL | How many human labels can a learned judge safely replace in HIL-SERL-style RL, and how does it fail? | M5 | ET-M6-1 (labels saved; disagreement tracked), ET-M6-2 (failure modes documented) |
| M7 | Data curation loop | Which experience should go back into training, and what are the scaling curves? | M3, M5 | ET-M7-1 (curves with intervals) |
| M8 | New embodiment: LEAP hand on a stand | Can a sim-trained evaluator pick the better real in-hand policy without real episodes? | M2b | ET-M8-1 (selection regret, with/without tactile) |

### M5 — Verifier at test time
Sample N action chunks from the VLA, score them with the validated scorer/judge, execute the best; no retraining. Exit tests ET-M5-1 and ET-M5-2 above.

### M6 — Verifier as reward for real-robot RL
HIL-SERL-style online RL on the real arm where the learned judge replaces as many human labels as it safely can; the final assessment stays independent. Exit tests ET-M6-1 and ET-M6-2.

### M7 — Data curation loop
Which experience goes back into training, with scaling curves. Exit test ET-M7-1.

### M8 — New embodiment: LEAP hand on a stand
Same schema, evaluator and pipeline for a new embodiment; in-hand reorientation needs no arm. Exit test ET-M8-1.

The thesis-level question across M4–M8: which parts of a learned evaluator / world model transfer across embodiments, and which must be rebuilt per robot (`PROGRAM.md §8.2`).

## Baselines (every comparison names its baseline)

| Area | Baselines |
|---|---|
| State prediction | constant / linear extrapolation; nominal dynamics; small learned model |
| Planning | nominal-model MPC; learned-model MPC; scripted controller; existing model-free GRPO policy where observation access matches |
| Evaluation | physics-simulator evaluator; simple logged metrics; ranking without learned evaluation |
| Synthetic data | real-only SFT; real + ordinary augmentation; real + generated, matched budgets |

Every comparison reports observation access, interaction data, pretraining, compute and inference latency.

## Reports

One report per accepted work order and one per phase exit (`docs/REPORT_TEMPLATE.md`). Negative results are valid deliveries. Generalization claims need fresh confirmatory evidence after any change informed by revealed test data.
