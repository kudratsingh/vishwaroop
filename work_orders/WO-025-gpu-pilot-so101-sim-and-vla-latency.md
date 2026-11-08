# WO-025 | GPU pilot: SO-101 simulator throughput and VLA inference latency (proposal, awaiting approval)
**Phase:** M2a
**Exit tests advanced:** none. It measures the workloads the M2 twin, M5-early and the deferred workstation decision depend on.
**Size:** S
**Prerequisites:** WO-024 (CUDA-portable code; CUDA untested until this runs). **Owner approval of this text, with the cap, before any rental.**
**Authorization:** needs §2.3 approval for paid compute. Owner, 2026-11-08 (`approvals-20261108T132556755986Z-2add2fa0`, item 2): "Revise the pilot plan first. I'm open to using the $50 ceiling for SO-101 simulator throughput and VLA inference latency. Send the exact workload, checkpoint, VM quote, and stop conditions for a fresh approval before I rent it." The owner rents, starts and stops the machine. The agent only connects over SSH.
**Files:** `src/vishwaroop/models/` (a new latency and throughput script), `tests/`, `config/` (a Linux CUDA lock), `work_orders/`, `reports/WO-025-gpu-pilot.md`, and the ignored `runs/`.
**Supersedes, if approved:** WO-018's GPU plan (tokenizer training speedup). WO-018's Mac frame bundle stays as recorded; its full M2a run is dropped with the from-scratch generator (owner, item 1).

## Objective
Answer two questions with measurements, on one rented card and on the Mac:
1. **Simulator throughput.** How fast does ManiSkill3 step and render an SO-arm scene on a GPU, compared with the Mac? This sizes the M2 twin's rollouts.
2. **VLA inference latency.** How long do ACT, SmolVLA and π0.5 take per decision, including batches of N candidates? Is that within the control budget, and what card class does that imply? This feeds M5-early's latency question and the workstation decision (owner item 6).

## The exact workload
**Software:** Python 3.12; `mani-skill==3.0.1` and `sapien==3.0.3` (this repository's resolved lock); `lerobot==0.6.1` (2026-08-03; 0.7.0 of 2026-11-05 is too new to pin); torch from a Linux CUDA lock resolved in this work order before the rental. Exact pins are recorded in `config/`.

**A. Simulator throughput.**
- **Environment:** `PickCubeSO100-v1`, upstream ManiSkill (SO-100; upstream has no SO-101). Physics backends `physx_cuda` on the GPU and `physx_cpu` on the Mac.
- **Scale:** `num_envs` in {1, 64, 256, 1024} on the GPU, and 1 on the Mac. Observation modes `state` and `rgb` (one 128 × 128 camera, then 480 × 640).
- **Timing:** 50 warm-up steps, then 1,000 timed steps with random actions.
- **Reported:** environment steps per second, rendered frames per second, peak GPU memory, and the first-step compile time.
- **Optional, 20 minutes at most:** the same timing on Squint's SO-101 environment (MIT licence) at a pinned commit, if it installs cleanly on `mani-skill==3.0.1`.

**B. VLA inference latency.**
- **Inputs:** synthetic, at the SO-101 shapes: two 480 × 640 RGB cameras, a 6-joint state, and one instruction string.
- **Timing:** 20 warm-up calls, then 200 timed calls each at batch 1, 4 and 8. Batch 4 and 8 are the N candidates of best-of-N.
- **Reported:** p50, p95 and max milliseconds per call and per action chunk; peak GPU memory.

| Policy | Checkpoint | Size | Licence | Precision |
|---|---|---|---|---|
| ACT | LeRobot 0.6.1's default ACT config (ResNet-18, chunk 100), randomly initialised. Latency does not depend on the weights, and no trained SO-101 ACT exists yet. | ~0.2 GB (estimated) | Apache-2.0 | fp32 |
| SmolVLA | `lerobot/smolvla_base` at revision `5e8d12a6e2975b0e5e5fce7c8caf47c371d257b6` | 0.91 GB `model.safetensors` | Apache-2.0 | bf16 |
| π0.5 | `lerobot/pi05_base` at revision `22c30e5b34f9e7ab738b1b34fc2fc5ecfe2d28f0` | 14.47 GB `model.safetensors` | Gemma terms; used for latency only, nothing redistributed | bf16 |

Weights load through safetensors only. Their sha256 is checked against the revision's LFS id before loading (`AGENTS.md §6.6`).

**The Mac first, at $0.** A and B run on the Mac (CPU physics, MPS inference) before the rental. That gives the baseline, and it debugs the script for free. π0.5 on MPS is attempted; out-of-memory or above 10 s per call is reported as a result.

## VM quote
From Runpod's `list-gpu-types`, on-demand Pod, secure cloud, read 2026-11-08. Stock is current only for that moment.

| Card | Memory | $/hour (secure) | $/hour (community) | Stock on 2026-11-08 | Role |
|---|---|---|---|---|---|
| **RTX 5090** | 32 GB | **$1.19** | $0.69 | LOW, in EU-RO-1 | **Proposed.** It is the consumer class a workstation would buy, it has graphics hardware for SAPIEN rendering, and π0.5 in bf16 fits in 32 GB (estimated). |
| L40S | 48 GB | $1.09 | $0.79 | LOW, in EUR-IS-2 and US-TX-4 | Fallback (WO-018's original choice) |
| RTX 6000 Ada | 48 GB | $0.99 | $0.74 | LOW, in US-WA-1 | Fallback |
| RTX 4090 | 24 GB | $0.89 | $0.34 | **none in stock** | Not available at the read |
| A40 | 48 GB | $0.59 | $0.35 | HIGH, in CA-MTL-1 and EU-SE-1 | Cheapest in stock, but an older Ampere card; less informative for a purchase |

- **One unverified risk:** Runpod Pods are containers, not VMs. SAPIEN's Vulkan rendering inside a Runpod container has not been checked. The setup check tests it first (stop condition 2).
- **The quote does not cover** other providers (Lambda, Vast and others), which were not read.

## Cost (estimated from the quote)
| Step | Hours |
|---|---|
| Setup and the setup check (`scripts/setup_gpu_host.sh --check-only`, then install) | 0.5 |
| A: simulator throughput | 0.75 |
| B: VLA latency (π0.5's 14.5 GB download included) | 0.75 |
| Copy-back and teardown check | 0.25 |
| **Total** | **2.25 h, about $2.70 at $1.19/h** |

- **Proposed cap for this work order:** **$10** of the $50 ceiling. That is about 8 hours at $1.19, including any stopped-disk storage.
- **Wall-clock stop:** 4 hours from start.

## Stop conditions
1. The cap: $10 spent, or projected to be spent before the remaining steps finish. Stop and leave the machine for the owner to stop.
2. The setup check fails: no CUDA, a driver older than the lock needs, or no Vulkan for SAPIEN. A runs without rendering only if the owner agrees, B continues, and the failure is reported.
3. A checkpoint's sha256 does not match its revision's LFS id. That checkpoint is refused and not loaded.
4. Four hours of wall clock.
5. Any need to start, stop, resize or replace the machine. That is the owner's action.
6. Any result that would need a second machine or a paid resource not in this text.

## Out of scope
- Training of any kind.
- Any real-arm checkpoint: none has been exported yet.
- Any arm motion.
- A second machine.
- Anything beyond the cap.

## Verification
- `make check`.
- The setup check's output.
- One `ledgered_run` per workload on each machine. Run directories and ledger lines are copied back.
- The report gives Mac and GPU numbers side by side, labelled **measured**.

## Exit criteria
Done when the report gives A and B on the Mac and on the rented card, and the actual cost. The report also says what the numbers imply for a local card. It makes no purchase recommendation beyond that implication.

## Report
`reports/WO-025-gpu-pilot.md`

## Progress (append-only)
