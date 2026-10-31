# ADR-0004 — M0 task: `PickCubeSO100-v1` with an independent place rubric

**Date:** 2026-10-31 · **Status:** accepted · **Work order:** WO-001 · **Program link:** PROGRAM §5.2, §6

## Context
WO-001 needs one ManiSkill3 task. The preferred target is the arm project's task configs and action space, but no completed export exists, and `AGENTS.md §1.1` forbids reading that repository. `docs/CONTEXT_AND_DECISIONS.md §5` sets the default: a readily available pick-and-place task, honestly labelled, with no transfer claim. PROGRAM §6 says M0 does not wait for the arm project.

Read from the `mani_skill` 3.0.1 source on 2026-10-31:
- Two tasks use the SO-100: `PickCubeSO100-v1` and `SO100GraspCube-v1`. The SO-100 URDF and meshes ship in the package. No task uses an SO-101.
- `PickCube`'s `success` is "cube within `goal_thresh` of the goal, and robot static". It does not require release, and the goal's centre can be up to 0.0925 m above the table, which is 0.08 m above the cube's rest height.
- `PlaceSphere-v1` and `StackCube-v1` do require release. Their source does not offer the SO-100.

## Decision
- **Environment:** `PickCubeSO100-v1`, `pd_joint_pos` control, state observations, `physx_cpu`, `max_episode_steps` 200. The registered limit of 50 steps at 20 Hz is 2.5 s, too short to pick, place and dwell.
- **Embodiment label:** `maniskill3_so100`. This is the simulated SO-100, not the SO-101. **No transfer claim.**
- **Outcome:** the rubric in `evals/M0-protocol.md`. It uses the goal's xy position as a target on the table and requires lift, release and dwell. It does not use the environment's `success` or reward.
- **Proposed stack, not yet tested end to end:** Python 3.11, `mani_skill` 3.0.1, `sapien` 3.0.3. `config/stack-lock.resolved.json` is written only when an episode has run on it. `AGENTS.md §8.6` sets Python 3.12 or later for this repository's code; the robotics environment is separate (`docs/ENVIRONMENT.md §1`) and its Python is whatever the pinned stack supports. A test keeps the simulator code parseable on 3.11, and that environment runs it with `PYTHONPATH=src`, because the package itself requires 3.12.

## Alternatives considered
| Option | Why not |
|---|---|
| Wait for the arm project's export | PROGRAM §6 says M0 does not wait; a later export gets its own ADR |
| `PickCube-v1` (Panda) | a lab arm the owner will not own; further from the program's embodiment |
| `PlaceSphere-v1` or `StackCube-v1` (Panda) | these require release, but on the wrong arm; a rubric on the SO-100 task gets both |
| `SO100GraspCube-v1` | has no placement goal |
| The environment's own `success` | no release, and independence requires not using the environment's task logic |

## Consequences
- The task is pick-and-place by rubric, not by the environment's reward, so reward-based results from this environment do not measure this task.
- Nothing here shows a scripted controller can pass the rubric within 200 steps, because no episode has run. **Not run** is the honest status. If the first runs show the task cannot produce both successes and failures, a new ADR supersedes this one; the replay tolerance stays frozen.
- An arm-project export replaces this task through a new ADR.

## Reversibility
Cheap until WO-002 collects data: a new ADR and a new protocol version. Afterwards, data stays attributed to this task under its recorded rubric version.
