# WO-021 | ET-M3-1 under `m3-protocol-4`: failed at its tolerance pilot; ET-M3-1 on hold

**Date:** 2026-11-07 · **Result:** failed, by the frozen `if_it_fails` (**measured**, simulation) · **Next:** ET-M3-1 is on hold by the owner's decision. It reopens only with a new design (below).

## What happened
ET-M3-1's tolerance pilot under `evals/M3-protocol-4.json` (sha256 `52508a87852607ec4431d0bc70c8d36bca6b529b6115270373e769c2401f5c2e`) ran once. Details:
- clean commit `1b55ac7`;
- run `20261108T055657Z_063008b3`;
- block 10 seeds 10940 to 10959;
- result in that run's `et_m3_1_pilot_p4.json`.

The pilot exited 4 by its frozen stop (9). That was the only stop that held:

> (9) seed 10954: the final frame shows v_g 0.3246 of the goal, below 0.4

Seed 10954 is a nominal scripted episode. From frame 136 to the final frame, 185, the arm covers most of the goal, and v_g stays below 0.4 for all 50 frames.

| Observed over unmodified pilot frames | Value | Where |
|---|---|---|
| Final-frame goal visibility v_g | 0.325 (below the 0.4 floor) | seed 10954 |
| Other final frames' v_g | 0.545 to 1.024 | 19 seeds |
| Largest centroid distance minus its envelope E | −0.67 px (every frame inside its envelope) | seed 10956 |
| Stop (10): smallest margin by which a whole-pixel 0.03 m shift leaves the envelope at T | 1.16 px (stop (10) held for no seed) | seed 10954 |
| Size-checkable frames | 17.7% of frames, at least 16 per candidate; r 1.000 | |
| Cube movement in size-checkable frames | at most 1.7e-6 m | |
| Merge radius | 27.3 px (stop 8 limit 60 px) | |
| Size band | [0.9, 1.1] | |
| Final frames | every one shows the cube (smallest r 0.275) | all 20 |

The new goal envelope held in every frame, and the cube rules held. What failed is the final-frame visibility floor: a normal episode can end with its goal mostly hidden by the arm.

At 10954's final frame a lasting 0.03 m goal move would still have been caught, by 1.16 px. The failure is therefore a false rejection of an unmodified episode, not a missed shift. The rule as frozen still sinks the test, because stop (9) halts the pilot before any control is generated.

## What was not done
Nothing was written to `evals/`. No tolerances file, control or injection was generated under `m3-protocol-4`.

## Seeds
- **Spent:** the pilot seeds 10940 to 10959.
- **Held for ET-M3-1:** the seeds protocol 4 named for other uses, which were never simulated:
  - 10260 to 10299 (type-3 replacements);
  - 10320 to 10379 (controls);
  - 10460 to 10519 (injections);
  - 10780 to 10789 (type-6 renders).

  They stay unused. `src/vishwaroop/synth/protocol.py` lists them as `ET_M3_1_HELD_SEEDS`, and `check_not_held` refuses them, so work other than ET-M3-1 cannot take them.

## Record across protocols
None of the four protocols reached its acceptance thresholds (100% of 60 injections rejected; at most 3 of 60 controls falsely rejected). Those thresholds have not changed.

| Protocol | Ended at | Cause | Report |
|---|---|---|---|
| `m3-protocol-1` | tolerance pilot | the cube-area band could not fit inside its frozen limits | `reports/WO-021-et-m3-1-protocol-1.md` |
| `m3-protocol-2` | scoring | 9 of 60 controls falsely rejected, on the every-frame presence band | `reports/WO-021-et-m3-1-protocol-2.md` |
| `m3-protocol-3` | tolerance pilot, stop (9) | goal-centroid drift from occlusion overlapped a 0.03 m goal move | `reports/WO-021-et-m3-1-protocol-3.md` |
| `m3-protocol-4` | tolerance pilot, stop (9) | a normal final frame showed 32.5% of the goal, below the 0.4 floor | this report |

Every failure came from the same source: a fixed camera that the arm occludes. Each checker rule that needs to see the cube or the goal in a particular frame has met a normal episode where it is hidden.

## The owner's decision (2026-11-07)
In `ledgers/approvals.jsonl`:

> "Hold ET-M3-1. Preserve the protocol-4 stop record and the unused seeds. If we reopen it, bring a design that gives the checker a reliable view of the goal and defines how to handle scenes where visibility is insufficient. For now, prioritize SO-101 work that can proceed independently of this test."

**What a reopening must bring.** It must be a new protocol, with its own pilot on fresh seeds that no earlier protocol named. Two things are required:
1. **A reliable view of the goal.** One possibility is a second camera, or a camera placed so the arm cannot cover the goal. This is unverified.
2. **A defined rule for scenes where visibility is insufficient.** The rule must not let a lasting shift pass because the goal is hidden.

The acceptance thresholds and every failure record stay unchanged.

**What carries forward to ET-M3-2 regardless.** The owner's audits stay recorded in WO-021's progress section:
- temporary disappearances;
- late resizes;
- lasting goal shifts with the goal partly occluded in the final frame.

They are added by an amendment frozen before any ET-M3-2 data.
