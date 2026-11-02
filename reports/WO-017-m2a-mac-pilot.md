# WO-017 — M2a observation model: a 30-minute Mac pilot to check the GPU estimate

**Status:** passed
**Date:** 2026-11-02 · **Author:** claude-code-vishwaroop · **Work order:** WO-017 · **Phase:** M2a (a measurement only) · **Protocol version:** none applies
**Program link:** PROGRAM §5.2 → vishwaroop M2a

> Four words with fixed meanings throughout this report: **measured** (ran here, evidence attached), **estimated** (arithmetic from stated assumptions), **mocked/fixture** (fabricated for tests), **not run**.

## 1. Claim and scope
**The Mac trains a ViT-S/14-shaped image tokenizer at 224 × 224 at 62 images per second (measured), below the 80 that WO-005's estimate assumed. The estimate's conclusion stands: one full M2a observation-model run is hundreds of Mac hours, so M2a needs a GPU.** Nothing was rented. The GPU side is still an estimate, because only renting can measure it.

## 2. Method
- **Frames.** 3,720 real simulator frames from 20 scripted episodes on train seeds 6000 to 6019. Block 6 had never been simulated. Frames were rendered at 512 × 512 and resized to 224 × 224.
- **Model.** A ViT-S/14-shaped encoder (12 layers, width 384, 6 heads) with a linear per-patch pixel decoder: 21.8 million parameters.
- **Training.** AdamW at 3e-4, batch 32, MSE reconstruction, on MPS, for a fixed 20 minutes. Each step is synchronized, so its time is real. The first smoke test without synchronization reported 2,102 images per second, which was only the enqueue rate, and that was fixed before the ledgered run.

## 3. Reproduction
`python -m vishwaroop.models.m2a_pilot`, run `20261102T123148Z_66528fb8` at `81cdf31`, clean. M3 Pro, MPS, torch 2.15.0.

## 4. Results
| Measure | Value |
|---|---|
| Rendering | 412 frames per second (512 × 512, while stepping) |
| Training rate | **62.3 images per second** (median step); 61.5 overall |
| Steps, images | 2,306 steps, 73,792 images in 20 minutes |
| Peak Metal memory | 4.66 GB |
| Loss (MSE, pixels in 0 to 1) | 10.03 at the start, about 0.004 to 0.005 after 5 minutes, 0.0032 at the end |

**The estimate redone, estimated:**

| | WO-005's estimate | With the measured rate |
|---|---|---|
| Encoder rate on the Mac | 80 per second, assumed | **62 per second, measured** |
| Encoder alone, 600,000 images × 20 epochs | about 42 hours | **about 53 hours** |
| Full model (decoder and dynamics, 3 to 10 times the encoder) | hundreds of hours | **about 160 to 530 hours** |
| One H100-class GPU, assumed 20 to 50 times faster | 10 to 80 GPU-hours | **about 3 to 27 GPU-hours** |
| At about $2 to $3 per GPU-hour | $20 to $250 per run | **about $6 to $80 per run**, before failed runs |

The GPU rows rest on the unmeasured 20 to 50 times speedup. The Mac rows rest on the measured rate. The new GPU range is lower than WO-005's because WO-005 rounded its multipliers up.

## 5. Failure analysis
- **The loss says little.** 3,720 frames from 20 episodes are few, and nothing was held out, so the falling loss shows the model trains, not that it generalizes.
- **Several numbers are assumptions.** The resolution, one camera and the dataset size are mine. An arm checkpoint's real input spec (WO-006) could change all of them.

## 6. Cost and latency
$0. About 21 minutes of Mac time: 9 seconds rendering and 20 minutes training.

## 7. Sealed access
None.

## 8. Exit tests and acceptance
None; a measurement. CI only (`AGENTS.md §13.8`).

## 9. Limits
- **No GPU was measured.** The speedup is assumed.
- **Encoder only.** No decoder or dynamics model beyond the per-patch head was trained.
- **One camera at 224 × 224,** both assumed.

## 10. Next bounded work order
M2a's first work order, when the owner opens it. On this evidence it needs a GPU. The next measurement is a short GPU pilot of the same code, which would need §2.3 approval and a cost estimate written before renting. Rollback: reverting removes the pilot. Its run stays.

## 11. Retro note
The unsynchronized timing would have overstated the Mac's rate by 30 times. A smoke test before the ledgered run caught it.

## Errata (append-only)
