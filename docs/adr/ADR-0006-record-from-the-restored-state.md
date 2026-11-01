# ADR-0006 — Record each episode from its restored initial state

**Date:** 2026-11-01 · **Status:** accepted · **Work order:** WO-001 · **Program link:** PROGRAM §5.2

## Context
`evals/M0-protocol.md §7` says replay restores the saved initial state only, then executes the recorded actions through physics. The first recording path saved the state right after `reset` and took its first action from there, without restoring.

An early sweep with that path found replays beyond the frozen 0.001 tolerance, while repeats agreed with one another. All figures below are **measured** on the owner's M3 Pro with the locked stack (run `20261101T051759Z_e444ac57`, code `50eebe9`, Python 3.12), on the nominal controller's actions, seeds 0–99. Six of those seeds could not be planned and are skipped, which leaves 94:

| Change at the start, same actions | Over 0.001 | Largest deviation | Label changed |
|---|---|---|---|
| Start from `reset`, not from the restored state | 31 of 94 | 0.0085 | 0 |
| Restore a state that has already been through one restore and save | 36 of 94 | 0.0089 | 1 |
| Move the cube's x by 0.0000001 m (1e-7) in the saved state | 31 of 94 | 0.0089 | 0 |

On Python 3.11, before the move, the same table read 32, 37 and 32.

Restoring is not exact. On all 94 seeds, saving again after a restore gave different bytes. An independent review diffed four seeds and found only four numbers of the robot's root pose changed, by about 1e-8. It also read velocities, joint forces, drive targets, controller targets, the cube's velocity, the sleep flag and the contact count, and these matched. The likely cause is that contact amplifies rounding-sized differences. That link is an inference, because PhysX's internals cannot be read from here.

## Decision
`record_episode` resets, saves the state, **restores that saved state**, and only then runs the policy. A recording therefore takes the same path as its replays. `evals/M0-exit-tests.json` and `evals/M0-protocol.md` do not change, and no threshold moves.

## Alternatives considered
| Option | Why not |
|---|---|
| Loosen the replay tolerance | Forbidden: a tolerance that would have to be loosened is a stop condition in WO-001, and it would hide the effect instead of removing its cause |
| Make the restore exact | Not available from here without changing the simulator. It would not make runs robust either, since moving the cube by 1e-7 m has the same effect |
| Replay from `reset` by seed | Breaks protocol §7, and would not test the saved state at all. The review also showed the state decides the run: changing the seed in the state file left deviation at 0.0 on 100 of 100 seeds |
| Report a blocker | Replay is reproducible once both runs take the same path, so nothing is blocked |

## Consequences
- With this decision, 200 of 200 sweep episodes replayed with a deviation of exactly 0.0 on all 3 repeats (seeds 100–149, all four families). The review found byte-identical recordings across fresh processes and different orderings of prior episodes.
- **ET-M0-3 therefore shows bit-exact reproducibility on one stack and one machine.** It does not show that these episodes are robust to small changes, and they are not. It says nothing about another CPU or operating system, which has not been run. By the owner's decision of 2026-11-01, Mac CPU physics is M0's platform of record, replay is claimed only on the same stack, and the replay command refuses another one. Linux replay and negative tests are re-run before Linux-recorded data is used in M1, and replay platforms are not mixed.
- **Mid-episode branches do not stay within tolerance.** Restoring a state saved mid-episode and continuing with the same actions went over 0.001 on 5 of 19 seeds at step 30, 11 at step 60, 15 at step 90, 15 at step 120 and 0 at step 150, with a largest deviation of 0.0079. No label changed. These restores also pass through `reset`, so the cause is not separated. **WO-005's simulator-branch validation and any claim under `AGENTS.md §13.6` must measure this for themselves** and may not assume that a branch reproduces its parent run.
- A tiny difference can occasionally change an outcome: one label of 94 changed above. A claim resting on one episode near a threshold is weak.
- `tests/test_sim_export_replay.py` and `tests/test_sim_record.py` pin the order of calls in a recording. `src/vishwaroop/sim/sensitivity.py` reproduces the table above.
