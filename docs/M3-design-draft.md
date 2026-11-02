# M3 design draft: synthetic-data engine (SFT route)

**Status:** draft for the owner, 2026-11-02, not frozen and not started. It drafts the design only and runs nothing; the owner's "no M3 work now" from WO-004 stays in force for M3 work itself.

**Status:** draft for the owner. Nothing has been frozen, generated or run. **Date:** 2026-11-02. **Program link:** PROGRAM §5.2, §8.3 step 3 → vishwaroop M3.
**Builds on:** `docs/PHASES.md` (M3), `config/phases.json`, `docs/SYNTHETIC_DATA_M3.md`, `AGENTS.md §13.5`, `docs/DATA_AND_SNAPSHOTS.md §6`.

> Labels: **measured** means it ran in this repo and has evidence. **Estimated** means arithmetic from stated assumptions. **Not run** means not run. Nothing in this draft is a result.

## 0. One point to settle first

In simulation the physics engine is already a perfect world model (PROGRAM §5.4). A sim-only M3 therefore cannot show that a generator beats the simulator. What it can show is narrower:

1. **The machinery and the filter work.** Sim gives ground truth, so the filter's false-acceptance rate can be measured exactly. The real arm cannot give that.
2. **How much of a known gap generated data closes,** measured against physics-made data of the same kind. Physics-made data is the oracle arm.

Each M3 claim stays sim-only until real teleop data exists. PROGRAM §6 rule 2 says M3 needs teleop data. PHASES allows a sim-only prototype if it makes no claim of real-arm improvement.

## 1. What M3 must deliver, and how each exit test is measured

The deliverable comes from PHASES:
- Pipeline A: known actions → predicted observations.
- Pipeline B: task + initial image → generated demo → IDM pseudo-actions.
- Both run on matched, reconstructible sim scenes.
- An executability filter that replays from the initial state only.
- A matched-budget downstream ablation.
- Cost per accepted trajectory.

| Exit test | Threshold today | Proposed measurement | To freeze before work |
|---|---|---|---|
| ET-M3-1 scene consistency | 100% of injected mismatches rejected (fixed) | Six mismatch types: object removed, object duplicated, cube resized, goal or task changed, asset hash broken, initial render not matching the saved state. At least 10 of each, injected into manifests and into generated frames. The pass rule also reports false rejection on at least 60 unmodified controls. | Count per type; a false-rejection cap on controls (proposed ≤ 5%) |
| ET-M3-2 replay executability | *proposed default:* false acceptance ≤ 10% on ≥ 100 audited | A stratified random audit sample with a frozen seed, drawn before any filter verdict is seen. It needs ≥ 100 accepted and ≥ 50 rejected candidates. The auditor is the stdlib-only rubric `src/vishwaroop/outcome/pickplace.py` on full sim state, plus a check that the replayed behaviour is the one generated. False acceptance = accepted but the audit fails, divided by all accepted. | Point estimate or Wilson upper bound. Recommendation: decide on the point estimate and report the Wilson interval, as ET-M1-4 did. Also freeze the trajectory-agreement tolerance (§2 step 6). |
| ET-M3-3 downstream ablation | *proposed default:* ≥ 3 seeds per arm; benefit only above a frozen margin | Arms: sim-"real" only, + ordinary augmentation, + generated. Same base, same optimizer steps, same evaluation: 200 episodes per run on fresh M3 dev seeds, with the same seeds across arms. Paired analysis. | **Margin.** Proposed: generated beats augmentation by ≥ 5 points, pooled over seeds, and the paired 95% interval's lower bound is above 0. Also: the downstream policy (decision D1) and the demo count. |
| ET-M3-4 cost per accepted trajectory | reported | (GPU $ + Mac hours + filter and training share) ÷ accepted, with rejected candidates counted. Success demos and failure trajectories are reported separately. | nothing |
| ET-M3-5 SFT-only route | code-path audit clean | A test that any RL objective module refuses records that are `imagined` or carry `generator_model_artifact`. vishwaroop has no GRPO, and the arm project's GRPO is out of reach (`AGENTS.md §1.1`), so exports also carry an "SFT only" declaration (see §4). | nothing |

Also proposed: **ET-M3-6, held-out failure family** (§3). It is new, so adding it to `config/phases.json` and `docs/PHASES.md` is an owner decision (D2).

## 2. Generation pipeline

Code lives in `src/vishwaroop/synth/`, which `docs/ARCHITECTURE.md` lists as not implemented. M0 code stays as it is: `sim/record.py` hard-codes blocks 0–9, and `partition_for_seed` raises outside them.

**Step 1. Scene snapshot, saved before generation (ET-M3-1).** For each M3 seed, `ManiSkillPickCube.reset` → `save_state` → restore. This is the ADR-0006 path, so a recording follows the same path as its replays. Then write a pre-generation manifest with:
- the initial state JSON
- `asset_manifest()` sha256s
- `configuration()` and `stack_identity()`
- the seed
- the camera pose
- the initial render, with its hash

Recording a nominal scripted demo on the same scene gives the `physics_sim` parent episode the contract requires (`provenance.parent_episode_ids`). The same demo is the sim-"real" demo.

**Step 2. Reproducibility gate.** Before any generation, replay the parent 3 times under the frozen 0.001 tolerance (`sim/replay.py`). Drop scenes that do not reproduce, and list them. WO-016 found 7 of 198 states outside tolerance (**measured**). Without this gate, those scenes would show up later as false rejections.

**Step 3. Generate.**
- **Pipeline A.** The actions come from the perturbation operators (§3) or the scripted plan. The observations come from the action-conditioned observation model, which is M2a's (see §5). The output is `imagined`, with the actions known.
- **Pipeline B.** Task + initial render go to the video generator, which produces frames. The IDM reads consecutive frames and outputs pseudo-actions. The output is `imagined`, with the actions inferred.
- The two pipelines never share a manifest, a family id or a report table (`SYNTHETIC_DATA_M3.md §2`).

**Step 4. Scene-consistency check.** This runs on every generated frame against the snapshot: object count, cube size and colour (known in sim), goal and task, and first frame against the saved render. It is deterministic. Any failure rejects the candidate before replay.

**Step 5. Action checks.** Pseudo-actions must be finite, inside `action_spec` limits and under a frozen per-step rate limit.

**Step 6. Replay from the initial state only.** Restore the snapshot once, execute the actions through physics, and never force a later state. The replay is a new `physics_sim` episode, linked to its imagined parent. Then:
1. Run the independent rubric.
2. Check constraints: knock, drop, table contact (`scoring/violations.py`).
3. Compare the replayed trajectory with the generated one, using observable predicates: cube xy and gripper open or closed, both estimated from the frames. The agreement tolerance is set by a pilot on seeds held apart from the audit and frozen before scoring. No pixel equality.
4. Repeat the replay 3 times for determinism.

**What counts as an accepted trajectory.** A candidate is accepted when every check passes:
- steps 1–5 pass;
- the replay is deterministic within 0.001;
- the replay's rubric label equals the generation intent: `success` for a demo, or the operator's intended failure label for a failure trajectory;
- there is no constraint violation unless the operator intends one;
- generated and replayed trajectories agree within the frozen tolerance.

Each acceptance appends a `replay_checked` line to the contract's validation ledger for the imagined episode. The manifest is never edited.

Acceptance means **simulator executability only** (`AGENTS.md §13.1`). The primary SFT input is the imagined observations with their actions. "Physics-replayed observations with generator-proposed actions" is a separate, labelled variant, never mixed into the primary.

**Cost accounting.** Every candidate, rejected ones included, gets a line in the run directory: generation seconds, filter seconds, and the stage that rejected it. `ledgers/costs.jsonl` holds the per-run totals.

## 3. Failure-data emphasis

**What M1 showed (measured, train data, family holdouts):**
- **`missed-grasp` held out.** Worst reductions were −237% on the cube and −63% on the joints against the best baseline. Most of the error was the residual moving a resting cube (WO-004 Stage A; WO-014).
- **`early-release` held out.** The cube missed 20% at horizons 2–4. The fall speeds it needs were never seen in training: up to 29.9 mm per step, against ≤ 12.9 mm in any other family (WO-014).
- **Knocks.** Knocks were 37–42 of the violations (WO-005, WO-016). The phase in which the cube is pushed before a grasp was worse than baseline (WO-004).
- **Gripper inversion.** This is the only place the learned model beat the nominal: AUROC 0.944 against 0.405 (WO-016).

**A caveat to measure first.** WO-005 replaced the model with "plain A", in which a free cube stays put. That change targets exactly the resting-cube error behind the `missed-grasp` number. The `missed-grasp` holdout under plain A is **not run**. So the first step of the held-out test re-measures it on train data. The target family is then chosen by a frozen rule: whichever of `missed-grasp` and `early-release` has the lower worst reduction under plain A. If both clear 20%, M1's motivation for M3 is weaker than it looked, and that becomes the reported result.

**Operators.** Each is an action edit applied to a nominal plan on an M3 scene:

| Operator | Edit | M1 link |
|---|---|---|
| `m3-op-lateral-miss` | grasp offset along **y**, 0.02–0.05 m | missed grasp |
| `m3-op-close-high` | gripper closes 0.02–0.04 m above grasp height | missed grasp |
| `m3-op-open-in-transit` | gripper opens at a random step of carry or lower | early release, fast falls |
| `m3-op-push` | 10-step arm-offset chunk during approach, 0.03–0.12 rad | knocks |
| `m3-op-gripper-invert` | gripper command inverted for 5–15 steps at a random phase | inversion |

**Leak rules,** frozen before any operator data exists:
1. **Parameters stay disjoint from existing families and branch chunks.** No operator may reproduce the settings of any existing family (`sim/baseline.py` `VARIANTS`):
   - `missed-grasp` (−0.04, 0) x
   - `wrong-place` −0.03 x
   - `early-release` place height 0.05
   - noise 0.01 and 0.02
   - `dev-grasp-offset` −0.012 x
   - `dev-place-offset` −0.016 x

   Nor may an operator reproduce M1's branch chunks exactly: 0.05 and 0.15 rad, and the 10-step inversion. Hence the y-axis offsets and the different ranges.
2. **Generators and IDMs never train on the target family,** on any dev family, or on M3 dev or sealed frames.
3. **New identities.** Family ids are `m3-synth-<operator>` and run ids are new, in partition `train`. Synthetic descendants inherit their parent's partition, and `audit_splits.py` enforces that.
4. **The evaluation family gets a new id,** `m3-eval-<target>`, recorded fresh on M3 dev blocks. `m0-scripted-<target>` is excluded from every training set in the test. M0 puts each family wholly in one partition, so reusing the M0 id would fail the audit.
5. **M1's dev artifacts (blocks 8–9) become regression-only** for any model trained with M3 data.

**Held-out-family test (proposed ET-M3-6).**
- **Model:** plain A (`carry-contact-beta-fall-still-reach`), 30 epochs, seeds 0, 1 and 2, as in WO-004.
- **Base training set:** M0 train data minus the target family (230 episodes, as in WO-014).
- **Evaluation:** ≥ 60 fresh `m3-eval-<target>` episodes on block 16, same PlanSettings as the M0 family.

Arms, at a matched number of added windows:

| Arm | Added data |
|---|---|
| F0 | none |
| F1 | ordinary augmentation (state and action jitter of existing windows) |
| F2 | operator trajectories, observations from physics (**oracle**; Mac, $0) |
| F3 | operator trajectories, observations generated and filtered (pipeline A, or B through its replay variant) |
| F* | collected target-family data (the WO-004 setting, as reference) |

**Decision rule, proposed for freezing.** Arm Fk "helps" when both conditions hold:
- On the evaluation family, its RMSE is below F1's at every horizon from 1 to 10, on both streams and all three seeds.
- Its worst seed-holdout reduction falls by no more than 2 points from F0's. This is the no-harm check, the same form as WO-004's free-fall rule.

Also reported: the fraction of the gap closed, (F0 − Fk) ÷ (F0 − F*), per stream at horizon 10. M3's question is F3 against F2. F2 against F1 says whether targeted failure data helps at all. Every arm is a valid negative.

In this test, the failure trajectories feed the **predictor and scorer**, not the SFT policy. Success demos feed SFT (ET-M3-3). Training a policy on failures is out of scope.

## 4. Partitions, seed blocks, contract, ledgers

**Seed blocks.**
- Blocks 0–9 are assigned to M0/M1: 0–7 train, 8–9 dev (`evals/M0-protocol.md §3`).
- Blocks already used: 2, 4, 5 (tuning), 6 (pilot), 8 and 9, from `evals/*plan*.json` and WO-017. M0's sweeps and tuning also used blocks 0 and 1 (`reports/WO-001-m0-grounded-environment.md`), and WO-012's pilot used block 3 (`src/vishwaroop/models/compute_pilot.py`). Only block 7 is untouched.

Proposal: a new frozen `evals/M3-protocol.md` (`m3-protocol-1`), with `scene_group_id` `m3-seed-block-<n>`, blocks of 1,000 seeds:

| Blocks | Partition | Use |
|---|---|---|
| 10–15 | train | scene sources, generator, IDM and SFT training |
| 16–17 | dev | held-out-family evaluation (16) and the ET-M3-3 evaluation suite (17) |
| 18–19 | reserved, never simulated | a future sealed suite, once the owner decides where sealed data lives (CONTEXT §5 row 3; PROGRAM §12 row 9) |

M3 never uses blocks 0–9. The same frozen file also holds the M3 task suite and its sample sizes.

**Contract (`ironclad.contracts.v1`, unchanged).**

| Data | `environment_kind` | Provenance |
|---|---|---|
| physics demos and operator data | `physics_sim` | — |
| generated data | `imagined` | `parent_episode_ids` = the scene's parent demo; `generator_model_artifact` = the generator weights hash |
| replays | `physics_sim` | parent = the imagined episode |

Validation-ledger statuses are `generated`, then `replay_checked`. Two gaps exist:
- `policy.origin` has no "generated" value. Proposal: `none`, with `family_id` = the generator run, and a note.
- The schema has no "SFT only" field. Proposal: `purpose: "demonstration"` plus a manifest note, and an ADR.

Changing the contract is a §2.3 gate, so this draft avoids it unless the owner wants one (D7).

**Ledgers.**
- `licenses.jsonl`: every pretrained generator, IDM or dataset before use. The owner's exclusion of non-commercial and model-output-restricted data applies (`docs/DATA_POLICY.md §6`).
- `imports.jsonl`: only when arm teleop exports arrive.
- `costs.jsonl`: every GPU run, through the launcher.
- `runs.jsonl`: as usual.
- `approvals.jsonl`: any rental.

Episode bytes have a single copy on the Mac (`DATA_AND_SNAPSHOTS.md §7`), and M3 multiplies that volume.

## 5. Compute

| Work | Where | Rough size (**estimated** unless marked) |
|---|---|---|
| Snapshots, parent demos, operator episodes (~3,000) | Mac CPU | Recording ran at ~0.55 s per episode (**measured**, WO-005: 325 in ~3 min), so ~30 min |
| Initial and per-step renders, 512² | Mac | 412 fps (**measured**, WO-017); 200k frames ≈ 8 min plus encoding |
| Replay filter, 3 repeats per candidate | Mac CPU | ~2 s per candidate; 2,000 candidates ≈ 1–2 h |
| Held-out test: 5 arms × 3 seeds | Mac MPS | ~5–6 s per epoch (**measured**, WO-004) at 234 episodes; ≈ 2–4 h with the added data |
| In-repo state-based BC policy, 3 arms × 3 seeds, plus 1,800 evaluation episodes | Mac | hours, $0 |
| Pipeline A observation model | GPU | Is M2a's model. WO-017's estimate is 3–27 GPU-hours per run, with the speedup **not measured**; WO-018 will measure it. |
| Pipeline B: small latent video generator on the M2a tokenizer, plus an image IDM | GPU | assumed comparable, ~5–30 GPU-hours; inference ~0.5–2 h for 1,000 candidates (assumption) |
| Fine-tuning a large open video foundation model | GPU, ≥ 48–80 GB | tens to hundreds of GPU-hours. Not proposed now. |

**Total GPU for M3:** about 5–35 GPU-hours before failed runs (**estimated**). That is ~$5–$105 rented at an assumed $1–3 per hour, or ~$0 marginal on the workstation (electricity ~$50 per month at 6 h a day, PROGRAM §9).

M3's budget today is **$0**. The $50 approval covers WO-018 only. The owner has said later runs move to the workstation.

**Dependencies.**
- Pipeline A cannot start before M2a's observation model exists. Pipeline B can share M2a's tokenizer.
- Replay must run on the stack that recorded the scenes. The Mac is the platform of record. If generation runs on the Linux workstation, either ship the candidates back to the Mac for the filter, or re-qualify Linux first (M0 replay and negative tests, per the owner's 2026-11-01 instruction). Replay platforms are never mixed.
- `object_grasped` is `reference_only` and excluded from M2a onward. It may appear in the audit, but never in IDM, generator or policy inputs.

## 6. Risks, owner decisions, work orders

**Risks.**
- **Generators rarely invent modes they never saw,** so F3 may close little of the gap. That is a valid negative, and F2 bounds it.
- **Inexact restore (ADR-0006)** adds false rejections. Step 2's gate mitigates this.
- **Low IDM acceptance** would make cost per accepted trajectory high. The cost is reported either way.
- **Ceiling effects.** Scripted demos are not teleop, and BC on scripted demos may sit at ceiling. Choose the demo count from a pilot on block 15, frozen before the ablation, so that sim-"real"-only success lands at 30–70%.
- **M2a slipping** delays Pipeline A.
- **Dev reuse.** M1's dev blocks have been read many times, so M3 uses fresh blocks only.

**Owner decisions.**

| # | Decision | Recommended default |
|---|---|---|
| D1 | Downstream policy for ET-M3-3 | In-repo BC policy, sim-only, state-based first. The arm VLA needs exports and owner-run SFT. |
| D2 | Add ET-M3-6 as a frozen exit test, or keep it report-only | Add it |
| D3 | Pipeline B generator | Small in-repo latent video model. A foundation model is a future option. |
| D4 | GPU: wait for the workstation, or rent under a new approval | Wait. Mac work orders run first. |
| D5 | Blocks 10–19 as in §4; where sealed data lives | As proposed. Sealed stays deferred. |
| D6 | ET-M3-2 basis (point estimate or upper bound); ET-M3-3 margin | Point estimate with Wilson reported; ≥ 5 points with lower bound > 0 |
| D7 | Contract gaps (§4) | Notes plus an ADR, no contract change |
| D8 | Whether F2's physics-made operator data counts as M3 evidence | Report it as the oracle arm, labelled `physics_sim`, never as "generated" |

**Proposed work orders.** WO-019 is already drafted (untracked, M4), so these start at WO-020.

1. **WO-020 · M3 protocol and scene engine (M, Mac, $0).**
   - Freeze `evals/M3-protocol.md` and `evals/M3-exit-tests.json`.
   - Build `synth/` snapshots, the reproducibility gate, the consistency checker and the mismatch injector.
   - **Closes ET-M3-1.** It needs one review plus one recheck (`AGENTS.md §13.8`).
2. **WO-021 · Failure operators, replay filter, held-out-family test on physics data (M, Mac, $0).**
   - Re-measure the target family under plain A.
   - Run arms F0, F1, F2 and F*.
   - Build the filter and audit harness. Exercise them on deliberately corrupted physics trajectories, labelled as controlled inputs, not ET-M3-2 evidence.
3. **WO-022 · Generators, IDM, generation and audit (L, GPU, needs approval or the workstation, after M2a's model).**
   - Pipeline B, then Pipeline A.
   - Arm F3.
   - **Closes ET-M3-2 and ET-M3-4.**
4. **WO-023 · Downstream SFT ablation and route audit (L, mostly Mac).**
   - BC policy, 3 arms × 3 seeds.
   - **Closes ET-M3-3 and ET-M3-5.**
   - Phase report.

WO-020 and WO-021 can start now. WO-022 waits on M2a and on compute.
