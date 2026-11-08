# WO-021 | ET-M3-1 under `m3-protocol-3`: failed at its tolerance pilot

**Date:** 2026-11-07 · **Result:** failed, by the frozen `if_it_fails` (**measured**, simulation) · **Next:** `m3-protocol-4` (draft `docs/M3-protocol-4-draft.json`, for the owner's review)

## What happened
ET-M3-1's tolerance pilot under `evals/M3-protocol-3.json` ran once, at clean commit `5cd71e1`, as run `20261108T040245Z_f9f36234`, on block 10 seeds 10920 to 10939. Its result is in that run's `et_m3_1_pilot_p3.json`. The pilot exited 4 by its frozen stop (9), the only stop that held:

> (9) the goal-centroid distance 16.44 px is at least the smallest image displacement of a 0.03 m goal move, 11.35 px (seed 10936), so a type-4 pixel shift could pass

| Observed over unmodified pilot frames | Value | Where |
|---|---|---|
| Largest goal-centroid distance from the snapshot's | 14.95 px (widened 16.44 px) | seed 10936, frame 114 |
| Smallest image displacement of a 0.03 m goal move | 11.35 px | seed 10936 |
| Final frames | all show the cube (r 0.607 to 1.206); no run with r < 0.02 | all 20 |
| Size-checkable frames | 19.1% of frames, at least 16 per candidate; r 1.000 to 1.002 | |
| Merge radius | 27.1 px (stop 8 limit 60 px) | |

The cube rules held. The goal check's tolerance did not separate normal goal-centroid drift from a 3 cm goal move.

## What was not done
No tolerances file, control or injection was generated under `m3-protocol-3`. Its control seeds (10580 to 10639), injection seeds (10520 to 10579), type-3 replacement seeds (10660 to 10749) and type-6 render seeds (10770 to 10779) were never simulated. Its pilot seeds 10920 to 10939 are spent.

## After the stop
The owner was told before any candidate was generated, and everything paused. On 2026-11-07 the owner chose option 1 (`ledgers/approvals.jsonl` `approvals-20261108T043859003982Z-5837a2ac`): a ledgered diagnostic on the spent pilot seeds, then a draft `m3-protocol-4` changing only the goal check.

The diagnostic runs, all on spent pilot seeds and writing nothing to `evals/`, were:
- `20261108T044149Z_1a94815d`;
- `20261108T044845Z_616d515d`;
- `20261108T045902Z_f0336752` (an analysis without simulation).

They found the drift was occlusion. At frame 114, 2.9% of the goal was visible. The snapshot render's own goal was half hidden, which biased the reference by 5.2 px. The draft's `known_before_this_freeze` gives the numbers.
