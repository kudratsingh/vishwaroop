# WO-021 | ET-M3-1 under `m3-protocol-2`: failed on false rejections

**Date:** 2026-11-07 · **Result:** failed (**measured**, simulation) · **Run:** `20261107T113835Z_1d794f74` at clean `4efb133`, scored once · **Rules:** `evals/M3-protocol-2.json`, tolerances `evals/M3-checker-tolerances.json` (sha256 `a52ca7db…2b37`, pilot run `20261107T113546Z_783f6d54`)

## Verdict
| Requirement | Result |
|---|---|
| All 60 injections rejected under the credit rule | 54 of 60. **All 60 injected candidates failed a check**; 6 were not credited because their unmodified source also failed. |
| At most 3 of 60 controls falsely rejected | **9 of 60** (15%, Wilson 95% 8.1% to 26.1%) |

Controls and sources are physics renders, so this does not estimate false rejection on generated frames (ET-M3-2 measures that).

## Cause: the presence band's tails
Every false rejection, and every failing source, failed `cube_area`: the every-frame presence band [0.116, 1.309]. This band is protocol-1's rule, the 20 pilot seeds' extremes widened by 10%. Fresh seeds went past it on both sides:

| | Candidates | Area ratio at the first failing frame |
|---|---|---|
| Above 1.309 (cube carried or placed nearer the camera) | 6 controls, 5 sources | 1.312 to 1.491 |
| Below 0.116 (cube occluded by the gripper) | 3 controls, 1 source | 0.069 to 0.115 |

That is 15 of 120 unmodified candidates (12.5%). The pilot saw 0.129 to 1.190. Protocol-1's pilot, on other seeds, saw 0.176 to 1.938. So 20 seeds do not pin down these tails, and a 10% widening does not cover them.

**The new size check did its job.** No control and no source failed `cube_size`.
- The size check ran on 19.4% of control frames (median 33 frames) and 19.5% of source frames.
- One control (10406) had no size-checkable frame. It passed, as the rule says.
- No resize source needed a replacement seed.

## What caught each injection (credited injections)
| Type | Credited | Caught by |
|---|---|---|
| object removed | 8 / 10 | `cube_area` 8, `cube_size` 1 |
| object duplicated | 10 / 10 | `extra_red` 10 |
| cube resized | 8 / 10 | `cube_size` 8, `cube_area` 4 |
| goal or task changed | 9 / 10 | `manifest` 7, `goal_centroid` 2 |
| asset hash broken | 9 / 10 | `manifest` 9 |
| initial render mismatch | 10 / 10 | `first_frame` 10 (and others) |

## What follows
Recorded as failed, as `if_it_fails` says. A further revision needs `m3-protocol-3`, the owner's decision, a new pilot on unused block 10 seeds, and fresh controls and injections. The seeds of this run (10200 to 10259, 10300 to 10319, 10400 to 10459, 10750 to 10759) are spent. Seeds 10800 to 10899 were never simulated, because no replacement was needed.
