# M2-twin design draft: a calibrated physics twin of the SO-101 bench (M2a), validated on the real arm (M2b)

**Status:** draft for owner review, revised 2026-11-08 after the owner's second decision. Nothing in it is frozen, built, recorded or run. No exit test changes until the owner has seen this text and a later work order freezes it (`AGENTS.md §5.2`).
**Authorization:** owner, 2026-11-08, item 1 of `approvals-20261108T132556755986Z-2add2fa0`: "M2a — Yes, draft the redesign. Build a calibrated physics simulator of our SO-101 bench for one pick-and-place task. Keep checkpoint input compatibility, and separate the real recordings used for calibration from the held-out trials used to validate policy rankings. Defer the from-scratch image generator." Owner, 2026-11-08, M2a item of `approvals-20261109T010005936999Z-5e60e401`: "M2a — Keep it as the simulator milestone. Use owner-provided recordings for calibration and input-fidelity checks. Put new held-out physical policy trials, ranking validation, and real-world false optimism in M2b. Fix the split-rule conflict before freezing. The draft allows development rollouts for calibration in §3, while ET-M2a-6 forbids that use. Keep held-out outcomes out of every fit." Still in force: arm motion, deployment and every physical policy trial (including M2b's held-out trials) need separate approval; ET-M2a is not frozen before the owner sees this revision; ET-M3-1 and drone training stay on hold; no spending.
**Builds on:** `AGENTS.md §13.1, §13.3, §13.6`; `docs/PHASES.md` (M2a, M2b); `config/phases.json`; `docs/EVALUATION_PROTOCOL.md`; `docs/DATA_AND_SNAPSHOTS.md`; `work_orders/WO-017-m2a-mac-pilot.md`; `work_orders/WO-018-m2a-gpu-pilot.md`; `src/vishwaroop/sim/env.py`. The owner's 2026-11-08 program review (kept outside the repository) supplied leads; each external claim used here is checked in §8.

> Labels (`AGENTS.md §7.2`): **measured** = ran in this repository, evidence attached; **estimated** = arithmetic from stated assumptions; **not run** = not run. A number quoted from a paper is marked "(cited, §8)" and is that paper's measurement, not ours. Every threshold below is a **proposed default**.

## 0. The change in one paragraph

Today M2a's deliverable is a learned "action-conditioned observation model" trained from scratch. This draft replaces it with a **physics twin**: ManiSkill3 with an SO-101 asset, whose servo, object and camera parameters are fitted to owner-provided recordings of the owner's bench, running one pick-and-place task. The twin renders every camera the evaluated checkpoint consumes, steps at the checkpoint's rate, and judges success from privileged simulator state. The from-scratch image generator is deferred behind a gate (§5). The work splits across the two existing milestones:

- **M2a, the simulator milestone.** The calibrated twin, checkpoint input compatibility, fidelity on owner-provided calibration recordings held out by session, input-fidelity checks (paired-state observation), abstention on constructed out-of-range cases, judge independence, and data separation. M2a needs owner-provided recordings, not policy trials.
- **M2b, real-arm validation.** New held-out physical policy trials (V-hold), ranking validation against no-evaluator baselines, real-world false optimism and bias, plus M2b's existing tests: selection regret, episodes saved and the one sealed opening.

**Owner decision recorded (the previous draft's Q1; the questions in §7.2 are renumbered).** The previous draft asked whether M2a should stop being simulation-only, since its ranking test needed real policy trials. The owner answered on 2026-11-08: M2a stays the simulator milestone; held-out physical policy trials, ranking validation and real-world false optimism go to M2b. One data rule now applies everywhere (§3.1): every set has a declared use, and held-out outcomes stay out of every fit. Every real recording is still made by the owner under separate approval; no code in this repository connects to the arm.

## 1. What the twin is

### 1.1 The one task (proposed)
| Item | Proposal |
|---|---|
| Task | `so101-pickplace-cube-bin`: pick one cube from a templated start pose and release it inside a fixed open bin. It is the `docs/EVALUATION_PROTOCOL.md §3` "PickPlace first" task, and it extends the rigid-object, single-arm scene this repo already runs (`PickCubeSO100-v1`). |
| Instruction | One fixed string, e.g. `"pick up the red cube and place it in the bin"`. It must match the instruction the arm project trained with byte for byte; the compatibility check (§2.3) enforces this. |
| Objects | One rigid cube (about 30 mm, matte, single colour, measured mass) and one rigid open bin (about 120 × 120 × 40 mm, fixed to the table). Rigid, matte and opaque, so contact and rendering stay within what PhysX and a rasterizer model well. A second object (for example a cylinder) is a later shift axis, not part of M2. |
| Placement template | A printed sheet fixed to the table by dowel pins or tape marks: cube start poses on a 3 × 3 grid at 40 mm pitch, two yaw angles (0°, 45°), so 18 named placements; the bin at one printed location; a ChArUco or AprilTag board printed in a corner for camera extrinsics. The same 18 placements are instantiated in the twin from the template's measured pose in the robot base frame. |
| Success (both sides) | Cube's centre inside the bin footprint, gripper open, cube resting for ≥ 1 s, before the episode timeout. Real side: the `docs/EVALUATION_PROTOCOL.md §4` rubric (blinded video review plus sensors). Twin side: the same predicate on simulator state. |
| Episode | Start and end at a fixed home pose; timeout proposed at 30 s. |

### 1.2 Simulator, asset and pins
- **Simulator:** ManiSkill3 `mani_skill 3.0.1` with SAPIEN `3.0.3`, already resolved in `config/stack-lock.resolved.v2.json` and running on the owner's Mac (CPU PhysX, CPU rendering; measured in WO-001 and WO-017). No new simulator.
- **SO-101 asset:** upstream ManiSkill has an `so100` robot but no `so101` (verified, §8). Two candidates: (a) the URDF and meshes vendored in the Squint repository (MIT licence, "moved to `mani-skill==3.0.1`" on 2026-10-17 per its README); (b) TheRobotStudio's official `so101_new_calib.urdf` (repository `SO-ARM100`, folder `Simulation/SO101`). Proposal: start from (b), the manufacturer's geometry, and use (a) as a cross-check for collision meshes and gripper setup. Owner decides (Q5).
- **Pins needed before any fit:** asset repository commit plus sha256 of every asset file (the pattern of `ManiSkillPickCube.asset_manifest()`); a new environment id added to `KNOWN_ENV_IDS`; physics settings (sim frequency, solver iterations, contact offsets) in a versioned config; the twin parameter file's sha256; the camera calibration ids. The `SimEnv` protocol in `src/vishwaroop/sim/env.py` stays the interface; the twin is a second implementation next to `ManiSkillPickCube`, with image streams added.
- **Version note:** ManiSkill's SO-100 grasp-reward bug (issue 1427, a lead from the review; not checked here) does not touch this design, because the twin's judge is its own predicate, not the environment's reward.

### 1.3 What is system-identified, and from what
Each parameter is fitted on C-fit recordings only (§3.1), stored with the hashes of the episodes it came from, and versioned under a calibration id. A mount change, servo swap, gain change or firmware change opens a new calibration id (`docs/DATA_AND_SNAPSHOTS.md §3`).

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
For each registered checkpoint (WO-006 registry, immutable export), an **input-spec manifest** is derived from the export's own policy config and dataset metadata: each image key with camera name, raw resolution, channel order and dtype; the state vector's joint names, units and order; the observation history length; the control rate; the action vector's meaning, units and chunking (chunk length, steps executed per inference, temporal ensembling); the instruction string; the normalisation statistics' hash; the inference library and version. Which cameras the arm project's policies use (front, top, wrist) and at what resolution and rate is not known yet (Q1); the design does not depend on the answer, but the rendering work in §2.2 does.

### 2.2 How the twin produces each input
- **Joint state:** read from the twin's joints, converted to the export's units and joint order, with the fitted deadband applied to the *reported* position as the real servo reports it.
- **Images:** rendered by SAPIEN's rasterizer from the calibrated intrinsics and extrinsics of each real camera, at the camera's **raw** recording resolution, then passed through the policy's own preprocessing, exactly as real frames are. Never pre-resized by the twin.
- **Domain matching, with no learned generator:** (1) textures for the table, template, cube and bin from photographs taken on the bench; (2) for fixed cameras, a SIMPLER-style "visual matching" option: the real empty-scene background image composited behind the rendered robot and objects (cited, §8); (3) the fixed per-camera colour transform from §1.3; (4) light placement matched to the bench lamp. A wrist camera cannot use a static background, so it relies on (1), (3) and (4); it is the hardest input to match (risk R3). Every rendering choice is fitted on C-fit only (§3.1).
- **Rate and timing:** physics substeps at a multiple of the policy rate; inference called at the rate, history and chunk execution the manifest says; the measured observation-to-action latency of the real deployment loop injected as a delay. Where the real loop's latency is unknown, the twin abstains (§4, ET-M2a-3).
- **Instruction:** passed verbatim from the manifest.

### 2.3 The check, before any evaluation counts
1. **Spec comparison:** the twin declares a manifest of what it can supply (keys, shapes, dtypes, units, rates, camera calibration ids, instruction). A checker compares it field by field with the checkpoint's input-spec manifest. Any mismatch is a refusal recorded with its reason. Nothing is coerced.
2. **Loopback test:** real frames and joint states from an owner-provided **loopback recording** (a non-held-out checkpoint running on this bench, with its actions logged; set C-check, declared use "check"; its success outcome is not read) go through the same adapter path the twin uses; the checkpoint's actions must equal the logged actions within a tolerance fixed per architecture. This shows the adapter is the deployment path, not a lookalike. It runs once per architecture. Whether such a recording counts as an owner-provided input-fidelity recording is Q7.
3. **Execution-config test:** chunk length, steps per inference and ensembling read back from the running harness equal the manifest.
Held-out (H-family) checkpoints take part in M2a only through tests 1 and 3, which read their configs, not their outputs. Policy weights load with safe loaders only (`safetensors`, `weights_only=True`) after hash verification (`AGENTS.md §6.6`). Inference uses a pinned third-party library (for example LeRobot or openpi) installed in this repository's environment, never the arm project's code (`AGENTS.md §13.4`).

## 3. Data separation: one rule set for M2a and M2b

### 3.1 Declared uses and the sets
Every set has exactly one **declared use**, written in the split declaration (§3.3) before any of its sessions is recorded:

| Declared use | Meaning |
|---|---|
| **fit** | may enter a parameter, rendering choice, calibration map or threshold, but only those the set's row below names |
| **check** | scored, never fitted |
| **held-out** | scored once, never fitted |

"Threshold" here means an operating threshold inside the evaluator (for example the drift alarm or an abstention bound). Exit-test thresholds are frozen text; before freezing, only Disposable sessions may inform them, never C-check or a V set.

| Set | Contents | Milestone | Declared use | May enter | Contract partition |
|---|---|---|---|---|---|
| **C-fit** | owner-provided calibration recordings: excitation sessions, camera and object captures, teleop sessions declared as calibration | M2a | fit | twin physics parameters (§1.3), camera calibration, rendering choices and colour transform (§2.2), the drift-alarm threshold | `train` |
| **C-check** | owner-provided calibration-style sessions held out by session, plus the loopback recordings (§2.3) | M2a | check | nothing; scored for ET-M2a-1 (loopback) and ET-M2a-2 | `dev` (scene group `calib-check`) |
| **Disposable** | sessions recorded for the design dry run only | M2a | fit, for dry-run twin versions only | dry-run twin versions and the dry run's proposals for exit-test thresholds; never a frozen twin, never scored for an exit test | `dev` (scene group `dry-run`) |
| **V-dev** (if kept, Q8) | real rollouts of **development policy families** (set D) | M2b | fit | the M2b success-calibration map and abstention bounds only; never twin physics, camera calibration or rendering | `dev` (scene group `policy-dev`) |
| **V-hold** | new real rollouts of **held-out policy families** (set H) | M2b | held-out | nothing; scored once for ET-M2b-2, -3, -5 | `dev` (scene group `policy-hold`) |
| **V-sealed** | a later, disjoint real suite | M2b | held-out | nothing; opened once for ET-M2b-4 | `sealed` |

Rules, following `AGENTS.md §13.3` and `docs/EVALUATION_PROTOCOL.md §1`:
- **Held-out outcomes stay out of every fit.** V-hold, V-sealed and any other H-family rollout never enter a twin parameter, rendering choice, camera calibration, calibration map, threshold or abstention bound, in M2a or M2b.
- **The M2a twin is fitted on C-fit only.** No policy rollout (V-dev, V-hold or V-sealed) enters twin physics or rendering. Rendering choices may use the actions of non-held-out (D-family) checkpoints run offline on C-fit frames; that is C-fit data, not V-dev. H-family checkpoint outputs enter no fit.
- **Check sets are scored, never fitted.** C-check is scored only on twin versions whose hashes are already in the status ledger. If a C-check result leads to a change, the change is fitted on C-fit, the new version gets new hashes, and every scoring of C-check is listed in the report with its twin hash.
- **By session:** a recording session belongs to one set. C-check sessions are disjoint from C-fit sessions; no C session is also a V session.
- **By policy training run/family:** D and H are disjoint sets of training runs, fixed in the WO-006 registry (`holdout: true` for H). Adjacent checkpoints of one run are never split across D and H. In H, at most one checkpoint per training run, so each ranked unit is an independent run.
- **Order of freezing and reading.** M2a's twin (parameter file, rendering config, camera calibration ids) is frozen and hashed before M2b starts; M2b uses that exact hash. V-dev is declared before it is recorded. The success-calibration map and abstention bounds are frozen and hashed before any V-hold outcome is read. V-hold outcomes are labelled by blinded reviewers and read once; afterwards V-hold may be re-scored as regression data for later twin versions (check use), and no later version may claim it as held-out.
- **Provenance check:** every fitted artifact (twin parameter file, rendering config, colour transform, camera calibration, drift threshold, success-calibration map, abstention bounds) carries the hashes of the episodes it was fitted on and their declared sets. A test refuses an artifact if any input episode's set does not declare "fit" for that artifact in the table above.
- **Policy training data:** the arm project's demonstrations may also serve as C-fit data (leader position is the command, follower position is the response) only if their sessions are declared C-fit before the fit and never appear in a V set. Q4 asks the owner.

### 3.2 Who records what
| Recording | Milestone | Who | How it reaches this repository |
|---|---|---|---|
| Excitation sessions (steps, chirps, sweeps, holds) | M2a | owner, at the bench, under a separate arm-motion approval | owner plays agent-written target files through LeRobot's own tools (Q2); LeRobot dataset → real-episode importer → `data/imports/` |
| Camera and object calibration captures | M2a | owner | same importer; `reference_only` streams |
| Teleop sessions declared as calibration | M2a | owner | same importer |
| Loopback recordings (non-held-out checkpoint, actions logged, outcome unread) | M2a | owner, under a separate arm-motion approval (Q7) | immutable arm-project export with `COMPLETE`, verified by `src/vishwaroop/importer.py` |
| Policy rollouts (V-dev, V-hold, V-sealed) | M2b | owner runs the arm project's checkpoints under the frozen physical protocol (`docs/EVALUATION_PROTOCOL.md §3`), under a separate approval | immutable arm-project export with `COMPLETE`, verified by `src/vishwaroop/importer.py` |
| Success labels (C-check whole episodes; V sets) | M2a, M2b | blinded reviewers per `docs/EVALUATION_PROTOCOL.md §4` | label files referencing episode hashes |

Agents write protocols, target files, manifests and analysis code; they never command the arm.

### 3.3 Declared and audited before data exists
Two split declarations, each frozen and its sha256 appended to the status ledger before the first session it governs is recorded:
- **M2a** (proposed file `evals/M2a-data-split.json`), before the first calibration session: session-id prefixes and declared use for C-fit, C-check and Disposable; the calibration-id scheme; the D and H training runs (by registry id), or, if the runs do not exist yet, the rule that assigns runs to D or H before any of their outputs or outcomes exist (for example by a hash of the run id). The D/H assignment is fixed here because M2a already treats H checkpoints differently (§2.3).
- **M2b** (proposed file `evals/M2b-data-split.json`), before the first policy rollout: session-id prefixes and declared use for V-dev, V-hold and V-sealed; the placement list for V trials; the order rule (randomised within pairs, blocked by session); the sample size from the precision plan; the episodes used for rubric double-labelling (ET-M2b-1), drawn from V-dev or Disposable, never from V-hold or V-sealed.

Each recorded session carries its set label in its collection manifest, written before recording. `ironclad-audit-splits` runs on every assembled set, plus the provenance check of §3.1.

## 4. Proposed exit tests (not frozen)

**These replace the texts in `config/phases.json` only after the owner approves, a design dry run on disposable sessions or fabricated data has checked that each statistic is computable and non-degenerate, and a freeze work order records the hash.** All thresholds are *proposed default*.

### 4.1 Where each earlier test went
| Earlier draft | Now | Why |
|---|---|---|
| ET-M2a-1 compatibility | ET-M2a-1, loopback on a C-check recording | input fidelity; no policy outcome |
| ET-M2a-2 fidelity (a, b, c) | ET-M2a-2; (b) on non-H checkpoints only | owner-provided recordings |
| ET-M2a-3 ranking and baselines | ET-M2b-2 (replaces its ranking clause) | needs new held-out physical policy trials |
| ET-M2a-4 false optimism and bias | ET-M2b-5 (new) | real-world false optimism, per the owner |
| ET-M2a-4 abstention, constructed cases | ET-M2a-3 | known answer by construction; no outcome data |
| ET-M2a-4 abstention, data-bound (no D family, outside V-dev range) | ET-M2b-5 | bounds fitted on V-dev |
| ET-M2a-5 judge independence | ET-M2a-4; matched policy cells reported in ET-M2b-5 | |
| ET-M2a-6 data separation | ET-M2a-5 and ET-M2b-6 | same rule, each milestone's own sets |

### 4.2 M2a: the simulator milestone
| Id | Statement | Evidence | Threshold (all *proposed default*) |
|---|---|---|---|
| ET-M2a-1 | Policy compatibility: for each supported checkpoint family the twin supplies every input the checkpoint expects (images at raw resolution and history, joint state, instruction, rate, chunk execution), shown by the spec comparison and the execution-config test for every family, and the loopback test once per architecture on a C-check loopback recording (§2.3). | compatibility log per checkpoint | 100% of checks pass for each family evaluated; any refusal blocks that family. |
| ET-M2a-2 | Twin fidelity on C-check sessions (held out by session from the fit): (a) open-loop joint replay over 2 s windows from the measured initial state; (b) paired-state observation test: the twin set to the measured joint state and object pose, its rendered inputs and the real inputs fed to each non-held-out checkpoint; (c) outcome agreement on open-loop replay of whole real C-check episodes, twin judge vs blinded real labels. | replay error tables; action-discrepancy table; paired outcome table | (a) per-joint median RMSE ≤ 1.5° and ≤ 50% of the uncalibrated nominal twin's; (b) median twin-vs-real action discrepancy ≤ 2 × the median discrepancy between two real frames of near-identical state from different sessions; (c) outcome agreement ≥ 80%. |
| ET-M2a-3 | Abstention on constructed out-of-range cases: the twin returns "insufficient evidence" on an incompatible checkpoint, an unknown camera calibration id, a placement outside the template, an unmeasured control latency, and a session whose start-of-session drift check exceeds the threshold fitted on C-fit (constructed by offsetting a C-check session's joint readings). | abstention test log | 100% abstention on the constructed cases. |
| ET-M2a-4 | The twin's success judge is a predicate on simulator state, separate from any training reward model and from the real rubric; twin-judge vs real-rubric disagreements on C-check episodes, and training-reward vs judge disagreements, are tracked (`docs/EVALUATION_PROTOCOL.md §7`). | code audit; disagreement ledger | no shared weights, labels or code between training reward, twin judge and real rubric; disagreement report produced. |
| ET-M2a-5 (new) | Data separation, M2a: the M2a split declaration was frozen before the first recording; the provenance check shows every M2a fitted artifact (twin parameters, rendering config, colour transform, camera calibration, drift threshold) was fitted only on sets declared "fit" for it (C-fit; Disposable for dry-run versions only); C-check was scored, never fitted, and only on hashed twin versions; no policy rollout and no H-family checkpoint output entered any M2a artifact. | split hash and status-ledger time order; `ironclad-audit-splits` output; provenance check output; C-check scoring log | pass/fail; any violation is a fail, not an exclusion. |

**Why abstention on constructed cases stays in M2a.** Each case has a known correct answer (abstain) by construction, so it tests the mechanism without any policy outcome and without touching a V set. Bounds that come from data (which architectures and which predicted-success range the success-calibration map supports) need V-dev outcomes, so they move to M2b.

**Why these numbers (to be revisited at the dry run, none frozen).** The fidelity bound 1.5° rests on the review's lead that STS3215 backlash is about 0.87° (unverified, §8) and is the most likely number to move at the dry run. Outcome agreement 80% is below the current ET-M2a-2's 85%, because open-loop replay of real grasps amplifies small contact errors (R2).

**What an M2a pass means.** On this bench and this task, the calibrated twin accepts the evaluated checkpoints' exact inputs, reproduces the arm's motion and the cameras' views on calibration sessions it was not fitted on, abstains on the constructed out-of-range cases, judges success independently, and was built from declared fit data only. It does **not** show that the twin ranks policies like the real arm, and it licenses no physical success claim; that claim waits for M2b (`AGENTS.md §13.6`, `docs/EVALUATION_PROTOCOL.md §8`).

### 4.3 M2b: real-arm validation (proposed additions and replacements)
`config/phases.json` already describes M2b as physical validation with ranking on held-out real checkpoint pairs, false optimism, selection regret, episodes saved and one sealed opening. The moved tests fit that deliverable. The table keeps the existing ids where the test stays and appends new ids; nothing here is frozen.

| Id | Relation to `config/phases.json` | Statement | Evidence | Threshold (all *proposed default*) |
|---|---|---|---|---|
| ET-M2b-1 | kept; adds where its episodes come from | Physical protocol frozen (objects, placement template, camera mounts and calibration ids, reset procedure, timeout, rubric, sensors, blinding); rubric double-labelled on about 20 mixed episodes from V-dev or Disposable. | protocol hash; agreement and confusion table | reviewer agreement ≥ 90% with adjudication rules recorded. |
| ET-M2b-2 | replaced: the ranking clause becomes the earlier ET-M2a-3; selection regret kept; false optimism moves to ET-M2b-5 | Ranking reliability and selection regret on V-hold, using the frozen M2a twin: set H, ≥ 8 runs, ≥ 2 architectures, one checkpoint per run, ≥ 30 real trials each on the 18 template placements with randomised within-pair order and paired analysis, twin trials on the same placements. Baselines: B0, random choice (expected pairwise accuracy 50%); B1, the selection rule available without an evaluator (the most-trained checkpoint, or lowest offline validation loss); B2, the uncalibrated nominal twin. An H run the twin abstains on counts as a wrong order in every pair it belongs to. | ranking table; Pearson, Spearman, MMRV; pairwise accuracy; paired bootstrap over runs and sessions; McNemar or exact paired test | Spearman ρ ≥ 0.7; Pearson r ≥ 0.7; MMRV ≤ 0.10; pairwise order correct on ≥ 80% of pairs with a predeclared visible real gap (≥ 20 points); twin beats B1 and B2 on pairwise accuracy with the 90% paired-bootstrap interval of the difference excluding 0; selection regret ≤ 5 points; sample size frozen from a precision plan. Otherwise reported as "not distinguishable from no evaluator", a fail. |
| ET-M2b-3 | kept unchanged | Physical episodes saved at the selection error validated in ET-M2b-2, and cost per evaluated checkpoint. | cost ledger lines; savings computation | reported with denominators; no threshold on the value itself. |
| ET-M2b-4 | kept unchanged | One sealed confirmation suite (V-sealed) opened once under logged owner authorization; result reported regardless of outcome. | `ledgers/sealed_access.jsonl` record; report section 7 | exactly one opening; frozen candidate hashes recorded before access. |
| ET-M2b-5 (new) | takes the false-optimism clause of the existing ET-M2b-2 and the earlier ET-M2a-4's bias and data-bound abstention | Real-world false optimism, bias and data-bound abstention on V-hold. The twin's success estimate goes through a success-calibration map fitted on V-dev only. False optimism = fraction of matched (policy, placement) cells where the twin predicts success and the real trial failed; bias = mean (twin − real) success over H. The twin abstains on an architecture with no D family and on estimates outside the range V-dev supports (bounds fitted on V-dev). Twin-judge vs real-rubric disagreements on matched cells are reported. | confusion table; bias with interval; abstention log with coverage and denominators; disagreement ledger | false optimism ≤ 10% (the existing M2b default; the earlier draft proposed 15% for the twin, Q9); bias ≤ +10 points; coverage reported. |
| ET-M2b-6 (new) | added | Data separation, M2b: the M2b split declaration was frozen before the first policy rollout; M2b used the M2a twin's frozen hashes unchanged; the provenance check shows the success-calibration map and abstention bounds were fitted on V-dev only; no V-hold, V-sealed or other H-family rollout entered any twin parameter, rendering choice, calibration map, threshold or abstention bound; V-hold outcomes were first read after the map and bounds were hashed; V-sealed was opened once. | split hash and status-ledger time order; `ironclad-audit-splits` output; provenance check output; `ledgers/sealed_access.jsonl` | pass/fail; any violation is a fail, not an exclusion. |

If the owner drops V-dev (Q8), ET-M2b-5 uses the twin's raw success estimate with no calibration map, the data-bound abstention clause is removed, and V-dev's row in §3.1 disappears; no other rule changes.

**Why these numbers (to be revisited at the dry run, none frozen).** Spearman 0.7 and 80% pairwise are carried from the current ET-M2a-3; selection regret 5 points and false optimism 10% from the current ET-M2b-2. MMRV ≤ 0.10 sits above SIMPLER's reported average of 0.056 for its visual-matching variant (cited, §8), because this twin is built by one person on a hobby arm. With 8 runs, ρ = 0.7 corresponds to a one-sided permutation p of 0.029 (arithmetic: exact enumeration of all 8! rankings, no data), so the interval will be wide; 8 is a floor, not a target (Q3). Real-trial cost: 8 runs × 30 trials = 240 V-hold trials, about 6 to 8 owner hours at 1.5 to 2 minutes per trial including reset (estimated), plus V-dev and V-sealed sessions.

**What an M2b pass means.** On this bench, this task, these placements and these policy families, the frozen M2a twin ranked held-out runs like the real arm, beat the no-evaluator baselines, chose a run within the regret bound, and was not over-optimistic beyond the bound, with every held-out outcome kept out of every fit. It is not physical success for any policy, and it licenses no counterfactual claim beyond its validated distribution (`AGENTS.md §13.6`, `docs/EVALUATION_PROTOCOL.md §8`).

## 5. The deferred image generator, and what stays from WO-017 and WO-018

**Gate to reopen a learned observation model** (all four, in order):
1. The twin's ranking test (proposed ET-M2b-2) has been scored once and missed its frozen threshold, or passed but the owner wants a claim it cannot support.
2. The failure analysis attributes the shortfall to the **observation** path, not dynamics: ET-M2a-2(b) fails or its residual tracks the ranking errors, while 2(a) and 2(c) pass. A dynamics shortfall is fixed in the twin, not with pixels.
3. Enough real data exists for a fine-tune, never a from-scratch model: the review's lead is at least about 1,000 real episodes, modelled on WorldEval's LoRA fine-tune of a pretrained video model on about 1,400 trajectories (unverified, §8).
4. A measured pilot gives the cost, and the owner approves the spending (`AGENTS.md §2.3`). The same ET-M2a and ET-M2b texts apply to it unchanged, so the generator and the twin are compared on one scale.

**What stays.**
- WO-017 (accepted) stays as recorded. Its measured numbers become planning inputs: CPU rendering at 412 frames per second at 512 × 512 while stepping, and 62.3 images per second tokenizer training on MPS (measured, `reports/WO-017-m2a-mac-pilot.md`). Its tokenizer code is not extended.
- WO-018 (in progress, no VM): its Mac frame bundle (3,720 frames, sha256 recorded in the status ledger) stays an immutable artifact but is not twin data. Per the owner's item 2 the pilot plan is being revised (SO-101 simulator throughput and VLA inference latency) and returns for a fresh approval; this draft only states what the twin would want measured there (§6.2).
- Kept for the twin: the `SimEnv` protocol, save/restore from the initial state, the replay machinery, the split audit, the importer, and the independent judge discipline.

## 6. Dependencies and work orders

### 6.1 Prerequisites
| Dependency | State today | Needed for |
|---|---|---|
| Real-episode importer (owner item 4, $0; LeRobot dataset → contract v1 with image streams and `reference_only` object pose) | WO-023, built on fixtures 2026-11-08 (`docs/SO101_EXPORT.md`); real data not run | every real recording (M2a, M2b) |
| Arm-project exports (checkpoints with config, preprocessor, normalisation stats, weights in `safetensors`, eval results, `COMPLETE`) | none exist | M2a: ET-M2a-1, -2(b); M2b: ET-M2b-2, -5 |
| WO-006 policy registry with `holdout` per run | created, not started | D/H split, fixed in the M2a declaration |
| Bench prerequisites: fixed cameras with locked exposure and white balance, fixed lighting, printed template with board, servo gains settled (P gain decided once, then a calibration id), session-start drift check, AprilTag or colour object pose from a top camera as `reference_only` | kit arrived 2026-11-08; not set up | every recording |
| Owner approval for arm motion: calibration and loopback recordings | not given | M2a: C-fit, C-check, Disposable |
| Owner approval for physical policy trials | not given | M2b: V-dev, V-hold, V-sealed |
| Compute | Mac CPU physics and CPU rendering (platform of record); MPS for ACT-class inference (expected, not run). π0.5-class inference likely needs a CUDA GPU (about 10 GB, a lead from the review; unverified). No rental approved. | M2a: ET-M2a-2(b) with π0.5; M2b: twin rollouts of π0.5 |

### 6.2 Compute, estimated
- **M2a.** System identification: thousands of short replay windows per optimiser run, CPU-bound, a few Mac hours per fit (estimated). The paired-state observation test renders single frames, not episodes, so its cost is small next to the fit (estimated). π0.5 inference for ET-M2a-2(b) needs the same GPU question as below.
- **M2b.** Twin rollouts for ET-M2b-2: 10 policies × 18 placements × 5 repeats ≈ 900 episodes; at about 600 control steps per 20 s episode at 30 Hz, two rendered cameras, and an assumed 10 to 30 s wall time per episode on the Mac for an ACT-class policy, about 2.5 to 7.5 Mac hours (estimated; the 10 to 30 s is an assumption, not a measurement). π0.5 rollouts are the open cost: at an assumed 0.1 to 0.3 s per inference on a rented card, 900 episodes need roughly 1 to 4 GPU hours plus setup (estimated, not run); this belongs in the revised WO-018 plan, not here.

### 6.3 Ordered work orders (proposed; sizes per `work_orders/README.md`)
| # | Work order | Size | Needs |
|---|---|---|---|
| 1 | ADR recording the M2a redesign and the M2a/M2b split; `docs/PHASES.md` and `config/phases.json` deliverable texts updated, ET texts marked "proposed, not frozen" | S | owner approval of this draft |
| 2 | Real-episode importer, WO-023 (built on fixtures) | M | none further |
| 3 | SO-101 twin scene: pinned asset, environment id, template scene, image streams on the `SimEnv` protocol, CPU-tier tests with a fake | M | 1 |
| 4 | Input-spec manifest and compatibility checker (spec comparison, loopback, execution config), tested on fabricated policy configs | S | 3; real exports and a loopback recording for the loopback test |
| 5 | Bench calibration protocol, excitation target files, collection manifests, the provenance check, and the M2a split declaration (frozen before any recording) | S | 1; owner bench setup |
| 6 | M2a design dry run on Disposable sessions: fit pipeline and every ET-M2a statistic computed end to end; thresholds proposed for freezing | S | 3, 5; a few owner-recorded Disposable sessions (arm motion approval) |
| 7 | Freeze ET-M2a (exit tests and protocol hashes in the status ledger) | S | 6; owner sees the final text |
| 8 | System identification on C-fit; ET-M2a-2(a) and (c) scored on C-check | M | 7; C recordings |
| 9 | Camera calibration and rendering match on C-fit; ET-M2a-2(b) scored on C-check | M | 7; C recordings, non-held-out exports |
| 10 | Twin evaluator runner: closed-loop rollouts, judge, abstention on constructed cases, drift alarm; resumable by episode (`AGENTS.md §13.9`) | M | 4, 8, 9 |
| 11 | M2a scoring: ET-M2a-1 to -5 scored; twin hashes frozen; independent review and recheck (`AGENTS.md §13.8`) | M | 10 |
| 12 | M2b protocol: physical protocol, precision plan, the M2b split declaration (V-dev declared fit for the map and bounds only; V-hold and V-sealed held-out); M2b design dry run on fabricated outcomes; freeze ET-M2b | S | 11; owner sees the final M2b text |
| 13 | Rubric double-labelling (ET-M2b-1) on V-dev or Disposable episodes; V-dev recorded; success-calibration map and abstention bounds fitted on V-dev and hashed | M | 12; physical-trial approval |
| 14 | Held-out validation: V-hold recorded and blind-labelled; ET-M2b-2, -3, -5, -6 scored once; independent review and recheck | M | 13; physical-trial approval; π0.5 compute if in H |
| 15 | Sealed opening, ET-M2b-4, under logged owner authorization | S | 14; owner authorization in `ledgers/approvals.jsonl` |

## 7. Risks and open questions

### 7.1 Risks
- **R1, few independent policies (M2b).** Eight held-out runs give a wide ρ interval, and the arm project may not produce eight runs with a real spread. Inducing spread with demo counts and training lengths is planned in the split declaration, not chosen after outcomes.
- **R2, contact physics (M2a).** The SO-101 gripper's small, compliant contacts may not replay in PhysX at the fidelity ET-M2a-2(c) asks. Open-loop replay of grasps amplifies small errors; the dry run may show 80% is out of reach for reasons unrelated to ranking.
- **R3, wrist camera (M2a).** If checkpoints consume a wrist view, background compositing does not apply and cables, gripper texture and close-range lighting are hard to match.
- **R4, drift (M2a, M2b).** Servo heat derating, backlash wear and gain changes move the real arm between sessions; a twin calibrated in one session can be stale in the next. The session-start drift check and calibration ids handle it, at the cost of re-fitting. A re-fit after M2a is frozen is a new twin version and must pass M2a again before M2b uses it.
- **R5, sim optimism (M2b).** Twin success above real is common (a lead of 9 to 31 points on an SO-101 Isaac Lab benchmark, unverified, §8); the V-dev-only calibration map and the bias bound address it. A small V-dev gives a weak map.
- **R6, setup sensitivity (M2b).** Real-to-sim correlation varies with setup (a lead that a SIMPLER replication found r ≈ 0.40; unverified, §8). One bench and one task may not reproduce published correlations.
- **R7, π0.5 compute (M2a, M2b).** Without an approved GPU, H may contain only ACT-class runs, which weakens the "≥ 2 architectures" requirement.
- **R8, owner time.** M2a: C-fit, C-check, loopback and Disposable sessions. M2b: about 240 V-hold trials plus V-dev and V-sealed, several bench days (estimated, §4.3).
- **R9, an M2a pass does not predict M2b.** Fidelity on calibration sessions does not guarantee policy ranking; a twin can pass M2a and fail ET-M2b-2. That is the reason the ranking claim lives in M2b.

### 7.2 Open questions for the owner
1. **Q1.** Which cameras, resolutions, rates and instruction strings will the arm project's ACT and π0.5 policies use? The rendering plan depends on whether a wrist camera is among them.
2. **Q2.** For calibration sessions, may agents write joint-target files that the owner plays through LeRobot's tools, with no connection from this repository to the arm?
3. **Q3.** How many held-out runs and real trials per run will the bench budget support in M2b (proposed floor 8 × 30)?
4. **Q4.** May teleop demonstration sessions (the policies' training data) double as C-fit data if declared before the fit?
5. **Q5.** Asset source: TheRobotStudio's official SO-101 URDF (proposed) or Squint's vendored ManiSkill3 copy?
6. **Q6.** Servo P gain: settle it (LeRobot's SO-101 setup uses 16 against a servo default of 32, per a third-party mirror of its docs; the review suggests 32) once, before any recording, since a change invalidates the calibration.
7. **Q7.** The loopback test (§2.3) needs a recording of a non-held-out checkpoint driving the arm, with its actions logged and its outcome unread. Does that count as an owner-provided input-fidelity recording for M2a, or should it come from the arm project's existing deployment logs?
8. **Q8.** Keep V-dev in M2b? It is needed only for the success-calibration map and data-bound abstention (ET-M2b-5). Without it, ET-M2b-5 scores the twin's raw estimate.
9. **Q9.** Real-world false optimism bound in ET-M2b-5: keep the existing M2b default of 10%, or use the 15% the earlier draft proposed for the twin?

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
