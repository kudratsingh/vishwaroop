# EVALUATION_PROTOCOL.md — specification to freeze before training

Rules: `AGENTS.md §5–7`. Exit tests that cite this protocol: `docs/PHASES.md` (M0-5, M1, M2a, M2b). Freeze the project-specific numbers in `evals/<phase>-protocol.md` and `evals/<phase>-exit-tests.json`, hash them, and record `frozen` status events before the phase starts.

## 1. Partitions and grouping
- Partitions: `train`, `dev`, `sealed` (confirmation), `regression` (revealed).
- Freeze the shift axes before training: object identity, position range, lighting, distractors, instruction wording, camera/session, and **policy identity**.
- Group by session and by **policy training run/family**, never by adjacent checkpoint ids. Snapshots from one run are candidates, not independent held-out policies.
- Synthetic descendants inherit their source partition. Keep sibling sessions/assets/run families together where the holdout requires it. Record licenses and lineage (`contracts/v1/audit_splits.py` must pass on every assembled set).

## 2. Sealed suites and the opening budget
- At most **one owner-authorized opening** of a named sealed suite per milestone report. Freeze candidate hashes, analysis code hash, exclusions and thresholds *before* access; log the opening in `ledgers/sealed_access.jsonl` (`config/sealed-access.schema.json`).
- The budget limits peeking; it does not restore statistical independence. Once disclosed, the suite becomes `regression` for later changes informed by it; new confirmatory claims need a fresh disjoint suite.
- A rerun solely for a documented infrastructure defect is logged, with no model tuning in between.
- Sealed data lives outside agent reach (owner decision pending: `docs/CONTEXT_AND_DECISIONS.md §5`).

## 3. Real-arm protocol (M2b)
- Task: PickPlace first. Freeze object ids, printed placement coordinates, camera mounts and calibration ids, allowed gripper approach, reset procedure, episode timeout, success rubric.
- Record for every episode: video, pre/post state, instruction, policy/run hashes, pair id, order, interventions, sensor readings, and a reason for every invalid or missing trial.
- Matched placements; **randomize policy order within each pair**; block across sessions. Never erase intervention or failure cases; define their treatment in advance and report them separately.
- Start with visibly different candidates; close pairs only once the evaluator has demonstrated discrimination.

## 4. Independent physical outcome
- A load cell establishes persistent added mass; a break-beam establishes passage. Neither alone proves correct-object placement, stable containment, release, or sequence. Freeze an evidence table: correct object; bin boundary; released grasp; dwell time; no prohibited intervention; timeout.
- Combine sensing with **blinded video review** for what sensors cannot resolve. Reviewers are blinded to policy identity and reward output.
- Validate the sensor: baseline, drift, bounce, empty-bin resets, deliberate negatives, wrong-object cases. A $10 component is not a calibrated sensing system by itself.
- Double-label about 20 mixed, deliberately informative episodes as a rubric check (agreement, confusion table, disputes, adjudication rules). This is a check, not final proof of label reliability.
- Sensor/reference streams never enter policy inputs for experiments claiming independence (`role: reference_only`).

## 5. Statistical plan
- Report raw successes/attempts and **Wilson intervals** for every proportion.
- Paired binary outcomes: McNemar (exact variant when counts are small) with a paired effect-size interval. Account for session clusters (e.g., resample whole sessions). Many steps, adjacent checkpoints, or one reset batch are not independent subjects.
- Reference points: 12/20 → 60% with 95% interval ≈ 38.7–78.1%; 30/50 → 60% with ≈ 46.2–72.4% (single proportions, not differences).
- Freeze a precision/power plan from the detectable gap and expected discordant pairs. Predefine missing-trial handling, exclusions, stopping, multiplicity, and descriptive vs confirmatory analyses.

## 6. Evaluator metrics (release criteria, not correlation alone)
- **Ranking reliability** on unseen training runs across tasks, seeds and meaningful policy changes.
- **False optimism**: predicted success where the real robot fails, at the chosen threshold.
- **Selection regret**: real performance lost by taking the evaluator's pick instead of the best physically evaluated candidate.
- **Calibration** of predicted probabilities; **abstention** coverage vs error ("insufficient evidence" outside the validated range).
- **Episodes saved** at a validated selection error.
- Per-task and per-shift breakdowns; ties and ranking uncertainty reported.
- M1 real-log claims cover executed actions only. M2b validation licenses no universal counterfactual claims; each claim stays bounded to its intervention protocol and validated distribution.

## 7. Reward-hacking alarm
Track training-reward vs independent-outcome disagreements, especially reward-positive/final-negative. Report conditional false-positive rate, coverage, task mix and intervals. Rising disagreement stops promotion and triggers inspection; it may also reflect sensor or label drift. It is an alarm, not proof of misbehaviour.

## 8. What a pass does and does not mean
A pass on simulated exit tests is simulated evidence. A pass on real-arm exit tests is evidence for that arm, that task suite, those shift axes and that policy population. Nothing here transfers to another embodiment without its own protocol.
