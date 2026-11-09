# WO-025 — GPU pilot: SO-101 simulator throughput and VLA inference latency (Mac baseline)

**Status:** Mac baseline measured; **GPU part not run** (no rental approved) · **Date:** 2026-11-09 · **Author:** claude-code-vishwaroop · **Work order:** WO-025 · **Phase:** M2a (tooling; no exit test) · **Protocol version:** none
**Program link:** PROGRAM §9 (rent before buying) → M2 twin rollout cost, M5-early latency, the deferred workstation decision

> Words with fixed meanings in this report: **measured** (ran here, evidence attached), **estimated** (arithmetic from stated assumptions), **mocked/fixture** (fabricated for tests), **not run**. **Reference** marks SO-100 numbers, which are never SO-101 throughput.

## 1. Claim and scope
On the owner's M3 Pro, the following were **measured**:
- **The required SO-101 scene:** steps and renders at the rates in §4.1.
- **ACT, SmolVLA and π0.5:** take the per-call latencies in §4.2 at batch 1, 4 and 8, with π0.5 at batch 8 above the 10 s stop.

**Not shown:**
- anything about a GPU;
- anything about the calibrated twin (this scene uses uncalibrated drive gains);
- any policy's task success.

The GPU half waits for the owner's approval of the revised work order and of the gate route (§10).

## 2. Frozen method
No exit test, so nothing is frozen (tooling under `AGENTS.md §13.10`).
- **The workload:** the one the work order fixes before the run: 1,000 timed simulator steps after 50 warm-up steps, and 200 timed latency calls after 20 warm-up calls.
- **Owner's words** (`approvals-20261109T010005936999Z-5e60e401`): "Run the $0 Mac baseline. Keep $10 as the proposed ceiling. Before I rent, make rendered SO-101 throughput a required workload and label any SO-100 timing as a reference."

## 3. Reproduction
Run from the repository root.

```
# A (robotics environment, MoltenVK as in docs/ENVIRONMENT.md §4)
~/.cache/vishwaroop-robotics/sim.sh -m vishwaroop.models.wo025_sim_throughput --backend cpu
# B (LeRobot environment, config/lerobot-requirements.macos.txt plus ironclad-kit v1.2.0)
PYTHONPATH=src ~/.cache/vishwaroop-robotics/lerobot-venv/bin/python -m vishwaroop.models.wo025_vla_latency --device mps
```

| Run | Directory | Code commit | Dirty |
|---|---|---|---|
| A, simulator | `runs/20261109T011733Z_52957e3e` (`sim_throughput.json`, one `cell-NN.json` per configuration) | `a9f598d` | no |
| B, latency | `runs/20261109T012123Z_5266661e` (`vla_latency.json`) | `717c96c` | no |

**Machine:** Apple M3 Pro, 6 performance cores, 36 GB, macOS 26.5.2.

**A's environment:**
- Python 3.12.13, torch 2.15.0, `mani_skill` 3.0.1, `sapien` 3.0.3;
- MoltenVK 1.4.2 for rendering.

**B's environment:**
- lerobot 0.6.1, torch 2.11.0, transformers 5.5.4, huggingface-hub 1.33.0, safetensors 0.8.0;
- MPS for inference.

## 4. Results (all **measured**, Mac, one environment)

### 4.1 A: simulator throughput, 1,000 timed steps
| Scene | Label | Observation | Cameras | Control steps/s | Rendered frames/s | Create + reset (s) | First step (ms) | Peak RSS (MiB) |
|---|---|---|---|---|---|---|---|---|
| SO-101 | **required** | state | — | 3,381 | — | 1.90 | 4.8 | 651 |
| SO-101 | **required** | rgb 128 × 128 | front, wrist | 459 | 918 | 1.97 | 3.3 | 683 |
| SO-101 | **required** | rgb 480 × 640 | front, wrist | **199** | **398** | 1.85 | 3.9 | 700 |
| SO-100 `PickCubeSO100-v1` | reference | state | — | 1,365 | — | 1.44 | 1.4 | 497 |
| SO-100 `PickCubeSO100-v1` | reference | rgb 128 × 128 | base | 515 | 515 | 1.73 | 2.5 | 559 |
| SO-100 `PickCubeSO100-v1` | reference | rgb 480 × 640 | base | 416 | 416 | 1.90 | 2.7 | 570 |

Reading:
- **Physics only:** the SO-101 scene runs state-only physics faster than `PickCubeSO100-v1` (3,381 against 1,365 steps/s). Its task code is empty (no reward, no grasp check), while upstream's computes both every step. So the gap is task code, not the robot.
- **With rendering:** at the SO-101 cameras' raw size, rendering dominates. Two 480 × 640 cameras give 199 control steps/s.
- **Policy rate:** at a 30 Hz policy rate (an assumption; the arm project's rate is not known), 199 steps/s is about 6.6× real time per Mac process, before any policy inference (estimated).

### 4.2 B: inference latency per `predict_action_chunk` call on MPS, 200 timed calls
| Policy | Precision | Parameters | Chunk | Batch | p50 (ms) | p95 (ms) | max (ms) | p50 per action step (ms) | Peak MPS memory (GB) |
|---|---|---|---|---|---|---|---|---|---|
| ACT (random init) | fp32 | 51.6 M | 100 | 1 | **30.7** | 33.7 | 34.8 | 0.31 | 1.36 |
| | | | | 4 | 113.2 | 122.8 | 127.6 | 1.13 | 1.37 |
| | | | | 8 | 225.1 | 255.4 | 261.5 | 2.25 | 2.44 |
| SmolVLA (`smolvla_base`) | fp32 | 450 M | 50 | 1 | **377.5** | 416.5 | 439.4 | 7.55 | 2.58 |
| | | | | 4 | 1,070.9 | 1,129.4 | 1,204.8 | 21.4 | 2.91 |
| | | | | 8 | 2,097.8 | 2,340.9 | 2,546.7 | 42.0 | 4.42 |
| π0.5 (`pi05_base`) | bf16 | 4.14 B | 50 | 1 | **1,334.5** | 1,661.8 | 1,868.0 | 26.7 | 11.32 |
| | | | | 4 | 5,083.8 | 5,880.4 | 6,277.2 | 101.7 | 12.42 |
| | | | | 8 | first call 10,387 ms: above the 10 s stop, not timed further | | | | |

Load times:
- ACT: 3.6 s.
- SmolVLA: 11.7 s.
- π0.5: 216 s, including the hash check of the 14.5 GB file. Its download happened earlier and is not counted.

Weights (both downloaded and checked against the pinned sha256 and the Hub's LFS id before loading):
- `smolvla_base`: sha256 `7cd549ac2351fb069c0ddb3c34ad2d09cfc92b56a15dccdfc2e41467aaca01eb`.
- `pi05_base`: sha256 `0eb11ca9587678c1d2ef8cf32807c29f8ce53a2bfdfc1aa4a4c96f16fca59b0f`.

Reading:
- **Batching doesn't help on MPS.** Cost grows roughly linearly with N for all three policies: batch 8 costs 7.3× (ACT), 5.6× (SmolVLA) and over 7.8× (π0.5) of batch 1. So on this Mac, N candidates cost about N single calls.
- **ACT fits a control budget on the Mac.** One ACT chunk of 100 steps takes 31 ms. N = 8 candidates take 225 ms, under one 100-step chunk at 30 Hz (3.3 s, estimated).
- **The two VLAs do not fit a closed-loop budget on the Mac.** A SmolVLA chunk takes 378 ms. A π0.5 chunk takes 1.33 s, and 5.1 s at N = 4.
  - With `n_action_steps = 50` at 30 Hz (1.67 s per chunk, assumed), π0.5 at N = 1 fits only without a pause budget, and N ≥ 4 does not fit (estimated).
  - This is the latency case for a CUDA card that the rental would measure.

## 5. Failure analysis
- **No failed configurations.** All 6 simulator configurations and all 8 timed latency cells completed.
- **One expected stop:** π0.5 at batch 8 reached the 10 s first-call stop, as the work order planned, and is reported above as a result.
- **During development** (not in the evidence runs):
  - rendering needed MoltenVK's ICD on the Mac, as `docs/ENVIRONMENT.md` documents;
  - the first wrist-camera mount sat inside the gripper and was moved beside the jaws.

## 6. Cost and latency
- **$0.** No GPU was rented.
- **Mac wall time:** the simulator run took 33 s (01:17:33 to 01:18:06 UTC). The latency run took 43 min (01:21:23 to 02:04:35 UTC), most of it π0.5 at batch 4 (200 calls of about 5 s each).
- **Downloads:** about 15.4 GB of checkpoints plus SmolVLM2's backbone weights, into the user's Hugging Face cache.

## 7. Sealed access
None.

## 8. Acceptance gate by gate
| WO-025 exit criterion | State |
|---|---|
| A and B on the Mac | met (**measured**, §4) |
| A and B on the rented card | **not run**: rental not approved |
| Actual cost reconciled | not applicable until a rental |
| What the numbers imply for a local card | partial, §9; the GPU numbers are needed |

The work order stays `in_progress`.

## 9. Limits
- **Synthetic latency inputs.** Images are random, and prompt tokens are random ids at the padded length, so the pre-processor (normalisation, tokenisation) is not timed. The PaliGemma tokenizer is gated and was not used.
- **Camera keys.** The two SO-101 frames fill the checkpoint's first two image keys.
  - SmolVLA declares three cameras with `empty_cameras = 0`, so it processes two.
  - π0.5 declares three and pads the third with a blank image that it still processes.
  - Both behaviours are lerobot 0.6.1's own; a real SO-101 export may declare different keys.
- **ACT's weights are random.** Latency depends on shapes, not values, but an exported ACT may use different chunk and backbone settings.
- **Precision.** SmolVLA runs fp32 because its config sets no dtype; bf16 might be faster and is not measured. π0.5 runs bf16.
- **Uncalibrated scene.** The SO-101 scene uses ManiSkill's SO-100 drive gains and generic camera intrinsics, and is not system-identified. Its rendering cost depends on mesh detail (13 manufacturer STL meshes of 0.1 to 2.7 MB each), which the twin may simplify.
- **One environment per Mac process.** `num_envs` above 1 needs GPU physics.
- **Not an idle machine.** The π0.5 download (network and disk) was running during the simulator run, and the Mac was in ordinary use, not reserved for the measurement.
- **SmolVLM2 backbone not pinned.** `HuggingFaceTB/SmolVLM2-500M-Video-Instruct` is fetched by lerobot without a revision; it resolved to `7b375e1b73b11138ff12fe22c8f2822d8fe03467` on 2026-11-08 (read with `model_info`), and the run did not record it itself.

## 10. Next work order
The GPU half of WO-025, once the owner:
- approves the revised text;
- chooses the gate route (owner-operated, proposed; or the ironclad launcher);
- approves the $10 ceiling.

The pinned image, the commands, the smoke-test plan and the gate steps are in the work order. WO-026 (R2 restore check) waits for the owner's scoped credentials.

## 11. Retro note
- **Write the run's machine-readable result before anything else.** The latency tool printed per-batch lines to stderr, so a crash in π0.5 would still have left ACT's and SmolVLA's numbers in the log, but not in `vla_latency.json`. Writing per-policy result files (as the simulator tool's per-cell files do) would make partial runs evidence too.
- **Pin every model the stack fetches.** That includes indirect ones like SmolVLM2's backbone.
