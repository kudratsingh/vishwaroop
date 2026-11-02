# WO-005 | M1 planner (CEM MPC) and action-chunk scorer with simulator-branch validation
**Phase:** M1
**Exit tests advanced:** ET-M1-2, ET-M1-4, ET-M1-5
**Size:** L
**Prerequisites:** WO-004 accepted; frozen task suite and baselines from `evals/M0-protocol.md`; WO-012's compute split accepted.
**Authorization:** AGENTS §2.1 only: planner runs and simulator branches run on the owner's M3 Pro on CPU physics. Any paid GPU time would need §2.3 approval and a new estimate from a measured need.
**Files:** `src/vishwaroop/planning/`, `src/vishwaroop/scoring/`, `src/vishwaroop/sim/branches.py`, `src/vishwaroop/models/`, `evals/M1-*`, `artifacts/manifests/`, `tests/`, `work_orders/`, `START_HERE.md`, `reports/WO-005-m1-planner-and-chunk-scorer.md`, `reports/WO-004-m1-predictors-and-calibration.md` (errata only), ignored `runs/` and `data/derived/`.

## Objective
Build the sampling MPC planner over the learned and nominal models, the simulator-branch protocol (restore an initial state, execute ≥ 2 alternative action chunks through physics), and the action-chunk scorer with abstention; compare planners on the frozen suite with matched interaction budgets; validate the scorer against executed branches. Make no full-episode VLA claim.

## Scope
`branches.py` (controlled counterfactual evidence in sim); CEM planner with bounded actions, known costs, uncertainty penalty, admissibility checks; nominal-model MPC baseline; scorer heads (progress, clearance, constraint violation, uncertainty) with an abstention rule; evaluation tables with Wilson intervals; latency and compute per decision; report.

When this work order is expanded, its plan includes an estimate of M2a's observation model: which parts need a GPU, for how many hours, and the measurement that would confirm it. M2a's observation model is the first work that may need one. The estimate rents nothing (owner instruction, 2026-11-01).

ET-M1-4's planner runs are over 30 minutes, so they must resume by episode (`AGENTS.md §13.9`).

## Out of scope
Closed-loop VLA evaluation (M2a), synthetic data (M3), real arm, drone logs.

## Plan (expanded 2026-11-02; owner: "expand WO-005's plan, including the M2a GPU estimate, and proceed")
Every rule below is frozen in `evals/M1-planner-scorer.json` before any result it governs.

### Stage 0: the owner's two carry-ins from WO-004 (done)
- **Free cube.** Measured on train data, then dev for information, then fresh data.
  - The owner adopted plain A (`carry-contact-beta-fall-still-reach`).
  - The dev-informed refinement failed its frozen rule on fresh data (`evals/M1-refinement-accept.json`), so plain A stands.
  - The strict stays-put miss is a known gap, in millimetres in the report.
- **Calibration.** Coverage with scales fitted on one half of dev and measured on the other is reported beside ET-M1-3's recorded result.

### Stage 1: calibration split, branches, ET-M1-2 and ET-M1-5
1. **Collect the calibration split.** `evals/M1-calibration-plan.json`, 120 dev-family episodes from block 9. It is used only to fit interval scales.
2. **Build `sim/branches.py`.** For each frozen state, reset to the episode's seed, execute the recorded prefix, then execute one chunk. This repeats for every chunk, with no restore and no forcing. It records each chunk's simulated trajectory, cost and violations, resumable by state.
3. **Score the branches.** Rank the chunks under the learned and nominal models (ET-M1-2), and run the model-based scorer with abstention (ET-M1-5). Each is scored once.

### Stage 2: planner and ET-M1-4
4. **Build `planning/`.** CEM over joint targets, clipped to the action limits. It uses a staged task cost from known geometry (approach, descend, close, lift, carry, lower, open), an uncertainty penalty from the calibrated ensemble spread, and the nominal model as an alternative.
5. **Tune.** On train seeds 5000 to 5049 only, in at most about 2 hours. Then freeze every planner setting in `evals/M1-planner-settings.json`.
6. **Run the suite.** Seeds 9100 to 9299 for the learned planner, the nominal planner and the scripted controller, resumable by episode. About 2.5 hours of Mac time (**estimated**: decisions at horizon 10 near 80 ms, from WO-012's 158 ms at horizon 20, times 200 steps, 200 episodes and 2 planners), plus a 50-episode run without the uncertainty penalty.
7. **Report,** then a full independent review (`AGENTS.md §13.8`), because this work order closes exit tests.

### M2a's observation model: GPU estimate (**estimated**; nothing rented)
- **What it must do.** Supply every input an evaluated arm checkpoint expects: camera images at the checkpoint's resolution and history, proprioception, instruction and timing, conditioned on actions (`docs/PHASES.md`, M2a). The checkpoint's exact input spec is unknown until arm exports exist (WO-006), so these numbers carry that uncertainty.
- **Likely parts.** An image tokenizer (encoder and decoder) and an action-conditioned dynamics model in its latent space. A diffusion decoder would cost more.
- **Mac, from measured numbers.** WO-012 measured a ViT-S/14-shaped encoder at 238 images per second on MPS, forward only with random weights. Training costs about 3 times a forward pass, so call it 80 images per second for the encoder alone. Assume 2,000 episodes of 150 steps with 2 cameras, which is 600,000 images, and 20 epochs. That is about 42 hours for the encoder alone. A decoder and dynamics model add several times that, so one training run lands in the hundreds of Mac hours. **The Mac is not practical here, so M2a's observation model likely needs a GPU.**
- **GPU.** On one H100-class GPU, assumed 20 to 50 times the Mac's training throughput (not measured), one full run is about 10 to 80 GPU-hours. At about $2 to $3 per hour that is about $20 to $250 per run, before failed runs.
- **The measurement that would confirm it, in two steps.**
  1. A 30-minute Mac pilot training a small tokenizer on rendered sim frames at the target resolution, to measure images per second and the early loss curve.
  2. Only if that projects past 24 hours a run, a 2-hour GPU pilot of the same code. It needs the owner's §2.3 approval, a cost entry, and an estimate written before renting.

## Verification
`make check`. Then, in order:
```bash
python -m vishwaroop.sim.collect --config evals/M1-calibration-plan.json --partition dev --tolerance-file evals/M0-exit-tests.json --out data/derived/m1-calibration/<commit>
python -m vishwaroop.data.registry build --root data/derived/m1-calibration/<commit> --plan evals/M1-calibration-plan.json --out artifacts/manifests/m1-calibration-v1.json
python -m vishwaroop.sim.branches          # ET-M1-2 and ET-M1-5 data, resumable by state
python -m vishwaroop.scoring.score_branches  # ET-M1-2 and ET-M1-5 verdicts, once
python -m vishwaroop.planning.suite --planner <learned|nominal|scripted>  # ET-M1-4, resumable by episode
```
Expected: each verdict computed under the frozen rules, pass or fail, and a negative result reported as one. Negative tests cover the following: a forced or restored state, a chunk outside the action limits, a second scoring, a changed frozen file, a resumed suite equal to an unbroken one, and a violation detector on fabricated trajectories.

## Exit criteria
Done when the report gives ET-M1-2, ET-M1-4 and ET-M1-5 as passed, failed or not decidable under the frozen rules, with the Stage 0 results and the M2a estimate. With WO-004's results, that settles phase M1's exit tests.

## Stop conditions
Thresholds not frozen; "constraint violation" (ET-M1-5) not defined in a frozen file before any scorer result, since no frozen file defines it today; planner exploiting predictor errors without the uncertainty penalty being reported; any attempt to present chunk scores as policy success.

## Report
`reports/WO-005-m1-planner-and-chunk-scorer.md`
