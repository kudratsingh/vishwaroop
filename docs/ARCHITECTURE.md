# ARCHITECTURE.md — World Model & Planner

Program context: `PROGRAM.md §5.2, §6, §8`. Phases and exit tests: `docs/PHASES.md`.

## 1. What this system is

A standalone platform that learns to **predict** what a robot's actions will do, **plans** with those predictions, **evaluates** policies without running them on the robot, and **generates** training data — with independent validation built in so the system knows when not to trust itself. First embodiment: the arm project's ManiSkill3 setup and its SO-101 arm. Later: drone flight logs (M4), a LEAP hand (M8).

Three products, three separate bodies of evidence:

| Product | What it answers | Interface | Evidence it needs |
|---|---|---|---|
| Predictor + planner + **action-chunk scorer** (M1) | "If the robot does this short sequence next, what happens, and how sure are we?" | observed history + candidate action chunk → predicted consequences, uncertainty, abstention | multi-step error vs baselines; action sensitivity vs executed simulator branches; calibration |
| **Closed-loop policy evaluator** (M2) | "How will this VLA checkpoint do, without running it on the real arm?" | checkpoint → predicted success distribution, ranking, abstention | every policy input reproduced; branch consistency; held-out policy runs; false optimism; selection regret; physical validation |
| **Synthetic-data engine** (M3) | "Can generated demonstrations improve a policy at matched budget?" | known scenes → filtered trajectories for SFT | matched-scene replay executability; filter ablation; downstream ablation; cost per accepted trajectory |

One world model does not automatically provide all three. A decoder-free latent model can plan and score action chunks; it cannot feed an unchanged image-consuming VLA its next observation. The evaluator therefore needs an **action-conditioned observation model** (M2), which is a separate, more expensive capability.

## 2. Ownership and boundaries

- **World Model owns:** read-only import, dataset registry and lineage, learned prediction and uncertainty, imagination, action-chunk scoring, closed-loop evaluation, synthetic-data generation and filtering, planning *proposals*, reports.
- **World Model never owns:** command authority over any robot or aircraft; the arm project's checkpoints, hardware, training or exports; live state estimation or safety behaviour on the drone.
- **The arm project** produces checkpoints, sim results and episodes through completed, immutable exports (`docs/DATA_AND_SNAPSHOTS.md`). Nothing here edits it.
- **Omni Drone** produces flight logs through the same contract and consumes exported model manifests; it can always reject a proposal or run without the learned component.
- **The contract** (`ironclad.contracts.v1`, from the pinned `ironclad-kit`) is the only shared technical boundary (`AGENTS.md §11`).

## 3. Modules (what exists, what is specified)

| Module | Path | Status | Responsibility |
|---|---|---|---|
| Core record helpers | `src/vishwaroop/core/` | implemented, tested | append-only ledgers, content-addressed artifacts, run directories, structured logs, strict config |
| Read-only snapshot importer | `src/vishwaroop/importer.py` | implemented (verification + registration), tested | refuses exports without `COMPLETE` marker or with hash mismatch; copies under read-only policy; records `ledgers/imports.jsonl` |
| Typed interfaces | `src/vishwaroop/interfaces.py` | implemented as Protocols | `Predictor`, `Planner`, `ChunkScorer`, `SuccessJudge`, `PolicyEvaluator`, `ObservationModel`, `TrajectoryGenerator` with units/frames/abstention contracts in docstrings |
| Simulator adapter (ManiSkill3) | `src/vishwaroop/sim/` | export, replay and negative tests implemented and tested on a fabricated fake; the ManiSkill3 adapter is written and **not run** (WO-001) | environment selection (ADR-0004) and lock; episode export through `ironclad.contracts.v1.writer`; initial-state-only replay |
| Independent outcome | `src/vishwaroop/outcome/` | implemented, tested on fabricated inputs | decides pick-and-place success from recorded simulator state; standard library only; shares nothing with a policy or reward |
| Dataset registry | `src/vishwaroop/data/` | **not implemented** (WO-002, WO-006) | manifests, splits by session and policy run/family, sealed-suite references, licenses |
| Predictors | `src/vishwaroop/models/` | **not implemented** (WO-004) | nominal + residual ensemble (state); compact latent predictor; calibration |
| Planner | `src/vishwaroop/planning/` | **not implemented** (WO-005) | CEM sampling MPC over bounded action sequences with known costs and uncertainty penalty; nominal-model baseline |
| Action-chunk scorer | `src/vishwaroop/scoring/` | **not implemented** (WO-005) | progress, clearance, constraint violation, uncertainty, abstention |
| Observation model + evaluator | `src/vishwaroop/eval/` | **not implemented** (M2a) | action-conditioned observation rollout matching the policy's inputs; independent success judge; ranking, false optimism, regret, abstention |
| Synthetic engine | `src/vishwaroop/synth/` | **not implemented** (M3) | pipeline A (action-conditioned), pipeline B (generated demo + IDM), replay filter, filter ablation |
| Reporting | `reports/`, `docs/REPORT_TEMPLATE.md` | template in place | per-WO and per-phase reports |

## 4. Prediction architecture (proposed default for M1; revise with evidence)

**State tier (first).** Nominal dynamics plus a learned residual, as a small probabilistic ensemble (3 members to start):

```
â_t = a_nominal(x̂_t, u_t, c_t) + r_θ(x̂_t, h_t, u_t, c_t)
```
`x̂_t` estimated state, `u_t` the action, `c_t` known context (controller mode, configuration version), `h_t` recent history. Integrate predicted rates to future states. Ensemble disagreement is the first uncertainty signal and is validated against actual error (ET-M1-3), never trusted on its own.

**Latent tier (second).** A recurrent state-space model with an observation-update mode (new evidence corrects belief) and an imagination mode (no future image available), PlaNet/Dreamer style; a frozen compact visual encoder to start; no image decoder for planning (TD-MPC2 style). Image generation is optional and only for representation learning, debugging or human review.

**Training unit.** Sequences `(o_t, u_t, o_{t+1}, …)` with a history segment to initialize belief, actions provided during the rollout, future observations withheld — the same information boundary the planner faces. Losses: motion, multi-step rollout, latent consistency; geometry and feature losses when visual inputs exist. Normalize physical quantities; balance terms so an image loss cannot drown a small motion error.

**Deployment-time inputs only.** Simulator ground truth may supervise but never feed the deployed model (no hidden wind, no future telemetry).

## 5. Planning (proposed default)

Sampling-based MPC (CEM): sample 128–256 bounded action sequences over a 1–2 s horizon, predict in batch, score with task cost plus uncertainty penalty, refine, execute the first action, observe, replan. Admissibility (limits, clearance) is enforced separately from the learned score. Encode observations once per step; never re-encode full images per candidate.

## 6. Evaluation architecture

- **Independent success judge.** Defined from simulator state in sim; from physical sensors plus blinded video review on the real arm (`docs/EVALUATION_PROTOCOL.md`). Separate from any training reward model; disagreement between the two is tracked as an alarm.
- **Tiers.** M1 open-loop action-chunk scoring (logged prefix → candidate chunk → short-horizon score; counterfactual claims only via executed simulator branches). M2a closed loop in sim (observation model supplies every policy input). M2b physical validation.
- **Holdouts.** By scene/session and by **policy identity** (training run/family, never adjacent checkpoints). Development suite for diagnosis; sealed confirmation suite opened once per milestone with logged authorization; revealed suites become regression-only.
- **Metrics.** Ranking reliability, false optimism, selection regret, calibration, abstention coverage, physical episodes saved. Correlation alone is not a release criterion.

## 7. Compute tiers (defined by measured workloads, not by "latent vs video")

| Workload | Budget line | Where it runs today |
|---|---|---|
| Training (state tier, compact latent) | peak memory, throughput, total cost per experiment | one rented 4090/A40-class GPU; later the owner's workstation |
| Offline generation / evaluation | cost per accepted trajectory; cost per evaluated checkpoint | same |
| Deployment (shadow) | end-to-end latency, deadline misses, behaviour when unavailable | logged only until a drone-owned WO authorizes more |

"One GPU" is not "real time": V-JEPA 2-AC's reported planning took ~16 s per action on a single RTX 4090 in its configuration. Measure before claiming suitability for any control loop.

## 8. Generality claims

Interfaces, training utilities, uncertainty methods and planning algorithms are shared across embodiments. Weights, action semantics and dynamics are not. Schema compatibility between the arm and the drone implies nothing about transferable dynamics; cross-embodiment transfer is a research question (`PROGRAM.md §8.2`), not an assumption.
