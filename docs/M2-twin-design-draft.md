# M2-twin design draft: a calibrated physics twin of the SO-101 bench as the M2a evaluator

**Status:** draft for owner review, 2026-11-08. Nothing in it is frozen, built, recorded or run. No exit test changes until the owner has seen this text and a later work order freezes it (`AGENTS.md §5.2`).
**Authorization:** owner, 2026-11-08, item 1 of `approvals-20261108T132556755986Z-2add2fa0`: "M2a — Yes, draft the redesign. Build a calibrated physics simulator of our SO-101 bench for one pick-and-place task. Keep checkpoint input compatibility, and separate the real recordings used for calibration from the held-out trials used to validate policy rankings. Defer the from-scratch image generator." Still in force: arm motion and deployment need separate approval; ET-M3-1 and drone training stay on hold; no spending.
**Builds on:** `AGENTS.md §13.1, §13.3, §13.6`; `docs/PHASES.md` (M2a, M2b); `config/phases.json`; `docs/EVALUATION_PROTOCOL.md`; `docs/DATA_AND_SNAPSHOTS.md`; `work_orders/WO-017-m2a-mac-pilot.md`; `work_orders/WO-018-m2a-gpu-pilot.md`; `src/vishwaroop/sim/env.py`. The owner's 2026-11-08 program review (kept outside the repository) supplied leads; each external claim used here is checked in §8.

> Labels (`AGENTS.md §7.2`): **measured** = ran in this repository, evidence attached; **estimated** = arithmetic from stated assumptions; **not run** = not run. A number quoted from a paper is marked "(cited, §8)" and is that paper's measurement, not ours. Every threshold below is a **proposed default**.

## 0. The change in one paragraph

Today M2a's deliverable is a learned "action-conditioned observation model" trained from scratch. This draft replaces it with a **physics twin**: ManiSkill3 with an SO-101 asset, whose servo, object and camera parameters are fitted to real recordings of the owner's bench, running one pick-and-place task. The twin renders every camera the evaluated checkpoint consumes, steps at the checkpoint's rate, and judges success from privileged simulator state. Its claim is narrow: on this bench and this task, the twin **ranks held-out policy families the way the real arm does**, measured against real trials never used to build it. The from-scratch image generator is deferred behind a gate (§5). In simulation the simulator is the oracle (`PROGRAM.md §5.4`), so a twin earns its keep only by agreeing with the real bench. That is why M2a now needs real trials.

**Consequence the owner should see first:** M2a stops being simulation-only. Its ranking test needs real rollouts of held-out policies, which is arm motion (`AGENTS.md §2.3`). This draft assumes the owner performs every real recording under separate approval; no code in this repository connects to the arm (§6, open question Q1).

## 1. What the twin is

### 1.1 The one task (proposed)
| Item | Proposal |
|---|---|
| Task | `so101-pickplace-cube-bin`: pick one cube from a templated start pose and release it inside a fixed open bin. It is the `docs/EVALUATION_PROTOCOL.md §3` "PickPlace first" task, and it extends the rigid-object, single-arm scene this repo already runs (`PickCubeSO100-v1`). |
| Instruction | One fixed string, e.g. `"pick up the red cube and place it in the bin"`. It must match the instruction the arm project trained with byte for byte; the compatibility check (§2.3) enforces this. |
| Objects | One rigid cube (about 30 mm, matte, single colour, measured mass) and one rigid open bin (about 120 × 120 × 40 mm, fixed to the table). Rigid, matte and opaque, so contact and rendering stay within what PhysX and a rasterizer model well. A second object (for example a cylinder) is a later shift axis, not part of M2a. |
| Placement template | A printed sheet fixed to the table by dowel pins or tape marks: cube start poses on a 3 × 3 grid at 40 mm pitch, two yaw angles (0°, 45°), so 18 named placements; the bin at one printed location; a ChArUco or AprilTag board printed in a corner for camera extrinsics. The same 18 placements are instantiated in the twin from the template's measured pose in the robot base frame. |
| Success (both sides) | Cube's centre inside the bin footprint, gripper open, cube resting for ≥ 1 s, before the episode timeout. Real side: the `docs/EVALUATION_PROTOCOL.md §4` rubric (blinded video review plus sensors). Twin side: the same predicate on simulator state. |
| Episode | Start and end at a fixed home pose; timeout proposed at 30 s. |

### 1.2 Simulator, asset and pins
- **Simulator:** ManiSkill3 `mani_skill 3.0.1` with SAPIEN `3.0.3`, already resolved in `config/stack-lock.resolved.v2.json` and running on the owner's Mac (CPU PhysX, CPU rendering; measured in WO-001 and WO-017). No new simulator.
- **SO-101 asset:** upstream ManiSkill has an `so100` robot but no `so101` (verified, §8). Two candidates: (a) the URDF and meshes vendored in the Squint repository (MIT licence, "moved to `mani-skill==3.0.1`" on 2026-10-17 per its README); (b) TheRobotStudio's official `so101_new_calib.urdf` (repository `SO-ARM100`, folder `Simulation/SO101`). Proposal: start from (b), the manufacturer's geometry, and use (a) as a cross-check for collision meshes and gripper setup. Owner decides (Q6).
- **Pins needed before any fit:** asset repository commit plus sha256 of every asset file (the pattern of `ManiSkillPickCube.asset_manifest()`); a new environment id added to `KNOWN_ENV_IDS`; physics settings (sim frequency, solver iterations, contact offsets) in a versioned config; the twin parameter file's sha256; the camera calibration ids. The `SimEnv` protocol in `src/vishwaroop/sim/env.py` stays the interface; the twin is a second implementation next to `ManiSkillPickCube`, with image streams added.
- **Version note:** ManiSkill's SO-100 grasp-reward bug (issue 1427, a lead from the review; not checked here) does not touch this design, because the twin's judge is its own predicate, not the environment's reward.

### 1.3 What is system-identified, and from what
Each parameter is fitted on calibration recordings only (§3), stored with the hashes of the episodes it came from, and versioned under a calibration id. A mount change, servo swap, gain change or firmware change opens a new calibration id (`docs/DATA_AND_SNAPSHOTS.md §3`).

| Parameter | Per | Recording (owner-run) | Fit |
|---|---|---|---|
| Command-to-motion latency | joint | step and chirp targets, plus teleop where leader position = command | delay that minimises replay error |
| Effective P gain (position-loop stiffness), damping | joint | steps of several sizes, holds under load | PD drive stiffness and damping in the twin |
| Backlash and firmware deadband | joint | slow back-and-forth sweeps from both directions | dead-zone width in the twin's joint controller |
| Gravity sag | arm pose | static holds at a grid of poses; tip position from the top camera's tag | link mass and centre-of-mass offsets, with the fitted gain |
| Joint friction (Coulomb, viscous) | joint | slow constant-velocity sweeps | joint friction terms |
| Velocity and torque limits, gripper close speed and force | joint, gripper | fast steps; gripper closing on the cube | limits; gripper drive |
| Cube and bin mass | object | kitchen scale | measured directly, not fitted |
| Cube–table and cube–finger friction | object | tilt-plane slip angle; scripted push | static and dynamic friction |
| Camera intrinsics | camera | checkerboard or ChArUco captures at the policy's resolution | OpenCV calibration; reprojection error recorded |
| Camera extrinsics | camera | template board visible at session start | board pose → camera pose in the robot base frame |
| Exposure, white balance, colour | camera | locked settings; colour chart or the cube and table under bench light | fixed per-camera colour transform (§2.2) |

Method: a black-box optimiser (CMA-ES or Nelder–Mead) over about 15 to 25 parameters (estimated count), minimising open-loop replay error of measured joint trajectories over short windows, starting from the measured initial state. Replay restores the initial state only (`AGENTS.md §13.5`), as M0 does. Whether the drives are modelled as PhysX joint drives or as an explicit servo model that writes joint targets each physics substep is decided in the design dry run (§6), on disposable sessions.

## 2. Checkpoint input compatibility

`AGENTS.md §13.1`: an M2 claim requires the twin to reproduce **every input** the evaluated checkpoint expects. The twin therefore owns the whole observation path up to the policy's own preprocessor.

### 2.1 What each checkpoint expects (read from its export, never assumed)
For each registered checkpoint (WO-006 registry, immutable export), an **input-spec manifest** is derived from the export's own policy config and dataset metadata: each image key with camera name, raw resolution, channel order and dtype; the state vector's joint names, units and order; the observation history length; the control rate; the action vector's meaning, units and chunking (chunk length, steps executed per inference, temporal ensembling); the instruction string; the normalisation statistics' hash; the inference library and version. Which cameras the arm project's policies use (front, top, wrist) and at what resolution and rate is not known yet (Q2); the design does not depend on the answer, but the rendering work in §2.2 does.

### 2.2 How the twin produces each input
- **Joint state:** read from the twin's joints, converted to the export's units and joint order, with the fitted deadband applied to the *reported* position as the real servo reports it.
- **Images:** rendered by SAPIEN's rasterizer from the calibrated intrinsics and extrinsics of each real camera, at the camera's **raw** recording resolution, then passed through the policy's own preprocessing, exactly as real frames are. Never pre-resized by the twin.
- **Domain matching, with no learned generator:** (1) textures for the table, template, cube and bin from photographs taken on the bench; (2) for fixed cameras, a SIMPLER-style "visual matching" option: the real empty-scene background image composited behind the rendered robot and objects (cited, §8); (3) the fixed per-camera colour transform from §1.3; (4) light placement matched to the bench lamp. A wrist camera cannot use a static background, so it relies on (1), (3) and (4); it is the hardest input to match (risk R3).
- **Rate and timing:** physics substeps at a multiple of the policy rate; inference called at the rate, history and chunk execution the manifest says; the measured observation-to-action latency of the real deployment loop injected as a delay. Where the real loop's latency is unknown, the twin abstains (§4, ET-M2a-4).
- **Instruction:** passed verbatim from the manifest.

### 2.3 The check, before any evaluation counts
1. **Spec comparison:** the twin declares a manifest of what it can supply (keys, shapes, dtypes, units, rates, camera calibration ids, instruction). A checker compares it field by field with the checkpoint's input-spec manifest. Any mismatch is a refusal recorded with its reason. Nothing is coerced.
2. **Loopback test:** real frames and joint states from a real policy rollout recorded on this bench go through the same adapter path the twin uses; the checkpoint's actions must equal the actions logged in that rollout within a tolerance fixed per architecture. This shows the adapter is the deployment path, not a lookalike.
3. **Execution-config test:** chunk length, steps per inference and ensembling read back from the running harness equal the manifest.
Policy weights load with safe loaders only (`safetensors`, `weights_only=True`) after hash verification (`AGENTS.md §6.6`). Inference uses a pinned third-party library (for example LeRobot or openpi) installed in this repository's environment, never the arm project's code (`AGENTS.md §13.4`).

## 3. Data separation: calibration recordings vs held-out validation trials

### 3.1 The partitions
| Set | Contents | Used for | Contract partition |
|---|---|---|---|
| **C-fit** | system-identification sessions; teleop sessions declared as calibration | fitting twin parameters (§1.3) | `train` |
| **C-check** | calibration-style sessions held out by session | fidelity test ET-M2a-2 only | `dev` (scene group `calib-check`) |
| **V-dev** | real rollouts of **development policy families** (set D) | choosing rendering options, the twin's calibration map (§4, ET-M2a-4) and abstention bounds | `dev` (scene group `policy-dev`) |
| **V-hold** | real rollouts of **held-out policy families** (set H) | ranking test ET-M2a-3 and false optimism ET-M2a-4, read once after the twin is frozen | `dev` (scene group `policy-hold`) |
| **V-sealed** | a later, disjoint real suite | M2b's one sealed opening (ET-M2b-4) | `sealed` |

Rules, following `AGENTS.md §13.3` and `docs/EVALUATION_PROTOCOL.md §1`:
- **By session:** a recording session belongs to one set. No session contributes to both a C set and a V set, and C-check sessions are disjoint from C-fit sessions.
- **By policy training run/family:** D and H are disjoint sets of training runs, fixed in the WO-006 registry (`holdout: true` for H). Adjacent checkpoints of one run are never split across D and H. In H, at most one checkpoint per training run, so each ranked unit is an independent run.
- **Outcome blindness:** V-hold outcomes are labelled by blinded reviewers and are not read by the agent until the twin's parameter file, rendering config and calibration map are frozen and their hashes recorded in the status ledger. V-hold is "dev", not "sealed": it is one scoring, after which it becomes regression data for later twin versions.
- **Provenance check:** every twin parameter file carries the hashes of the episodes it was fitted on; a test refuses a twin whose inputs include any V session or any H-family rollout.
- **Policy training data:** the arm project's demonstrations may also serve as C-fit data (leader position is the command, follower position is the response) only if their sessions are declared C before the fit and never appear in V. Q5 asks the owner.

### 3.2 Who records what
| Recording | Who | How it reaches this repository |
|---|---|---|
| Excitation sessions (steps, chirps, sweeps, holds) | owner, at the bench, under a separate arm-motion approval | owner plays agent-written target files through LeRobot's own tools (Q3); LeRobot dataset → real-episode importer → `data/imports/` |
| Camera and object calibration captures | owner | same importer; `reference_only` streams |
| Teleop sessions declared as calibration | owner | same importer |
| Policy rollouts (V-dev, V-hold) | owner runs the arm project's checkpoints under the frozen physical protocol (`docs/EVALUATION_PROTOCOL.md §3`) | immutable arm-project export with `COMPLETE`, verified by `src/vishwaroop/importer.py` |
| Success labels for V | blinded reviewers per `docs/EVALUATION_PROTOCOL.md §4` | label files referencing episode hashes |

Agents write protocols, target files, manifests and analysis code; they never command the arm.

### 3.3 Declared and audited before data exists
A split declaration (proposed file `evals/M2a-data-split.json`) is frozen and its sha256 appended to the status ledger **before the first calibration session is recorded**. It names: session-id prefixes per set; the calibration-id scheme; the D and H training runs (by registry id), or, if the runs do not exist yet, the rule that assigns runs to D or H before their real outcomes exist (for example by a hash of the run id); the placement list for V trials; and the order rule (randomised within pairs, blocked by session). Each recorded session carries its set label in its collection manifest, written before recording. `ironclad-audit-splits` runs on every assembled set, plus the provenance check of §3.1.

## 4. Proposed ET-M2a exit tests (not frozen)

**These replace the five texts in `config/phases.json` only after the owner approves, a design dry run on disposable sessions has checked that each statistic is computable and non-degenerate, and a freeze work order records the hash.** The shape is kept: compatibility, fidelity (formerly branch consistency), ranking on held-out runs, false optimism and abstention, judge independence. One test is added: data separation.

| Id | Statement | Evidence | Threshold (all *proposed default*) |
|---|---|---|---|
| ET-M2a-1 | Policy compatibility: for each supported checkpoint family the twin supplies every input the checkpoint expects (images at raw resolution and history, joint state, instruction, rate, chunk execution), shown by the spec comparison, the loopback test and the execution-config test (§2.3). | compatibility log per checkpoint | 100% of checks pass for each family evaluated; any refusal blocks that family. |
| ET-M2a-2 | Twin fidelity on C-check sessions (held out by session from the fit): (a) open-loop joint replay over 2 s windows from the measured initial state; (b) paired-state observation test: the twin set to the measured joint state and object pose, its rendered inputs and the real inputs fed to each D-family policy; (c) outcome agreement on open-loop replay of whole real C-check episodes. | replay error tables; action-discrepancy table; paired outcome table | (a) per-joint median RMSE ≤ 1.5° and ≤ 50% of the uncalibrated nominal twin's; (b) median twin-vs-real action discrepancy ≤ 2 × the median discrepancy between two real frames of near-identical state from different sessions; (c) outcome agreement ≥ 80%. |
| ET-M2a-3 | Ranking reliability on held-out policy runs (set H; ≥ 8 runs, ≥ 2 architectures, one checkpoint per run, ≥ 30 real trials each on the 18 template placements, twin trials on the same placements). Compared against "no evaluator" baselines: B0, random choice (expected pairwise accuracy 50%); B1, the selection rule available without an evaluator (the most-trained checkpoint, or lowest offline validation loss); B2, the uncalibrated nominal twin. | ranking table; Pearson, Spearman, MMRV; pairwise accuracy; paired bootstrap over runs and sessions | Spearman ρ ≥ 0.7; Pearson r ≥ 0.7; MMRV ≤ 0.10; pairwise order correct on ≥ 80% of pairs with a predeclared visible real gap (≥ 20 points); twin beats B1 and B2 on pairwise accuracy with the 90% paired-bootstrap interval of the difference excluding 0. Otherwise reported as "not distinguishable from no evaluator", a fail. |
| ET-M2a-4 | False optimism and abstention. The twin's success estimate goes through a calibration map fitted on D families only. False optimism = fraction of matched (policy, placement) cells where the twin predicts success and the real trial failed; bias = mean (twin − real) success over H. Abstention: the twin returns "insufficient evidence" on an incompatible checkpoint, an unknown camera calibration id, a placement outside the template, an unmeasured control latency, an architecture with no D family, or a C-check drift alarm. | confusion table; bias with interval; abstention test log on constructed out-of-range cases | false optimism ≤ 15%; bias ≤ +10 points; 100% abstention on the constructed out-of-range cases. |
| ET-M2a-5 | The twin's success judge is a predicate on simulator state, separate from any training reward model and from the real rubric; twin-judge vs real-rubric disagreements on matched cells, and training-reward vs judge disagreements, are tracked (`docs/EVALUATION_PROTOCOL.md §7`). | code audit; disagreement ledger | no shared weights, labels or code between training reward, twin judge and real rubric; disagreement report produced. |
| ET-M2a-6 (new) | Data separation: the split declaration was frozen before the first recording; no V session or H-family rollout entered any twin parameter, rendering choice or calibration map; V-hold outcomes were first read after the twin's hashes were recorded. | split hash and status-ledger time order; `ironclad-audit-splits` output; provenance check output | pass/fail; any violation is a fail, not an exclusion. |

**Why these numbers (all to be revisited at the dry run, none frozen).** Spearman 0.7 and 80% pairwise are carried from the current ET-M2a-3. MMRV ≤ 0.10 sits above SIMPLER's reported average of 0.056 for its visual-matching variant (cited, §8), because this twin is built by one person on a hobby arm. With 8 runs, ρ = 0.7 corresponds to a one-sided permutation p of 0.029 (arithmetic: exact enumeration of all 8! rankings, no data), so the interval will be wide; 8 is a floor, not a target (Q4). Fidelity bound 1.5° rests on the review's lead that STS3215 backlash is about 0.87° (unverified, §8) and is the most likely number to move at the dry run. Real-trial cost: 8 runs × 30 trials = 240 trials, about 6 to 8 owner hours at 1.5 to 2 minutes per trial including reset (estimated), plus D-family and C sessions.

**What a pass means.** That on this bench, this task, these placements and these policy families, the twin ranked held-out runs like the real arm. It is not physical success for any policy, and it licenses no counterfactual claim beyond its validated distribution (`AGENTS.md §13.6`, `docs/EVALUATION_PROTOCOL.md §8`). M2b keeps its role: frozen physical protocol, selection regret, episodes saved and the one sealed opening, on V-sealed.

## 5. The deferred image generator, and what stays from WO-017 and WO-018

**Gate to reopen a learned observation model** (all four, in order):
1. The twin's ET-M2a-3 has been scored once and missed its frozen threshold, or passed but the owner wants a claim it cannot support.
2. The failure analysis attributes the shortfall to the **observation** path, not dynamics: ET-M2a-2(b) fails or its residual tracks the ranking errors, while 2(a) and 2(c) pass. A dynamics shortfall is fixed in the twin, not with pixels.
3. Enough real data exists for a fine-tune, never a from-scratch model: the review's lead is at least about 1,000 real episodes, modelled on WorldEval's LoRA fine-tune of a pretrained video model on about 1,400 trajectories (unverified, §8).
4. A measured pilot gives the cost, and the owner approves the spending (`AGENTS.md §2.3`). The same ET-M2a texts apply to it unchanged, so the generator and the twin are compared on one scale.

**What stays.**
- WO-017 (accepted) stays as recorded. Its measured numbers become planning inputs: CPU rendering at 412 frames per second at 512 × 512 while stepping, and 62.3 images per second tokenizer training on MPS (measured, `reports/WO-017-m2a-mac-pilot.md`). Its tokenizer code is not extended.
- WO-018 (in progress, no VM): its Mac frame bundle (3,720 frames, sha256 recorded in the status ledger) stays an immutable artifact but is not twin data. Per the owner's item 2 the pilot plan is being revised (SO-101 simulator throughput and VLA inference latency) and returns for a fresh approval; this draft only states what the twin would want measured there (§6.2).
- Kept for the twin: the `SimEnv` protocol, save/restore from the initial state, the replay machinery, the split audit, the importer, and the independent judge discipline.

## 6. Dependencies and work orders

### 6.1 Prerequisites
| Dependency | State today | Needed for |
|---|---|---|
| Real-episode importer (owner item 4, $0; LeRobot dataset → contract v1 with image streams and `reference_only` object pose) | being built on fixtures; no number assigned in this checkout | every real recording |
| Arm-project exports (checkpoints with config, preprocessor, normalisation stats, weights in `safetensors`, eval results, `COMPLETE`) | none exist | ET-M2a-1, -3, -4 |
| WO-006 policy registry with `holdout` per run | created, not started | D/H split |
| Bench prerequisites: fixed cameras with locked exposure and white balance, fixed lighting, printed template with board, servo gains settled (P gain decided once, then a calibration id), session-start drift check, AprilTag or colour object pose from a top camera as `reference_only` | kit arrived 2026-11-08; not set up | every recording |
| Owner approval for arm motion (calibration sessions; policy rollouts) | not given | C and V sets |
| Compute | Mac CPU physics and CPU rendering (platform of record); MPS for ACT-class inference (expected, not run). π0.5-class inference likely needs a CUDA GPU (about 10 GB, a lead from the review; unverified). No rental approved. | twin rollouts of π0.5 |

### 6.2 Compute, estimated
Twin rollouts for ET-M2a-3: 10 policies × 18 placements × 5 repeats ≈ 900 episodes; at about 600 control steps per 20 s episode at 30 Hz, two rendered cameras, and an assumed 10 to 30 s wall time per episode on the Mac for an ACT-class policy, about 2.5 to 7.5 Mac hours (estimated; the 10 to 30 s is an assumption, not a measurement). System identification: thousands of short replay windows per optimiser run, CPU-bound, a few Mac hours per fit (estimated). π0.5 rollouts are the open cost: at an assumed 0.1 to 0.3 s per inference on a rented card, 900 episodes need roughly 1 to 4 GPU hours plus setup (estimated, not run); this belongs in the revised WO-018 plan, not here.

### 6.3 Ordered work orders (proposed; sizes per `work_orders/README.md`)
| # | Work order | Size | Needs |
|---|---|---|---|
| 1 | ADR recording the M2a redesign; `docs/PHASES.md` and `config/phases.json` deliverable text updated, ET texts marked "proposed, not frozen" | S | owner approval of this draft |
| 2 | Real-episode importer (already approved, in progress) | M | none further |
| 3 | SO-101 twin scene: pinned asset, environment id, template scene, image streams on the `SimEnv` protocol, CPU-tier tests with a fake | M | 1 |
| 4 | Input-spec manifest and compatibility checker (spec comparison, loopback, execution config), tested on fabricated policy configs | S | 3; real exports for the loopback test |
| 5 | Bench calibration protocol, excitation target files, collection manifests and the split declaration (frozen before any recording) | S | 1; owner bench setup |
| 6 | Design dry run on disposable sessions: fit pipeline and every ET statistic computed end to end; thresholds proposed for freezing | S | 3, 5; a few owner-recorded disposable sessions (arm motion approval) |
| 7 | Freeze ET-M2a (exit tests and protocol hashes in the status ledger) | S | 6; owner sees the final text |
| 8 | System identification on C-fit; ET-M2a-2 scored on C-check | M | 7; C recordings |
| 9 | Camera calibration, rendering match, paired-state observation test (ET-M2a-2b) | M | 7; C recordings, D-family exports |
| 10 | Twin evaluator runner: closed-loop rollouts, judge, calibration map on D, abstention; resumable by episode (`AGENTS.md §13.9`) | M | 4, 8, 9 |
| 11 | Held-out ranking: ET-M2a-3, -4, -5, -6 scored once; independent review and recheck (`AGENTS.md §13.8`) | M | 10; V-hold recorded and labelled; π0.5 compute if in H |

## 7. Risks and open questions

### 7.1 Risks
- **R1, few independent policies.** Eight held-out runs give a wide ρ interval, and the arm project may not produce eight runs with a real spread. Inducing spread with demo counts and training lengths is planned in the split declaration, not chosen after outcomes.
- **R2, contact physics.** The SO-101 gripper's small, compliant contacts may not replay in PhysX at the fidelity ET-M2a-2(c) asks. Open-loop replay of grasps amplifies small errors; the dry run may show 80% is out of reach for reasons unrelated to ranking.
- **R3, wrist camera.** If checkpoints consume a wrist view, background compositing does not apply and cables, gripper texture and close-range lighting are hard to match.
- **R4, drift.** Servo heat derating, backlash wear and gain changes move the real arm between sessions; a twin calibrated in one session can be stale in the next. The session-start drift check and calibration ids handle it, at the cost of re-fitting.
- **R5, sim optimism.** Twin success above real is common (a lead of 9 to 31 points on an SO-101 Isaac Lab benchmark, unverified, §8); the D-only calibration map and the bias bound address it.
- **R6, setup sensitivity.** Real-to-sim correlation varies with setup (a lead that a SIMPLER replication found r ≈ 0.40; unverified, §8). One bench and one task may not reproduce published correlations.
- **R7, π0.5 compute.** Without an approved GPU, H may contain only ACT-class runs, which weakens the "≥ 2 architectures" requirement.
- **R8, owner time.** About 240 V-hold trials plus D and C sessions is several bench days (estimated, §4).

### 7.2 Open questions for the owner
1. **Q1.** M2a now needs real trials (arm motion). Accept that M2a is no longer simulation-only, with M2b keeping selection regret, episodes saved and the sealed opening? Or move ET-M2a-3 into M2b and keep M2a to compatibility and fidelity?
2. **Q2.** Which cameras, resolutions, rates and instruction strings will the arm project's ACT and π0.5 policies use? The rendering plan depends on whether a wrist camera is among them.
3. **Q3.** For calibration sessions, may agents write joint-target files that the owner plays through LeRobot's tools, with no connection from this repository to the arm?
4. **Q4.** How many held-out runs and real trials per run will the bench budget support (proposed floor 8 × 30)?
5. **Q5.** May teleop demonstration sessions (the policies' training data) double as C-fit data if declared before the fit?
6. **Q6.** Asset source: TheRobotStudio's official SO-101 URDF (proposed) or Squint's vendored ManiSkill3 copy?
7. **Q7.** Servo P gain: settle it (LeRobot's SO-101 setup uses 16 against a servo default of 32, per a third-party mirror of its docs; the review suggests 32) once, before any recording, since a change invalidates the calibration.

## 8. External claims and their status (checked 2026-11-08)

| Claim used here | Status | Source |
|---|---|---|
| Squint (Almuzairee, Christensen; RA-L 2026) uses ManiSkill3 and an SO-101, trains in about 15 min on one RTX 3090, 73/80 (91.3%) real zero-shot over 8 tasks × 10 trials, wrist camera only; domain randomisation, no system identification described | verified (paper HTML) | https://arxiv.org/abs/2602.21203 ; https://arxiv.org/html/2602.21203v2 |
| Squint repository: MIT licence; `envs/robot/` holds robot URDF and meshes; "moved to `mani-skill==3.0.1`" (2026-10-17) | verified (README; `environment.yaml` not inspected) | https://github.com/aalmuzairee/squint |
| Upstream ManiSkill robots include `so100` but not `so101` | verified (main branch listing) | https://github.com/haosulab/ManiSkill/tree/main/mani_skill/agents/robots |
| TheRobotStudio publishes SO-101 URDFs (`so101_new_calib.urdf`, `so101_old_calib.urdf`) and an MJCF | verified | https://github.com/TheRobotStudio/SO-ARM100/tree/main/Simulation |
| SIMPLER (Li et al., CoRL): real-to-sim evaluation with "visual matching"; MMRV and Pearson r as metrics; visual matching average MMRV 0.056, r 0.924; validation MSE r 0.308 | verified (search summary of the paper and project page) | https://arxiv.org/abs/2405.05941 ; https://simpler-env.github.io |
| PolaRiS (Dec 2025): average r ≈ 0.9 over paired environments, worst 0.81, 0.98 against RoboArena, about 350 sim co-training demos; Ctrl-World MMRV 0.22 | verified (paper HTML) | https://arxiv.org/html/2512.16881v2 |
| A SIMPLER replication found r ≈ 0.40 | unverified (review lead; source not located) | none |
| An SO-101 Isaac Lab benchmark: Spearman 1.00 over 5 policies, sim success 9 to 31 points above real | unverified (news aggregator only) | https://aiweekly.co/alerts/so-101-bench-shows-sim-policy-rankings-match-real-hardware |
| STS3215 backlash about 0.87°, gravity sag 3 to 5 mm, P = 32 halving sag | unverified (review leads) | none |
| LeRobot SO-101 setup sets P = 16 against a servo default of 32 | partly verified (third-party mirror of LeRobot docs; the official page fetched does not show gains) | https://www.mintlify.com/huggingface/lerobot/robots/so-101 |
| WorldEval: LoRA on a pretrained video model, about 1,400 trajectories, about 88 GPU-h | unverified (review lead) | none |
| π0.5 inference needs about 10 GB of GPU memory | unverified (review lead) | none |
| ManiSkill SO-100 grasp-reward issue 1427 | not checked; not relied on | none |
