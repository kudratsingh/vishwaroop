# WO-018 | M2a: a GPU pilot to measure the speedup over the Mac, then one full run if it fits
**Phase:** M2a
**Exit tests advanced:** none
**Size:** S
**Prerequisites:** WO-017 accepted; the owner's approval in `ledgers/approvals.jsonl` (2026-11-02, $50 total).
**Authorization:** AGENTS §2.3, paid compute, approved by the owner. The owner rents, starts and stops one single-GPU Linux VM, and the agent only connects over SSH. Nothing runs before the owner's explicit go. The full run needs a second explicit approval with its projected cost.
**Files:** `src/vishwaroop/models/m2a_pilot.py`, `src/vishwaroop/models/compute_pilot.py`, `tests/`, `work_orders/`, `ledgers/approvals.jsonl`, `docs/CONTEXT_AND_DECISIONS.md`, `reports/WO-018-m2a-gpu-pilot.md`, ignored `runs/`.

## Objective
Measure the real training speedup of the WO-017 tokenizer on a rented GPU over the Mac, on identical frames, and project the cost of one full M2a observation-model run. Then start that run only if it fits the remaining cap and the owner approves it with the number.

## Cost estimate, written before the VM goes up (**estimated**; the owner confirms the quote)
| Item | Value |
|---|---|
| Instance | 1 × NVIDIA **L40S 48 GB**, a single-GPU Linux VM (not a container). 8 or more vCPU and at least 64 GB RAM. |
| Why the L40S | It renders through Vulkan, which the full run's simulator frames need, as well as training. A data-centre H100 or A100 trains faster but lacks graphics hardware for SAPIEN rendering. |
| Fallback | RTX 6000 Ada 48 GB, then A6000 48 GB. |
| Image / OS | Ubuntu 22.04 x86_64, NVIDIA driver **580 or newer** (the lock pins CUDA 13.2), `nvidia-smi`, `libvulkan1` and NVIDIA's Vulkan ICD (`nvidia_icd.json`), `git`, `python3.12` or `uv`, coreutils `timeout`. |
| Disk | **200 GB.** The pilot needs about 25 GB. A full run's frames at 224 × 224 are 45 GB uncompressed per 300,000 images. |
| Assumed rate | **about $1.00 per hour** (range $0.80 to $1.40), not a quote |
| Pilot | install up to 30 min; frames copied from the Mac (560 MB); three 10-minute trainings: batch 32 fp32 (like for like), batch 128 fp32, batch 128 bf16. About **1.5 hours**, hard stop 3 hours, so **about $2 at most $4**. |
| Full run | Projected from the pilot's measured rate. With WO-017's arithmetic (160 to 530 Mac hours) and an assumed 10 to 30 times speedup on an L40S, about **5 to 50 GPU-hours, about $5 to $70.** The pilot narrows this. The run goes ahead only if its projection, with a 25% margin, fits the cap left after the pilot. |
| Cap | **$50 in total** (owner's approval). Storage while stopped counts too. |

## What the full run would train
No M2a work order fixes the model yet. Arm checkpoint inputs (WO-006) are still unknown, so a full run now means the tokenizer with an action-conditioned latent dynamics model, on one 224 × 224 simulated camera. It is frozen in its own short work order before the owner approves it with a number.

## Scope
1. The owner rents the VM and gives SSH. The agent runs `scripts/setup_gpu_host.sh --check-only` and reports. Then, after the owner's go, it runs the full setup.
2. The same frames go to both machines: `python -m vishwaroop.models.m2a_pilot --save-frames frames.pt` on the Mac, sha256 recorded. Then `--frames frames.pt --frames-sha256 <hash> --device cuda --seconds 600`, at batch 32 and 128, fp32 and bf16, on the VM. Each run is ledgered on the VM, and its run directory and ledger lines are copied back.
3. Report the measured speedup and the projected cost per full run.

## Out of scope
Starting or stopping any machine; a second machine; anything past $50; the full run without its own approval.

## Verification
`make check`; the setup check's output; the pilot runs' `m2a_pilot.json` on both machines from the same frames hash.

## Exit criteria
Done when the report gives the measured speedup and the projected cost, and either the full run's result or the reason it did not run.

## Stop conditions
Spend projected past the remaining cap; the setup check fails; any need to start, stop or resize the machine.

## Report
`reports/WO-018-m2a-gpu-pilot.md`
