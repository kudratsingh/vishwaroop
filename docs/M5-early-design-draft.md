# M5-early design draft: best-of-N action chunks with a real-state scorer on the SO-101

**Status:** draft for owner review, 2026-11-08. Nothing here is frozen, run, or authorized beyond design and offline preparation.
**Authority:** owner approval `approvals-20261108T132556755986Z-2add2fa0`, item 3 ("Approve design and offline preparation. Start with ACT as the baseline and π0.5 as the second candidate once compatible exports exist. Define how ACT gets distinct candidate chunks, since standard ACT inference is deterministic. Establish the real-state scorer's accuracy and latency before proposing a physical trial. Arm motion and deployment require separate approval.") and item 8 (sharpen the question around abstention, latency and gains versus fine-tuning at a matched real-trial budget; credit prior SO-101 best-of-N work). Not authorized: arm motion, deployment, a physical trial, any spending.
**Program link:** PROGRAM §8.2 (arm row), §8.3 step 1 → vishwaroop M5. **Builds on:** `docs/PHASES.md` (M1, M5), `config/phases.json`, `docs/EVALUATION_PROTOCOL.md`, `AGENTS.md §7.3–7.4, §13.1, §13.2, §13.4, §13.6`, the M1 reports (WO-004, WO-005, WO-012, WO-016).
**Leads, not evidence:** the program review `reports/REVIEW-2026-11-08-program-architecture-compute.md` (§0, §3, §7, §9 item 11) is untracked in the main checkout and was read, not copied. Its literature claims were re-checked below; two were corrected.

> Labels: **measured** = ran in this repo, evidence attached; **estimated** = arithmetic from stated assumptions; **mocked/fixture** = fabricated for tests; **not run** = not run. External numbers are the cited authors' measurements, not ours. Every threshold here is a *proposed default*, not frozen.

## 0. Two points to settle first

1. **Phase order.** `config/phases.json` makes M5 depend on M2b, and M2b has not started. M5-early decouples the verifier from the evaluator: it needs the real-state scorer validated offline, not a validated policy evaluator. Before any ET-M5 threshold is frozen, the owner should approve that change (ADR plus a `phases.json` edit, or an `M5-early` phase with its own exit tests). Until then this draft is design and offline preparation only.
2. **What offline evidence can and cannot show (`AGENTS.md §7.3, §13.6`).** Real logs validate executed chunks only. Offline work can establish the scorer's accuracy, calibration, abstention and latency on chunks the arm actually executed. It cannot show that the scorer ranks *alternative, unexecuted* candidates correctly on the real arm. That needs intervention evidence: simulator branches (sim only, already done in M1) or the paired physical trial in §4. Offline success is a necessary gate for proposing a trial, not a claim about best-of-N.

## 1. The sharpened question and what prior work already answered

### 1.1 What the field has already shown (verified 2026-11-08 from the papers' own pages)

| Work | What it showed | What it leaves open for us |
|---|---|---|
| **DREAM-Chunk** (Chen et al., arXiv 2606.18589, submitted 2026-06-17, https://arxiv.org/html/2606.18589) | Test-time selection among N sampled chunks with a latent world model, no policy fine-tuning, **on an SO-101** with a fine-tuned SmolVLA: N = 10, 20 rollouts per condition, 50 to 100 teleop demos per task; USB unplug/insert 75% → 95%, pick moving object 60% → 80%, pick-and-insert toy 35% → 45%. On a Franka with π0.5, remote inference scored below local (40/30/35% at N = 10/15/20 vs 65% local at N = 5), which the authors attribute to added delay. Its selection rule matches predicted against observed state (reactive chunk switching), not an outcome score. | "Does test-time chunk selection help an SO-101 policy" is answered yes in their setting. Not reported: calibrated abstention, false optimism, a comparison with fine-tuning at matched real budget, ACT, or a state-only scorer. |
| **VeriVLA** (Sun et al., arXiv 2610.21985, submitted 2026-10-15, https://arxiv.org/html/2610.21985) | Flow-matching VLAs (π0.5 on the real robot) sampled with a distinct noise seed per candidate; a two-sample trigger decides when to verify; a JEPA latent world model ranks K = 10 candidates. Real AgileX PiperX dual arm, three tasks: completion 50.8% → 65.5%. Added latency 326 ms (80 ms extra sampling + 246 ms verifier) on one RTX 4090; 96 ms untriggered, 422 ms triggered. | A gate that falls back to the first sample when no trigger fires, but no calibrated abstention or false-optimism rate; lab-grade dual arm, not a low-cost arm; no fine-tuning comparison. |
| **Best-of-N headroom study** (Gao et al., arXiv 2610.37196, submitted 2026-10-27, https://arxiv.org/html/2610.37196) | Simulation only (RoboCasa, LIBERO-Plus; four world action models; no real robot). Native policy samples: held-out decision-level headroom ≈ 0 (+0.003 [−0.024, 0.035] on TurnOnStove). Structured perturbations (end-effector offsets along robot axes, about 2, 5 and 10 cm; orientation and gripper unchanged): +0.158 [0.081, 0.247] at κ = 0.25. A gated selector that deviates only when failure is predicted: closed loop +4.7 [1.9, 7.6] points on training tasks, +7.2 [4.7, 9.8] on unseen tasks (76.9% → 81.6%; 62.6% → 69.8%). Value head ρ = 0.01 vs future-frame probe ρ = 0.19 (0.23 pooled). Held-out oracle stays flat as candidates grow. | Whether the native-vs-structured finding holds on real, backlash-limited hardware; time-shift and gripper-timing perturbations were not tested. |
| **ACT** (Zhao et al., arXiv 2304.13705, submitted 2023-04-23, https://arxiv.org/html/2304.13705) | CVAE-trained chunk policy; "At test time, we set z to be the mean of the prior distribution i.e. zero to deterministically decode." Removing the CVAE objective dropped human-data success from 35.3% to 2%. Temporal ensembling queries the policy every step and averages overlapping chunks with exponential weights, "only extra inference-time computation". | Nobody we found reports ACT best-of-N, or whether ACT's latent carries usable diversity at test time. |

Corrections to the review's leads: DREAM-Chunk's SO-101 policy is **SmolVLA**, not ACT, and the 15M figure is the paper's general statement about JEPA world models, not the size of the model used on hardware (unverified for the hardware runs). The headroom study's "+11 to +16" is a decision-level oracle bound, and its closed-loop gains (+4.7, +7.2) come from a gated selector in simulation.

### 1.2 Sharpened questions (proposed; replaces the PROGRAM §8.2 arm row by ADR after owner review)

- **Q1 (primary). Gain versus fine-tuning at a matched real-trial budget.** On one SO-101 pick-and-place task, spend a budget of B real episodes (proposed unit: executed real episodes plus their operator minutes) either (a) on training and calibrating a real-state scorer used for best-of-N with abstention, or (b) on fine-tuning the same policy with B more real episodes (SFT on demos or interventions; RL fine-tuning only if the arm project produces one). Which gives the larger paired real-success gain over the N = 1 policy?
- **Q2. Proposal distribution and N.** On real hardware, do native samples (ACT latent; π0.5 noise seeds) or structured perturbations create selectable headroom, and where between N ∈ {1, 4, 8} do gains stop?
- **Q3. Abstention and false optimism.** At the frozen threshold, how often does the scorer abstain (fall back to the policy's own chunk), how often is it falsely optimistic, and does abstention keep the system no worse than N = 1 on out-of-range states (a no-harm test)?
- **Q4. Latency.** Does the per-decision overhead at each N fit the control budget on the bench computer, and does the pause it adds change success on its own?

What stays ours: a sub-$500 arm with measured backlash, calibrated abstention and measured false optimism as release criteria (`docs/EVALUATION_PROTOCOL.md §6`), a state-based scorer validated on physics branches (M1), and the matched-budget comparison. Unverified lead from the review: MG-Select (arXiv 2510.05681) reports gains flat beyond N = 4; not checked here.

## 2. How ACT gets distinct candidate chunks

**Fact base (verified).** LeRobot's ACT sets the latent to zeros whenever it is not training ("When not using the VAE encoder, we set the latent to be all zeros", `modeling_act.py`, https://github.com/huggingface/lerobot/blob/main/src/lerobot/policies/act/modeling_act.py, read 2026-11-08). Defaults in `configuration_act.py` (same date): `chunk_size = 100`, `n_action_steps = 100`, `latent_dim = 32`, `kl_weight = 10.0`, `temporal_ensemble_coeff = None`; temporal ensembling requires `n_action_steps = 1`. So standard ACT is deterministic for a given observation, and two calls give identical chunks.

**Fixed rules for every option.**
- **N = 1 is the policy's own standard output:** z = 0, the exported config's `n_action_steps` and temporal-ensembling setting, no scorer. It is the baseline arm and is never itself perturbed.
- **Candidate 0 of every set is that same z = 0 chunk.** Abstention means executing candidate 0, so an abstaining selector reduces to N = 1.
- **Nested sets.** The N = 4 set is the first four of the N = 8 set, generated from a per-decision seed derived from (episode id, decision index), so arms are paired at the candidate level and reproducible.
- **Selection happens at chunk boundaries,** every `n_action_steps` steps. Temporal ensembling is not combined with best-of-N in M5-early (it would require scoring at every control step). If the exported policy was evaluated with temporal ensembling, N = 1 keeps it and the best-of-N arms state the difference; this is an owner decision (§6, O4).
- **Distinctness metric.** For candidates a⁽ⁱ⁾ over the scored prefix of H steps (6 joint targets each; gripper scaled to radians-equivalent by its range), d(i, j) = RMS over steps and arm joints of a⁽ⁱ⁾ − a⁽ʲ⁾, with the gripper reported separately. A set's distinctness is min over i ≠ j of d(i, j). *Proposed default:* a set counts as distinct if its minimum pairwise d ≥ 0.015 rad, about the STS3215 backlash the review cites (0.87°, an unverified lead) and to be replaced by the backlash we measure on our arm. Candidates closer than the arm's own backlash are not physically different. Report the full distribution, not only the pass rate.

| Option | Retraining? | Changes the policy's distribution? | How distinctness arises | How N ∈ {1, 4, 8} is formed | Cost and risk |
|---|---|---|---|---|---|
| **A. Sample the CVAE latent** z ~ N(0, τ²I), τ ∈ {0.5, 1.0} | No. An inference shim replaces the zeros with samples (our loader, built on the public `lerobot` package, never the arm project's code) | Within the learned prior at τ = 1 in principle; the deployed policy has only ever been validated at z = 0, and τ > 1 is off-distribution | Only as much as the decoder uses z. With `kl_weight = 10`, the decoder may largely ignore z (posterior collapse); this is a hypothesis to measure, not a known fact | z = 0 plus 3 or 7 samples, one batched forward pass | Cheapest (one batch of N). Risk: near-identical chunks. Measured offline on logged observations (§5, WO-C) before any trial |
| **B. Structured perturbations** of the z = 0 chunk: time shift (±k steps), end-effector target offsets (±1 and ±2 cm along table axes through SO-101 FK/IK), gripper timing (close/open ±k steps) | No | Yes, deliberately off-policy; offsets must stay within joint limits and the workspace | By construction; size is a parameter | z = 0 plus a fixed, pre-registered menu: N = 4 = {0, +x, −y, gripper −k}; N = 8 adds {−x, +y, shift +k, gripper +k} (illustrative; frozen later) | Cheap. The headroom study's sim evidence favours it. Risk: the scorer must be calibrated on perturbed chunks (WO-016's lesson: calibration without them abstained on 42 to 56% of perturbed chunks) |
| **C. Checkpoint or seed ensemble** | Yes: N independent training runs in the arm project | Each candidate is a different policy | Training variance | N runs, one candidate each | N× memory and forward cost; N = 8 needs 8 runs; confounds selection with ensembling and complicates the policy-family holdout. Not recommended |
| **D. Temporal-ensemble phase offsets** (chunks predicted from the last k observations) | No | Stale observations | Small; candidates are highly correlated | Current chunk plus the previous 3 or 7 still overlapping | Free if `n_action_steps = 1`; low diversity and older information. Diagnostic only |
| **E. Observation noise** (joint-state noise, image crop or colour jitter) | No | Yes, input-side | Uncontrolled | z = 0 on clean input plus N − 1 noisy inputs | N forward passes; diversity not tied to anything physical. Not recommended |

**Recommendation.** Two proposal sources, both anchored on candidate 0 = the deterministic z = 0 chunk:
1. **Structured perturbations (B) are the primary ACT condition.** They need no retraining, their size is controlled, and the only published head-to-head (simulation) found headroom there and none in native samples.
2. **Latent sampling (A) at τ = 1 is the native-sample condition, conditional on an offline gate:** if fewer than 80% of decision points on held-out logged observations reach the distinctness threshold (proposed default), ACT's native condition is dropped and reported as a finding (ACT's prior carries too little test-time diversity on this task), and the native-vs-structured comparison moves to π0.5.

**π0.5 (second candidate, once a compatible export exists).** π0.5 produces continuous actions with a flow-matching action expert, starting from Gaussian noise and running 10 denoising steps (verified, https://arxiv.org/html/2504.16054, read 2026-11-08). Native candidates are different noise seeds, as in VeriVLA. Its N = 1 baseline is one sample with a logged seed; candidate 0 is that sample. The same distinctness metric, nesting and perturbation menu apply. Inference memory ("about 10 GB") and GPU needs are review leads, unverified here; π0.5 on the Mac is expected to be infeasible for closed-loop timing (estimated), which makes a bench GPU or rented card a spending question.

## 3. The real-state scorer

### 3.1 What it carries over from M1, and what must change
M1's scorer (WO-005, WO-016) rolls a 3-member residual ensemble (`src/vishwaroop/models/compute_pilot.py`, `cube_study.py`) over a 13-value state, computes knock, drop and table margins (`src/vishwaroop/scoring/violations.py`), scales intervals by split-conformal calibration (`conformal_scale` in `m1_scoring.py`), and abstains above the 90th-percentile calibrated cube std (`score_branches.py`). The RSSM in `latent_predictor.py` is the alternative backbone. Changes for real state:
- **No grasp flag.** `object_grasped` is M1-only by owner decision (`docs/CONTEXT_AND_DECISIONS.md`); "held" must be inferred from gripper joint, tool-to-object distance and object height.
- **Pre-grasp knocks.** The review reports that the plain-A gate zeroes predicted displacement of an unheld object, which hides the most common violation (37 to 42 of 44 to 50). Treat as a lead to verify in code, then fix before training on real data.
- **SO-101 kinematics** replace `so100_kinematics`; the nominal model comes from measured servo lag on our arm.
- **Scored prefix** H = the executed `n_action_steps` (proposed: at most 30 steps), not ACT's full 100-step chunk; M1 validated horizons up to 10 steps at 20 Hz only.

### 3.2 Interface (proposed)
- **Inputs:** joint positions (6, rad) and their recent history; commanded joint targets; object pose from the top camera (AprilTag or colour, position in m plus yaw), declared `role: reference_only`, which means it never enters the VLA's inputs; target region from the printed placement template (constant per placement); the candidate chunk.
- **Outputs per candidate:** progress (predicted reduction in tool-to-object plus object-to-target distance over the prefix, from `task_cost`); constraint-violation margins (knock, drop, table, joint limit) with a violation probability; uncertainty (ensemble spread, conformally scaled); and a decision of **select**, or **abstain → candidate 0**, with a reason (out-of-range state, wide uncertainty, all candidates predicted to violate).
- **Independence (`AGENTS.md §13.2`).** The trial's final success assessment never uses the scorer's pose stream; it uses the frozen evidence table (load cell or break-beam plus blinded video, `docs/EVALUATION_PROTOCOL.md §4`).

### 3.3 Training data (estimated needs; all from imported real episodes)
Sources, via the real-episode importer and WO-006: owner teleop (successes and safe failures or interventions), the arm project's ACT evaluation rollouts, later π0.5 rollouts. Every source is real and executed; nothing imagined is relabelled.
- *Proposed default size:* at least 150 episodes over at least 5 sessions and at least 2 policy families, with at least 30 violating chunk windows in the test split (the M1 scorer needed a 10-violation minimum; 30 gives a usable AUROC interval). **Estimated:** at 30 Hz and about 20 s per episode, about 600 steps and about 20 non-overlapping 30-step windows per episode, about 3,000 windows in all.
- *Proposed split:* **train** = teleop plus ACT run-family A from sessions 1 to 3; **calibration** = session 4, all sources, perturbation-like variety included; **test** = sessions 5 and later, plus a held-out policy family (π0.5, or an independently trained ACT run, never an adjacent checkpoint). `audit_splits.py` must pass.
- **Labels:** violations computed from the reference pose stream with the M1 thresholds converted to the real bench (knock 10 mm, drop rules) only after the pose noise floor is measured. A double-labelled sample of about 20 episodes against blinded video checks the automatic labels (`docs/EVALUATION_PROTOCOL.md §4`).

### 3.4 Offline evaluation, frozen before any scoring (all proposed defaults)

| Gate | Metric | Proposed default | Source of the default |
|---|---|---|---|
| S0 pose floor | Static jitter of the top-camera object pose | std ≤ 2 mm and ≤ 1/5 of the knock threshold | new; a 10 mm knock is meaningless under centimetre noise |
| S1 prediction | Multi-step RMSE vs constant, linear and nominal baselines, horizons 1..H, held-out sessions | ≥ 20% below the best baseline at every horizon | mirrors ET-M1-1 |
| S2 violation | AUROC for a violation in the executed chunk, on chunks kept | ≥ 0.75, bootstrap over sessions | mirrors ET-M1-5 |
| S3 ranking on executed outcomes | Spearman(predicted progress, realized progress) over executed chunks; pairwise ordering accuracy for executed chunks from matched placements whose realized progress differs by more than the pose floor | ρ ≥ 0.5; ordering ≥ 75% | new; executed chunks only (§0.2) |
| S4 calibration | 90% interval coverage per stream and horizon; ECE of violation probability | coverage within ±10 points; ECE ≤ 0.10 | mirrors ET-M1-3 |
| S5 abstention | Coverage on the test split; abstention on deliberately out-of-range inputs (held-out family, pose dropout, unseen object position) | abstain ≤ 20% in range; abstention rate higher out of range than in range, with an interval | M1 cap; ET-M2a-4 shape |
| S6 false optimism | Fraction of actually violating executed chunks that the scorer kept and rated safe at the frozen threshold; plus, episode level, failed episodes rated as progressing at every decision | ≤ 10% | ET-M2a-4 proposed default |
| S7 latency | Wall time for candidate generation + scoring + selection, per candidate and per N ∈ {1, 4, 8}, p50/p95/max over ≥ 1,000 decisions, on the Mac (CPU and MPS) and on the bench computer | p95 at N = 8 ≤ min(100 ms, ¼ of the executed-prefix duration) on the bench computer | new; frozen once the export states the control rate |

**Latency anchors already in this repo (measured, M1, Mac M3 Pro, simulated state):** a CEM decision with 3 members, 256 samples, horizon 20, 5 iterations took 158 ms on MPS and 169 ms on CPU, and 87 / 67 ms at 128 samples and 3 iterations (`reports/WO-012-m1-compute-split.md`); the M1 planners took 103 ms (learned) and 90 ms (nominal) median per control step under contention, against a 50 ms period (`reports/WO-005-m1-planner-and-chunk-scorer.md`); scoring 764 chunks offline took about 5 s wall time including loading (`reports/WO-016-m1-et5-retest.md`), which is not a per-decision latency. Per-candidate scorer latency for control has **not been measured**. **Estimated:** one batched rollout of 8 candidates should cost about one CEM iteration's dispatch overhead, roughly 30 ms on this Mac (158 ms / 5 iterations), before the review's suggested fixes; ACT's batched forward for N candidates is not run. Report both the median and the induced pause (Q4).

A failed gate is reported as a negative result; thresholds are not moved after seeing scores.

## 4. What a physical-trial proposal would contain later (not planned for execution)

A separate document, written only after §3.4 passes, sent to the owner, frozen before any episode:
- **Arms (proposed):** ACT N = 1 (standard output); ACT N = 4 and N = 8 with the recommended source; at N = 8, native vs structured if both pass the distinctness gate; optionally a latency-matched N = 1 (the same pause, no selection) to isolate Q4. π0.5 arms only once its export and inference hardware exist.
- **Design:** matched placements from the printed template with image-overlay checks; randomized arm order within each placement block; blocks spread across sessions; at least 30 episodes per arm, the final count from a frozen power plan on expected discordant pairs (`docs/EVALUATION_PROTOCOL.md §5`). **Estimated:** 4 arms × 30 = 120 episodes, about 4 to 6 hours of arm time at 2 to 3 minutes per episode with reset.
- **Outcomes:** independent success assessment per the frozen evidence table and blinded video; Wilson intervals; McNemar with paired effect intervals; session-clustered resampling.
- **Always reported:** abstention rate per arm and per decision; false optimism (decisions where the selected chunk was predicted safe and the episode failed at that step); per-decision latency and pause; compute per episode; interventions and invalid trials with reasons. Selection regret needs every candidate executed from the same state, which is a separate, smaller sub-study if wanted.
- **Matched-budget comparator (Q1):** the arm project fine-tunes the same policy on B extra real episodes, with B equal to the real episodes the verifier route consumed for scorer training and calibration.
- **Separate owner approvals it needs (`AGENTS.md §2.3`):** hardware motion (every session); deployment of a changed decision path that acts on the arm (the selector), including where the runtime lives, since editing the arm project is itself a §2.3 item; the frozen protocol and exit tests; any spending (π0.5 inference GPU, rented or bought); the phase-order change in §0.1; a sealed-suite opening if one is used.

## 5. Offline preparation work orders (ordered; $0; `AGENTS.md §2.1`)

| # | Work order (proposed) | Size | Depends on | Runs on fixtures now? |
|---|---|---|---|---|
| WO-A | **Real-episode importer**, WO-023 (built on fixtures 2026-11-08, PR #59; real data not run): LeRobot dataset → contract v1 with joints, images, object pose `reference_only`, `embodiment_id: so101_real` | done on fixtures | — | yes, on fabricated datasets |
| WO-B | **Candidate generator library:** perturbation menu (time shift, EE offsets via SO-101 FK/IK, gripper timing), joint-limit clipping, nesting and seeding, distinctness metric; an abstract hook for latent or noise-seed sampling | S | SO-101 kinematics from the official URDF (licence checked) | yes: fabricated chunks; mocked/fixture |
| WO-C | **ACT export loader and latent-diversity measurement:** load an immutable, hash-verified ACT export through public `lerobot`, replay logged observations (no arm), generate z ~ N(0, τ²I) candidates, report distinctness against the gate in §2 | M | WO-006 import of an arm-project ACT export; real episodes from WO-A | loader on a randomly initialised ACT (fixture); the measurement waits for the export |
| WO-D | **Real-state scorer port:** SO-101 state layout without grasp flag, inferred held state, knock-gate fix, real violation definitions, nominal from measured servo lag, training and conformal calibration scripts | M | WO-A; bench prerequisites (top camera, tags, servo-lag measurement) | yes: fabricated episodes |
| WO-E | **Offline evaluation protocol and harness:** §3.4 metrics coded and tested on fabricated numbers; protocol drafted for the owner to freeze before any real scoring; one independent review plus one recheck (`AGENTS.md §13.8`) | M | WO-D | yes |
| WO-F | **Latency harness:** per candidate and per N, Mac CPU/MPS now; bench computer when the owner names it and runs it there with no actuator connection | S | WO-B, WO-D (WO-C for ACT's forward) | yes: random weights, fabricated states |
| WO-G | **π0.5 candidates and latency** once a compatible export exists | S–M | π0.5 export; inference hardware (spending approval if rented) | interface only |
| WO-H | **Score once and report** (S0 to S7) on real data, then draft the physical-trial proposal (§4) | S | WO-C to WO-F; frozen protocol; ≥ 150 imported episodes | no |

Bench prerequisites the owner owns (review leads): top camera with locked exposure, fixed lighting, printed placement template, AprilTags, servo P = 32, a session-start calibration check, a backlash measurement for the distinctness threshold.

## 6. Risks and open questions for the owner

**Risks**
- **R1 ACT's latent may be collapsed** (`kl_weight = 10`), making native ACT candidates near-identical. Mitigated by the offline gate in §2; a negative is a result.
- **R2 Pose noise and occlusion.** A single top camera loses the object under the gripper, exactly when knocks and drops happen (per the review, ET-M3-1 failed four times because the arm occludes a fixed camera). S0 must pass; abstaining on missing pose must count against coverage.
- **R3 Offline accuracy does not license counterfactual ranking** (§0.2). The trial remains the only real test of selection.
- **R4 Distribution shift to perturbed candidates.** Executed logs contain few perturbed chunks; calibration may be over-optimistic on them (WO-005's abstention failure). Teleop safe failures and multiple policy families are the partial mitigation.
- **R5 Latency changes behaviour.** DREAM-Chunk's remote runs lost their gains to delay; a pause at chunk boundaries on a backlash-limited arm may itself change outcomes. Hence the latency-matched control.
- **R6 Data volume.** 150 episodes over 5 sessions is weeks of bench time (estimated) and depends on the arm project exporting.
- **R7 Small effects.** With 30 episodes per arm, only large paired differences are detectable; a null result must be reported as such.

**Open questions**
- **O1** Approve decoupling M5-early from M2b (ADR, `config/phases.json`)?
- **O2** The fine-tuning comparator: SFT on B extra real episodes in the arm project, or wait for an RL fine-tune? Who counts B, and in what unit?
- **O3** Where does the selection runtime live when a trial is approved: inside the arm project (a §2.3 modification) or a vishwaroop runner that commands the arm (a new hardware-motion boundary)?
- **O4** If the exported ACT uses temporal ensembling, should N = 1 keep it (faithful baseline) or match the best-of-N arms' chunk-boundary execution (cleaner comparison)? Recommendation: keep it, and add the matched variant only if arm time allows.
- **O5** Which bench computer runs the latency harness, and may an agent run software on it with no actuator connected?
- **O6** π0.5 inference hardware: rented card within a future approved envelope, or wait for the workstation decision?
- **O7** Confirm the distinctness threshold source: our measured backlash rather than the literature lead.
