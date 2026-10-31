# SYNTHETIC_DATA_M3.md — generated demonstrations and matched-scene replay

Phase definition and exit tests: `docs/PHASES.md` (M3). Research framing: `PROGRAM.md §8.3`.

## 1. First experiment (sim-renderable variations)
Use variations whose assets and initial states are known: approved rigid objects (check licenses), textures, lighting, layouts, distractors. "New object" means absent from the training split, not a different view of a training object. Save **before generation**: initial robot state, object poses and physical properties, simulator and controller configuration, calibration, asset hashes, random seeds, and the initial render.

## 2. Two pipelines, never conflated
- **Pipeline A — action-conditioned rollout.** Known actions → predicted observations. Action labels already exist. Test: changing the commanded action produces the correct change in outcome.
- **Pipeline B — generated demonstration.** Task + initial image → generated demonstration → inverse-dynamics pseudo-actions (DreamGen-style). Test: recovered actions are physically feasible and reproduce the intended behaviour under replay.
A task-conditioned demonstration generator is not an action-controllable policy evaluator (that is M2).

## 3. Replay filter
1. Verify the generated scene/object identity stays consistent with the matched initial scene; reject geometry, object-count or task changes.
2. Restore **only the initial simulator state**; execute inferred actions with the target control semantics. Never force subsequent recorded or generated states (ManiSkill's state-forcing replay mode is not an executability test).
3. Check limits, contact/clearance constraints, temporal behaviour, task outcome and end-state task predicates. A generated video may not expose its exact 3D end state: use observable predicates or explicitly estimated states with uncertainty; never invent inaccessible ground truth or require pixel equality.
4. Matched replay success establishes **simulator executability only**, not physical correctness. Real-initial-frame generations without a qualified matched reconstruction stay `unverified`.

## 4. Filter ablation
Compare at matched budget: quality/success filtering alone (GR00T-Dreams-style), physics replay alone where applicable, and combined. Measure acceptance, false acceptance/rejection on audited data, downstream task success, coverage lost, and cost per accepted trajectory. No novelty or superiority is assumed; the replay check's value is what the ablation shows.

## 5. Downstream ablation (SFT route only)
Real-only SFT / real + ordinary augmentation / real + generated. Match real data, base checkpoint, optimizer budget and evaluation suite; report synthetic ratios and total compute; ≥ 3 independent runs per arm where resources permit. Generated demonstrations never enter the GRPO objective: GRPO samples come from the rollout policy snapshot; IDM-labelled data has no such provenance. Keep generation and filter thresholds away from sealed suites.
