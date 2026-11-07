# WO-021 | ET-M3-1 under `m3-protocol-1`: failed at its tolerance pilot

**Date:** 2026-11-07 · **Result:** failed, by the frozen `if_it_fails` (**measured**, simulation) · **Next:** `m3-protocol-2` (`evals/M3-protocol-2.json`)

## What happened
ET-M3-1's tolerance pilot ran once, at clean commit `5ca439e`, as run `20261107T083058Z_83f404c3`, on block 10 seeds 10900 to 10919. Its result is in that run's `et_m3_1_pilot.json`. The pilot exited 4 by its frozen stop rule:

> the widened band [0.1583, 2.131] is not inside 0.36 < a_lo and a_hi < 2.56, so no frozen band contains every pilot frame

| Observed over unmodified pilot frames | Value | Where |
|---|---|---|
| Cube area ratio, minimum | 0.176 | seed 10900, frame 90, under the gripper |
| Cube area ratio, maximum | 1.938 | seed 10908, frame 185, placed nearer the camera |
| Widened band | [0.158, 2.131] | outside the frozen limits |
| Largest merge distance | 28.5 px | seed 10908, frame 113 |

A band wide enough to accept every real frame also accepts the 0.6 and 1.6 resizes, whose areas are 0.36 and 2.56 times the original. So the frozen area check could not detect a resized cube, and ET-M3-1 as frozen could not pass. This is a flaw in the freeze's design, not a code bug.

## What was not done
No tolerances file, control or injection was generated under `m3-protocol-1`. Its control seeds (10000 to 10059), injection seeds (10100 to 10159) and type-6 render seeds (10650 to 10659) were never simulated. `m3-protocol-2` does not use any of them.

## After the stop
The owner was told before any candidate was generated, as the rule requires. On 2026-11-07 the owner chose option A (`ledgers/approvals.jsonl`): run the size check only in frames where the cube's size is knowable, with those frames chosen independently of the area measurement. `m3-protocol-2` freezes that before its own pilot on seeds 10300 to 10319.

Three scratch diagnoses on the spent pilot seeds 10900 to 10919 informed `m3-protocol-2`. They were not ledgered and wrote nothing to `evals/`; `evals/M3-protocol-2.json` (`known_before_this_freeze`) gives their numbers.
