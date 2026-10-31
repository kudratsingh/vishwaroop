# CONTEXT_AND_DECISIONS.md — World Model & Planner

What an agent needs from the planning conversations (Sept–Oct 2026) to make the same choices the owner would. Program-level decisions live in `PROGRAM.md §11–12`; this file records the project-specific ones. Status words: *confirmed* (owner stated), *proposed default* (suggested, not objected to), *unknown*, *future option*.

## 1. Why this project exists

- The owner's next ML step (Oct 25, 2026): fine-tuning and RL on a pre-trained open model, **exciting and usable in the real world**, not a benchmark replication (code RLVR was "not very exciting"). *Confirmed.*
- On Oct 30, 2026 the owner chose two separate projects — Omni Drone and World Model & Planner — because the sim-to-real gap is large and he wants the world model to serve a purpose beyond the drone. *Confirmed.*
- The repository and Python package are named **`vishwaroop`**; "World Model & Planner" stays the descriptive name in prose. *Confirmed (Oct 31, 2026; ADR-0003).*
- The world model's first task/environment is the arm project (`vla-rl-so101`): its ManiSkill3 setup is the first environment, its VLA the first baseline and evaluation subject. *Confirmed.*
- Three uses were agreed: (1) data engine, (2) evaluator, (3) planner; with the correction that one model does not give all three and that the evaluator needs an action-conditioned observation model. *Confirmed (adopted from review).*
- Why the arm and not a digital-only target: in pure simulation the physics engine is already the perfect world model; evaluator and data engine only matter where reality differs from the simulator and real episodes are expensive. The SO-101 gives that at the lowest cost. *Confirmed.*
- The drone's noise (wind, vibration, estimator drift) makes it a worse first hardware target for the evaluator; the drone is the better target for self-motion/residual dynamics (M4). *Proposed default accepted.*

## 2. Decisions adopted from the two external reviews (Oct 30, 2026)

| # | Decision | Status |
|---|---|---|
| 1 | Latent planning (M1) is separate from closed-loop VLA evaluation (M2); M2 must reproduce every policy input, not plausible video | confirmed |
| 2 | Independent outcome validation and failure-data collection are permanent parts of the project | confirmed |
| 3 | M1 is an *action-chunk scorer*; real logs validate executed actions only; counterfactuals need executed simulator branches | confirmed |
| 4 | M3 keeps action-conditioned generation separate from generated-demo + IDM; matched reconstructible scenes; replay from initial state only; executability is simulator evidence, not physical success; SFT route only | confirmed |
| 5 | Build the reward-labelling infrastructure once, but keep the training reward classifier, the development evaluator and the final assessment as separate authorities | confirmed |
| 6 | Policy-identity holdouts by training run/family; development vs sealed confirmation suites; one authorized opening per milestone; revealed suites become regression | confirmed |
| 7 | Paired randomized trials with session-aware analysis; Wilson intervals; precision plan instead of "20 or 50 is enough" | confirmed |
| 8 | Physical success sensing (load cell, break-beam) plus blinded review, each covering what the other cannot | confirmed |
| 9 | The "only you can build" claim about the replay filter was removed; the contribution is a physics-replay check on matched scenes, measured against GR00T-Dreams-style filtering | confirmed |
| 10 | M4 branches from M0/M1 when drone logs exist; it does not wait for M2/M3 | confirmed |
| 11 | No rocket warm-up | confirmed |
| 12 | Arm integration is read-only through completed immutable exports; automatic export hooks are a future owner-approved arm-project change | confirmed |
| 13 | Budget caps are enforced by a launcher that an agent cannot bypass; default $0; measured pilot before any paid run | confirmed |
| 14 | Sealed suite opening budget: once per named suite per milestone report, logged | confirmed |
| 15 | Counterfactual claims on real data stay limited to actual intervention evidence, even after M2 | confirmed |

## 3. Working style (confirmed by the owner for his projects)

- Fast iteration and completion; autonomous agents working through bounded work orders; continue to the next ready work order without asking after every step (`AGENTS.md §2–3`). Independent review passes are not default; they are required on RL-loop and evaluator-validation work orders (project addendum, `AGENTS.md §13`).
- Never delete or overwrite data, runs, logs, reports; always append or create a new record.
- Diagnose cost and waste proactively with numbers before it accumulates; never carry an expensive recurring default silently.
- Phases have exit tests written before work starts; anyone can follow progress on the status board.

## 4. Relationship to the owner's other work

- `vla-rl-so101`: few-shot SFT then GRPO in ManiSkill3 on one rented GPU, then the real SO-101 (ordered Oct 26, 2026); HIL-SERL-style real-robot RL is a confirmed follow-on and the natural home of M6. Lock-in request to the arm project (owner action): freeze task configs and action space early so the evaluator evaluates the same robot.
- `coding-agent-from-scratch`: the owner's post-training expertise (SFT/RLHF/RLVR data at frontier labs) is the edge behind M5–M7.
- `incident-commander`: source of the "deterministic guards, independent judge, reward vs assessment" discipline.

## 5. Open decisions (project level)

| # | Decision | Default until decided |
|---|---|---|
| 1 | First ManiSkill3 task if the arm project's SO-101 adapter is not exportable yet | a readily available pick-and-place task, honestly labelled; no transfer claim |
| 2 | Base VLA family for M2 compatibility work | the arm project's choice; import as checkpoints only |
| 3 | Where sealed real-arm evaluation data lives | owner-controlled location outside agent access (unknown) |
| 4 | GPU for M1 training | rented 4090/A40-class until the workstation exists; cap $0 until approved |
| 5 | Teleop pilot scope for M3/M2b data | 10 successful demos + 10 safe autonomous/intervention episodes, one task, named object set (proposed default) |
| 6 | Remote repository designation | decided: `kudratsingh/vishwaroop`, private (ADR-0005) |

## 6. Contradictions found while consolidating (and how they were resolved)

| Conflict | Resolution |
|---|---|
| Reference kit: "no branches/PRs/GitHub writes" and "stop after every completed work order" vs owner (Oct 30): autonomous iterative development with branches, PRs and merges in the designated repositories | Owner's latest instruction governs (`AGENTS.md §2–4`); remote operations still require a designated remote; §2.3 gates unchanged |
| Reference kit: "evaluator covered by the latent tier" vs review: latent tier cannot evaluate an unchanged visual VLA | Review adopted: M1 scorer vs M2 evaluator are separate phases |
| Reference kit: `WO-002` numbering used twice (budget and D1 in the drone kit) | Renumbered; numbering is global and never reused |
| Reference kit CLAUDE.md held the whole policy and was identical across projects including world-model-only rules | Policy moved to `AGENTS.md` with a shared core and a project addendum; `CLAUDE.md` is a pointer |
| Reference kit README implied evidence could be added by editing an episode manifest | Append-only validation ledger added to the contract; manifests are write-once |
