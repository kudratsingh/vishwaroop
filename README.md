# Vishwaroop — World Model & Planner

A **world model and planner for robot learning**, built around action-conditioned dynamics, latent prediction, calibrated uncertainty and **cross-entropy method model-predictive control (CEM MPC)**. The project brings predictive simulation, action-chunk scoring, closed-loop VLA policy evaluation and physics-validated synthetic training data into one learning and planning architecture.

The SO-100 pick-and-place environment in **ManiSkill3** connects scripted and perturbed trajectories to learned residual ensembles, recurrent state-based predictors, counterfactual simulator branches and independent task-outcome checks. Matched-budget planning comparisons and uncertainty calibration make model behavior inspectable at the action and trajectory level.

## What works today

- **Reproducible episodes.** Scripted and perturbed controllers, independent task outcomes, trajectory export, replay from saved initial state, and audited train/dev splits.
- **Predictive models.** Nominal dynamics, a learned residual ensemble, and a recurrent state-based latent predictor, compared on held-out episodes.
- **Planning.** Cross-entropy method model-predictive control over the learned or nominal model, with matched interaction budgets and an uncertainty penalty.
- **Action-chunk scoring.** Progress, clearance, constraint violations and calibrated uncertainty, with abstention outside the accepted range.
- **Read-only imports.** Completed exports are accepted only after completion-marker and SHA-256 verification. The importer never modifies the producing project.

## Results and limits

**M0 and M1 have passed their recorded exit tests.** These are simulation results on the declared task and development suites, not real-robot validation.

| Measurement | Recorded result | Evidence |
|---|---|---|
| Planning success, matched 200-episode suite | Learned MPC **184/200**; nominal MPC **184/200**; scripted controller **183/200** | [Planner comparison](reports/WO-005-m1-planner-and-chunk-scorer.md) |
| Constraint prediction on fresh simulator branches | AUROC **0.922**, bootstrap interval **0.887–0.952**, on retained chunks; **9.4%** abstention | [Scorer retest](reports/WO-016-m1-et5-retest.md) |
| Observation-model compute pilot | **62.3 images/s** on M3 Pro MPS for the tested image-tokenizer training workload | [Mac pilot](reports/WO-017-m2a-mac-pilot.md) |

The learned dynamics produced **no planning-success advantage** over the nominal model. The scorer's pooled advantage over nominal comes mainly from chunks that change the gripper command; the two models were similar on arm-offset chunks. An action-chunk score is not a full-episode success estimate.

The image pilot measures throughput, not evaluator quality. A policy-compatible closed-loop evaluator (M2), real-arm validation, synthetic-data benefits (M3), and drone adaptation (M4) remain unproven. See the [current status board](docs/STATUS_BOARD.md) for phase and exit-test evidence.

## Inspect and run checks

Python **3.12+**. The CPU tier uses the pinned `ironclad-kit` dependency, currently hosted in a **private repository**; installation requires access to `kudratsingh/ironclad`. The public checkout is not a standalone simulator or model-weight distribution.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e . -r requirements-dev.txt
make check
ironclad contract-info
```

`make check` runs lint, types, unit/contract tests, policy verification, secrets scanning and link checks. It does not repeat the recorded simulator experiments. For simulator setup, pinned environments, data and reproduction commands, follow the [environment guide](docs/ENVIRONMENT.md) and the reports above. Raw datasets and trained checkpoints are not bundled here.

## Code and documentation

| Area | Entry point |
|---|---|
| Episode collection, export and replay | [src/vishwaroop/sim](src/vishwaroop/sim/) |
| Predictors and calibration | [src/vishwaroop/models](src/vishwaroop/models/) |
| CEM planner and action scoring | [planning](src/vishwaroop/planning/), [scoring](src/vishwaroop/scoring/) |
| Export verification | [importer.py](src/vishwaroop/importer.py) |
| Evaluation design and phase boundaries | [Evaluation protocol](docs/EVALUATION_PROTOCOL.md), [phases](docs/PHASES.md) |
| Design and recorded results | [Architecture](docs/ARCHITECTURE.md), [reports](reports/), [status](docs/STATUS_BOARD.md) |

The name comes from Sanskrit *viśvarūpa*, the universal form. Part of the [Physical AI Program](PROGRAM.md). Contributors should read [AGENTS.md](AGENTS.md) before making changes.
