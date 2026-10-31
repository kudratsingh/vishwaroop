# M0 protocol — task rubric, splits, holdouts, sealed budget, baselines

**Version `m0-protocol-2`. Frozen 2026-10-31, before any simulator episode, replay, dataset or training result exists.** It replaces `m0-protocol-1` after an independent review, also before any result. It adds the family-to-partition rule, the label order, `target_position` as a compared stream and the M1 task suite; no threshold is loosened. Numbers live in `evals/M0-exit-tests.json` and `evals/M1-exit-tests.json`. The task choice and its limits are in `docs/adr/ADR-0004-m0-task-choice.md`. Changing anything here after seeing results needs an ADR and a new protocol version; the old version stays.

## 1. Task
ManiSkill3 `PickCubeSO100-v1`, joint-position control, state observations, CPU physics, at most 200 control steps per episode. **This is the simulated SO-100, not the owner's SO-101. No transfer claim to any physical arm follows from M0.**

## 2. Independent outcome rubric (`m0-place-1`)
The environment's own `success` and reward are not used. Its success never checks release, because its goal can sit in mid-air. The goal's xy position is used as the target on the table.

An episode succeeds when all of these hold, computed by `src/vishwaroop/outcome/pickplace.py` from recorded simulator state. Sample 0 is the state before the first action, so the last 10 steps span 11 samples:

| Condition | Requirement |
|---|---|
| Picked | at some step the cube's height was at least 0.02 m above its rest height |
| In target | at the end of each of the last 10 steps, the cube's xy distance to the target is at most 0.015625 m |
| On the table | at the end of each of the last 10 steps, the cube's height is within 0.005 m of its 0.0125 m rest height |
| Released | at the end of each of the last 10 steps, the simulator does not report the cube as grasped |
| Settled | during each of the last 10 steps, the cube moves at most 0.001 m |

Failure labels, used by WO-002, in the order they are checked, so that the first failure gives the label: `never_lifted`, `still_grasped`, `not_on_table`, `outside_target`, `not_settled`. An episode with fewer than 11 samples, or with an invalid or non-finite sample, gets `success: null` and `insufficient_evidence`; it is never counted as a failure.

The rubric shares no code, labels or weights with any policy, reward or learned model. A test enforces that its module imports only the standard library.

## 3. Splits and group ids
- Partitions: `train`, `dev`, `sealed`, `regression`.
- `scene_group_id`: `m0-seed-block-<n>`, where block `n` holds seeds `[1000n, 1000n + 999]`. Whole blocks go to one partition.
- `session_group_id`: the collection run id. A run's episodes stay in one partition.
- Partition assignment: blocks 0–7 `train`, blocks 8–9 `dev`. M0 assigns no block to `sealed`, and WO-002 creates no `sealed` partition.
- **A policy family lies wholly in one partition.** `dev` holds whole families never used in `train`, because `audit_splits.py` treats `policy_run_group_id` as a holdout axis.
- Shift axes frozen for M0: cube and goal placement by seed. Lighting, distractors and object identity do not vary in M0.
- `contracts/v1/audit_splits.py` must pass on every assembled set.

## 4. Policy holdout
`policy_run_group_id` names the **training run or family**, never a checkpoint. Snapshots from one run are candidates, not independent held-out policies. In M0 the only policies are scripted: each scripted controller and its perturbation family is one family, `m0-scripted-<name>`. Held-out evaluation in later milestones holds out whole families.

## 5. Sealed opening budget
- M0: no sealed suite exists, so the budget is 0 and nothing can be opened.
- M1: no sealed suite. M1 claims rest on `dev`.
- From M2a: at most one owner-authorized opening per milestone report, logged in `ledgers/sealed_access.jsonl`, with a revealed suite becoming `regression` (`docs/EVALUATION_PROTOCOL.md §2`).

## 6. Baselines
- M0: the scripted controller is the only policy. It exists to produce successes and failures, not to be compared.
- M1: constant and linear predictors, a nominal dynamics model, nominal-model MPC, and the scripted controller, on matched budgets and data.
- M1 task suite `m1-suite-1`: this task on seed blocks 8–9, 200 episodes per planner, with the same seeds across planners. `evals/M1-exit-tests.json` holds the numbers and the ET-M1-4 decision rule.

## 7. Replay
Replay restores the saved initial state only, then executes the recorded actions through physics. Deviations are compared on `joint_position` (rad), `object_position` (m) and `target_position` (m) against the frozen tolerance, over 3 repeats, with identical outcome labels required. A non-finite value counts as an infinite deviation. The episode must match the simulator on engine, version, stack, assets, configuration, action meaning, stream meaning and timebase, and its recorded outcome must match the rubric. An undecided episode supports no claim. Forcing state during a replay invalidates the claim.

## 8. What a pass means
A pass is simulated evidence on this stack, for this task. It says nothing about a physical arm (`docs/EVALUATION_PROTOCOL.md §8`).
