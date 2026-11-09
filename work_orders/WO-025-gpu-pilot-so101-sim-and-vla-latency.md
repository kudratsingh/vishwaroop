# WO-025 | GPU pilot: SO-101 simulator throughput and VLA inference latency (Mac baseline done; benchmark scope accepted; rental held)
**Phase:** M2a
**Exit tests advanced:** none. It measures the workloads the M2 twin, M5-early and the deferred workstation decision depend on.
**Size:** S
**Prerequisites:** WO-024 (CUDA-portable code; CUDA untested until this runs). **Owner approval of this text, with the ceiling, before any rental.**
**Authorization:**
- **First decision (owner, 2026-11-08, `approvals-20261108T132556755986Z-2add2fa0`, item 2):** "Revise the pilot plan first. I'm open to using the $50 ceiling for SO-101 simulator throughput and VLA inference latency. Send the exact workload, checkpoint, VM quote, and stop conditions for a fresh approval before I rent it."
- **Second decision (owner, 2026-11-08, `approvals-20261109T010005936999Z-5e60e401`):** "WO-025 — Run the $0 Mac baseline. Keep $10 as the proposed ceiling. Before I rent, make rendered SO-101 throughput a required workload and label any SO-100 timing as a reference. Bring back the pinned image, exact commands, CUDA and Vulkan smoke-test plan, and the steps needed to clear the paid-execution gate."
- **Third decision (owner, 2026-11-09, `approvals-20261109T022626042919Z-ee024835`):** "WO-025. Accept the benchmark scope and keep $10 as the proposed ceiling. Hold the rental. Bring the teardown question to ironclad and propose a verified shutdown mechanism compatible with me operating the pod. Also fix S3 to check the selected GPU's architecture. The RTX 5090 is compute capability 12.0, and both named fallbacks are 8.9."
- **Who runs the machine:** the owner rents, starts and stops it. The agent only connects over SSH.

**Files:**
- `src/vishwaroop/sim/so101_scene.py`, `config/so101-assets.json`
- `src/vishwaroop/models/wo025_sim_throughput.py`, `src/vishwaroop/models/wo025_vla_latency.py`
- `config/lerobot-requirements.{in,linux.txt,macos.txt}`, `scripts/setup_gpu_host.sh`
- `tests/`, `work_orders/`
- `reports/WO-025-gpu-pilot.md`
- the ignored `runs/`

**Supersedes, if the rental is approved:** WO-018's GPU plan (tokenizer training speedup). WO-018's Mac frame bundle stays as recorded. Its full M2a run is dropped along with the from-scratch generator (owner, item 1).

## Objective
Answer two questions with measurements, on the Mac and on one rented card:
1. **Simulator throughput.** How fast does ManiSkill3 step and render an **SO-101** scene on a GPU, compared with the Mac? This sizes the M2 twin's rollouts.
2. **VLA inference latency.** How long do ACT, SmolVLA and π0.5 take per decision, including batches of N candidates? Is that within the control budget, and what card class does that imply? This feeds M5-early's latency question and the workstation decision (owner item 6).

## Scope: the exact workload
**A. Simulator throughput** (`python -m vishwaroop.models.wo025_sim_throughput`).
- **A1, SO-101 (required).** Scene `VishwaroopSO101Throughput-v1` (`src/vishwaroop/sim/so101_scene.py`). Its contents:
  - the robot: TheRobotStudio's `so101_new_calib.urdf` (Apache-2.0) at commit `a758567c3978dfeefe282ede0500085a48fe8f78`, with the URDF and its 13 meshes pinned by sha256 in `config/so101-assets.json` (a mismatch refuses);
  - a 30 mm cube, an open bin, and two cameras: a fixed front camera and a wrist camera beside the jaws.
  - The drive gains are ManiSkill's SO-100 defaults. This is a throughput scene, not the calibrated twin.
  - The tool refuses to run without A1.
- **A2, SO-100 (reference only).** Upstream `PickCubeSO100-v1`, with one camera. Every output labels it `"reference"`, and the report never quotes it as SO-101 throughput.
- **Backends:** `physx_cuda` with GPU rendering on the card; `physx_cpu` with rendering through MoltenVK on the Mac.
- **Scale:** `num_envs` in {1, 64, 256, 1024} on the GPU, and 1 on the Mac.
- **Observations:** `state`; `rgb` at 128 × 128; `rgb` at 480 × 640 (the SO-101 cameras' raw size).
- **Timing:** each configuration runs in its own child process. Creation and reset, then a first step (timed separately), 50 warm-up steps, and 1,000 timed steps of pre-drawn random actions.
- **Reported:** control steps per second, environment steps per second, rendered camera frames per second, and peak memory (CUDA max allocated on the card; process max RSS on the Mac).
- **A failure** in one configuration, such as running out of memory at 1,024 environments with 480 × 640 cameras, is recorded as a result.

**B. VLA inference latency** (`python -m vishwaroop.models.wo025_vla_latency`).
- **Inputs:** synthetic, at the SO-101 shapes: two 480 × 640 RGB cameras and a 6-joint state. Batch N repeats one observation N times, as best-of-N candidates do.
- **Timing:** 20 warm-up calls, then 200 timed calls each at batch 1, 4 and 8. One call is `predict_action_chunk` on a batch already on the device, then a device sync.
- **Not timed:** the pre-processor (normalisation and tokenisation). Both VLAs pad the prompt to a fixed length, so the prompt is random token ids at that length.
  - This also avoids the PaliGemma tokenizer, which is gated: the owner's Hugging Face account has not accepted its terms (checked 2026-11-08).
- **Slow-call stop:** a first call slower than 10 s is recorded as a result, and larger batches are skipped.
- **Reported:** p50, p95 and max milliseconds per call and per action step; peak accelerator memory.

| Policy | Checkpoint | Size | Licence | Precision |
|---|---|---|---|---|
| ACT | LeRobot 0.6.1's default ACT config (ResNet-18 backbone, chunk 100), two 480 × 640 cameras, randomly initialised (torch seed 0). Latency does not depend on the weights, and no trained SO-101 ACT exists yet. | 51.6 M parameters | Apache-2.0 | fp32 |
| SmolVLA | `lerobot/smolvla_base` at `5e8d12a6e2975b0e5e5fce7c8caf47c371d257b6`; weights sha256 `7cd549ac…aaca01eb` (full value in the code) | 0.91 GB | Apache-2.0 | fp32 (its config sets no dtype) |
| π0.5 | `lerobot/pi05_base` at `22c30e5b34f9e7ab738b1b34fc2fc5ecfe2d28f0`; weights sha256 `0eb11ca9…16fca59b0f` | 14.47 GB | Gemma terms; used for latency only, nothing redistributed | bf16 |

- **Weight checks:** each checkpoint's weights are checked three ways before loading: the pinned sha256, the Hub's LFS id at the pinned revision, and the sha256 of the downloaded file. A mismatch refuses (stop condition 3). Loading is through safetensors only.
- **Environments:** two environments, because lerobot 0.6.1 needs torch below 2.12 while the simulator lock has torch 2.15.
  - A runs in the simulator lock (`config/robotics-requirements.linux.txt`).
  - B runs in `config/lerobot-requirements.linux.txt`: torch 2.11.0 with CUDA 13.0 wheels, so a host driver of 580 or newer. Both locks are hash-pinned.

## The Mac baseline ($0, done)
Measured on 2026-11-08 and 2026-11-09 on the owner's M3 Pro (36 GB). The results, runs and limits are in `reports/WO-025-gpu-pilot.md` §4.

## Pinned image and machine
| Item | Value |
|---|---|
| Provider, product | Runpod, on-demand Pod, secure cloud, one GPU |
| Card | **RTX 5090 32 GB**. Fallbacks, in order: L40S 48 GB, then RTX 6000 Ada 48 GB. |
| Image | `runpod/base:2.0.0-cuda1300-ubuntu2404@sha256:d06fb6b07bcf13cac6eab0218824129358101ef7d36abf98afbecacb4338c8b2` (Docker Hub, tag dated 2026-11-05; digest read 2026-11-08). Ubuntu 24.04 with Python 3.12, uv 0.13.4, git and openssh-server. It has no Vulkan loader. |
| CUDA floor | `minCudaVersion` 13.0 when the pod is created. Hosts with stock report CUDA 13.2 (read 2026-11-09). |
| Pod environment | `NVIDIA_DRIVER_CAPABILITIES=all`, so that the container runtime mounts NVIDIA's graphics libraries (`libGLX_nvidia.so.0`), which SAPIEN's Vulkan rendering needs. Whether Runpod honours it is the first smoke test. |
| Disk | 100 GB container disk; **no volume disk** and no network volume, so a stopped pod keeps no data (container-only, the teardown proposal's `disk_policy`). Needs, estimated: π0.5 14.5 GB, SmolVLA 1 GB, two environments about 15 GB, runs under 1 GB. |
| Access | TCP 22 exposed. The owner's SSH public key goes in the pod's `PUBLIC_KEY`. No GitHub token and no Hugging Face token on the pod (see "Code and credentials"). |

### Code and credentials
- **Nothing private on the pod.** Code arrives as a `git bundle` of the exact commit, copied with `scp`.
- **ironclad:** the pinned `ironclad-kit` v1.2.0 arrives as a wheel built on the Mac, with its sha256 recorded.
  - `scripts/setup_gpu_host.sh --ironclad-wheel PATH --ironclad-wheel-sha256 HASH` installs it from that wheel and checks the name's version and the hash (added in this work order, gate step G5). A test build on 2026-11-09 gave `ironclad_kit-1.2.0-py3-none-any.whl`, sha256 `41a2fe13…b30cfc16`; the approval binds the hash of the build made for the rental.
- **Checkpoints:** both are public at their pinned revisions and download without a token.

## Exact commands
`POD` stands for the SSH address the owner gives. `C` is the commit the owner approves, written into the approval line. Each step's output is saved under `runs/` on the pod and copied back.

**On the Mac, before rental ($0):**
```
git bundle create ~/wo025-$C.bundle $C
uv tool run --from pip --python 3.12 pip wheel --no-deps "ironclad-kit @ git+https://github.com/kudratsingh/ironclad@v1.2.0" -w ~/wo025-wheels
shasum -a 256 ~/wo025-wheels/*.whl
```

**On the pod, after the owner's go:**
```
# 1. Vulkan loader, inside the disposable container (root): the only system package step.
apt-get update && apt-get install -y --no-install-recommends libvulkan1 vulkan-tools

# 2. Code, from the bundle.
scp ~/wo025-$C.bundle ~/wo025-wheels/*.whl POD:/workspace/          # run on the Mac
cd /workspace && git clone wo025-$C.bundle vishwaroop && cd vishwaroop && git checkout $C

# 3. Read-only setup check (smoke S1 and S2 below).
scripts/setup_gpu_host.sh --check-only --ironclad-wheel /workspace/<wheel> --ironclad-wheel-sha256 <hash>

# 4. Simulator environment, GPU check and the M0 smoke episode (S3, S5).
scripts/setup_gpu_host.sh --venv /workspace/venv-sim --ironclad-wheel /workspace/<wheel> --ironclad-wheel-sha256 <hash>

# 5. SO-101 render smoke on the GPU (S4): 20 steps per configuration, SO-101 only.
export VK_ICD_FILENAMES=<the ICD the setup check names> PYTHONPATH=src
/workspace/venv-sim/bin/python -m vishwaroop.models.wo025_sim_throughput --backend cuda --scenes so101 --warmup 2 --steps 20

# 6. Workload A, in full.
/workspace/venv-sim/bin/python -m vishwaroop.models.wo025_sim_throughput --backend cuda

# 7. LeRobot environment for workload B (hash-pinned).
uv venv --python 3.12 /workspace/venv-lerobot
uv pip install --python /workspace/venv-lerobot/bin/python --require-hashes --no-deps -r config/lerobot-requirements.linux.txt
uv pip install --python /workspace/venv-lerobot/bin/python --no-deps /workspace/<wheel>

# 8. Workload B. S3 again in this environment: device.require("cuda") checks the card's capability against this build.
/workspace/venv-lerobot/bin/python -m vishwaroop.models.wo025_vla_latency --device cuda

# 9. Copy back (run on the Mac), then tell the owner the machine can be stopped.
scp -r POD:/workspace/vishwaroop/runs/<run ids> runs/
scp POD:/workspace/vishwaroop/ledgers/runs.jsonl ~/wo025-pod-runs.jsonl    # its new lines are appended here, never the file replaced
```

## CUDA and Vulkan smoke-test plan
These run first. The time box is 30 minutes (about $0.60 at $1.19/h), and every result is recorded.

| # | Check | Pass | On failure |
|---|---|---|---|
| S1 | `nvidia-smi`: card, driver and memory in use | RTX 5090 (or the named fallback); driver ≥ 580; under 500 MiB used | Stop condition 2. Tell the owner, who may replace the machine. |
| S2 | Vulkan: `vulkaninfo --summary`, and the setup check's ICD test (`nvidia_icd.json`, or `libGLX_nvidia.so.0` present) | An NVIDIA device listed, not `llvmpipe` | Stop condition 2. A runs only at `obs_mode=state`, and only if the owner agrees. B continues, since it needs no rendering. |
| S3 | torch CUDA in each environment, for the **card actually selected**. It checks `torch.cuda.is_available()`, reads `torch.cuda.get_device_capability(0)`, and checks the result against the expected value for the named card: 12.0 for the RTX 5090; 8.9 for the L40S and the RTX 6000 Ada (NVIDIA's compute-capability table). `device.require("cuda")` then refuses unless `torch.cuda.get_arch_list()` can run that capability: an `sm_XY` binary of the same major and an equal or lower minor (`sm_86` serves 8.9), or `compute_XY` PTX at or below it. A 12.0 card needs `sm_120` or PTX. The check finishes with a 4096 × 4096 bf16 matmul | The capability matches the named card, the build can run it, and the matmul is finite | Stop condition 2 for that environment. A card other than the one named is also a stop: the owner decides. |
| S4 | SAPIEN on the GPU: the command 5 smoke on SO-101, `physx_cuda`, 128 × 128 and 480 × 640 frames | Every SO-101 configuration measured, and the saved frame shapes match | GPU rendering failure: stop condition 2. One configuration out of memory: recorded, not a stop. |
| S5 | The M0 smoke episode on CPU physics (in `setup_gpu_host.sh`) | Recorded, validated and replayed | Recorded; it does not block A or B, which do not depend on M0 replay. |

## VM quote
From Runpod's `get-gpu-type` read on 2026-11-09 at 01:18 UTC: on-demand Pod, `minCudaVersion` 13.0, secure cloud. Stock is current only for that moment.

| Card | Memory | $/hour (secure) | $/hour (community) | Stock | Role |
|---|---|---|---|---|---|
| **RTX 5090** | 32 GB | **$1.19** | $0.69 | LOW, in EU-CZ-1, EU-RO-1 and EUR-NO-1 | **Proposed.** It is the consumer class a workstation would buy, it has graphics hardware for SAPIEN, and π0.5 in bf16 fits (estimated 7.2 GB of weights). |
| L40S | 48 GB | $1.09 | $0.79 | LOW, in EU-NL-1, EUR-IS-2, OC-AU-1, US-MO-1 and US-TX-4 | First fallback |
| RTX 6000 Ada | 48 GB | $0.99 | $0.74 | LOW, in US-WA-1 (read 2026-11-08, not re-read) | Second fallback |

- **Known risk:** Runpod Pods are containers, not VMs. The graphics mount (S2) is unverified until S2 runs.
- **Not quoted:** other providers.
- **Architecture differs by card.** The RTX 5090 is Blackwell (compute capability 12.0); both fallbacks are Ada (8.9).
  - torch's arch list is checked against the selected card (S3).
  - SAPIEN 3.0.3 on 12.0 is untested; S4 tests it. If S4 fails on the 5090, the fallback is an L40S on a new pod, which needs the owner's action (stop condition 5).

## Cost (estimated from the quote)
| Step | Hours |
|---|---|
| Smoke S1–S5 and both installs | 0.5 |
| A: 12 SO-101 and 12 SO-100 configurations | 0.75 |
| B: three policies, including π0.5's 14.5 GB download | 0.75 |
| Copy-back | 0.25 |
| **Total** | **2.25 h, about $2.70 at $1.19/h** |

- **Proposed ceiling:** **$10** of the $50 (owner, kept). About 8 hours at $1.19/h, including any stopped-disk storage.
- **Wall-clock stop:** 4 hours from the pod's start.

## Steps to clear the paid-execution gate
These are what the repository's rules require before the first paid minute. None of them is done by renting.

1. **G1. An owner approval line** (`ledgers/approvals.jsonl`, written from the owner's words, `AGENTS.md §2.5, §9.1`). It binds:
   - WO-025 and the commit `C`;
   - the card and its fallbacks, and one resource;
   - the $10 ceiling and the 4-hour wall stop;
   - an expiry.
2. **G2. Verified teardown with the owner operating the pod.**
   - **The owner's decision, 2026-11-09** (`approvals-20261109T022626042919Z-ee024835`): "Hold the rental. Bring the teardown question to ironclad and propose a verified shutdown mechanism compatible with me operating the pod."
   - **Why the rule blocks today.** `AGENTS.md §9.2` keeps paid execution blocked until the launcher's provider-teardown tests pass. ironclad 1.2.0 refuses every paid launch (`REAL_PROVIDER_LIFECYCLE_VERIFIED = False`).
   - **The proposal for ironclad:** `docs/program-drafts/ADR-NNNN-PROGRAM-verified-teardown-for-owner-operated-pods.md`.
     - The launcher attaches to the owner's pod and never creates or stops it.
     - The owner's own stop timer, set at creation, is the hard bound.
     - A Read Only Runpod key verifies `TERMINATED` (or a container-only `EXITED`), a bill that has stopped rising, and the reconciliation.
     - Fake-provider tests come first, then a real $1-class pilot with the owner operating.
   - **This step is met when** ironclad releases that mode with its pilot passed and this repository moves its pin, or when the owner decides otherwise in writing.
3. **G3. A fresh quote at creation.** The owner creates the pod only if the card's secure price is at most $1.19/h; for a fallback, at most $1.09 (L40S) or $0.99 (RTX 6000 Ada). The read time goes in the report.
4. **G4. Teardown verified and reconciled** (`AGENTS.md §9.3`). After the owner stops and terminates the pod:
   - the agent reads the pod's state with Runpod's read-only `get-pod` and `list-pod-billing`, and confirms that the pod is gone and nothing bills;
   - the agent appends reserved, completed and reconciled lines to `ledgers/costs.jsonl`, with the billed amount;
   - process exit is not pod shutdown.
5. **G5. Pre-rental preparation ($0, agent).**
   - The `--ironclad-wheel` option in `setup_gpu_host.sh`, with tests: **done**.
   - The bundle and wheel built from the approved commit.
   - This work order, the code and both locks merged.

## Stop conditions
1. **Ceiling:** $10 spent, or projected to be spent before the remaining steps finish. Stop and leave the machine for the owner to stop.
2. **A smoke test fails:** S1, S2, S3 or S4, as stated in the smoke-test table. Report it and wait for the owner.
3. **Checkpoint hash:** a checkpoint's sha256 does not match its pin or its revision's LFS id. That checkpoint is refused and not loaded.
4. **Wall clock:** four hours from the pod's start.
5. **Machine actions:** any need to start, stop, resize or replace the machine. That is the owner's action.
6. **Anything outside this text:** any result that would need a second machine, a token on the pod, or a paid resource not in this text.

## Out of scope
- Training of any kind.
- Any real-arm checkpoint: none has been exported yet.
- Any arm motion.
- A second machine.
- Anything beyond the ceiling.
- Accepting the Gemma terms, which is an owner action that latency does not need.

## Verification
- `make check`.
- The smoke-test outputs.
- One ledgered run per workload on each machine. Run directories and ledger lines are copied back.
- The report gives Mac and GPU numbers side by side, labelled **measured**, with SO-100 rows labelled **reference**.

## Exit criteria
Done when the report gives A and B on the Mac and on the rented card, and the reconciled cost. The report also says what the numbers imply for a local card. It makes no purchase recommendation beyond that implication.

## Report
`reports/WO-025-gpu-pilot.md`

## Progress (append-only)
- 2026-11-09: Mac baseline measured (runs/20261109T011733Z_52957e3e, runs/20261109T012123Z_5266661e; reports/WO-025-gpu-pilot.md). GPU half not run: waits for the owner's approval of this text, the gate route (G2) and the $10 ceiling.
- 2026-11-09: owner accepted the benchmark scope, kept $10 as the proposed ceiling and held the rental (approvals-20261109T022626042919Z-ee024835). S3 now checks the selected GPU's architecture (device.require refuses a build that cannot run the card's compute capability). Teardown proposal for ironclad: docs/program-drafts/ADR-NNNN-PROGRAM-verified-teardown-for-owner-operated-pods.md.
- 2026-11-09: held until teardown is validated and released (owner, approvals-20261109T031542703689Z-c8b6c471). Design and simulation: WO-027.
