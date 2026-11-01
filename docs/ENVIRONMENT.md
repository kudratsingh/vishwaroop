# ENVIRONMENT.md — what runs where, bootstrap, and unresolved pins

## 1. Two environments, kept apart

| Environment | Purpose | Platform | Pinned by |
|---|---|---|---|
| **Tooling env** (this repository's `requirements-dev.txt`) | CPU-tier checks: lint, types, unit and contract tests, hash/secret/link checks, status board | any OS with Python ≥ 3.12 (tested: Python 3.13.18 on Linux at packaging time; the owner's Macs qualify) | `requirements-dev.txt` |
| **Robotics/ML env** | ManiSkill3 (SAPIEN), PyTorch + CUDA, the base VLA's dependencies, LeRobot for the real arm | **Linux + NVIDIA GPU only.** ManiSkill3's GPU simulation does not run on macOS. Today: a rented 4090/A40-class machine; later the owner's workstation (`PROGRAM.md §9`) | `config/stack-lock.resolved.json` (does not exist yet; WO-001 creates it) |

Never install the robotics stack into the tooling env or vice versa. Never force the tooling pins onto the robotics stack.

## 2. Bootstrap (tooling env)

```bash
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements-dev.txt
make check                      # the CPU tier; must be green before any work
make board                      # regenerate docs/STATUS_BOARD.md
```

`requirements-dev.txt` pins the private `ironclad-kit`. On a developer machine your normal GitHub login installs it, and CI uses the read-only deploy key. It requires Python 3.12 or newer.

## 3. Bootstrap (robotics/ML env)

**On the Mac, M0's platform of record (tested, `config/stack-lock.resolved.v2.json`):** Python 3.12, the versions in `config/robotics-requirements.macos.v2.txt`, and MoltenVK as in section 4. Keep them outside the repository and outside `/private/tmp`, which a restart wipes; `~/.cache/vishwaroop-robotics` is used here. Replay is claimed only on the same stack.

**On an owner-provided Linux GPU machine (proposed, not yet run on any machine):**

```bash
scripts/setup_gpu_host.sh --check-only   # read-only: what the machine has and lacks
scripts/setup_gpu_host.sh                # checks, pinned install, smoke episode
```

The script needs a clone of this repository on the machine, and the owner decides how it gets there. It checks the platform, the NVIDIA driver, an idle GPU, the Vulkan loader and ICD, disk space and an installer. It then installs `config/robotics-requirements.linux.txt` (every package hash-pinned, resolved from `config/robotics-requirements.in`) and records the driver, CUDA and versions it finds. It checks that torch can use the GPU and that GPU physics and rendering start, and fails if not. Finally it runs one episode on CPU physics through record, contract validation and frozen replay. Evidence goes to `runs/gpu-smoke-*/`. It never starts or stops a machine, installs system packages, uses `sudo`, resets a GPU or writes to `data/`, and it reminds you that the machine keeps running. If the image lacks `libvulkan.so.1` it stops and says so, and the owner picks an image that has it.

- Containers are preferred when the provider supports them; record the image digest in a new stack lock version.
- M1 does not need this machine: its exit tests run on the Mac (`reports/WO-012-m1-compute-split.md`). The 24 GB VRAM figure was an earlier assumption, and no M1 workload measured here needs a GPU.

## 4. What the Macs can and cannot do (owner's machines)
- Can: everything in the tooling env; LeRobot teleop/recording with the SO-101 (MPS for small policies); CAD, printing, docs.
- Cannot: ManiSkill3/SAPIEN GPU sim, Isaac Lab, VLA fine-tuning at useful speed. These rent until the workstation exists. Larger world-model training, such as the M2a observation model, has not been measured here.
- Can, measured: the M1 state-based predictor, latent model, chunk scorer, CEM planner and simulator branches, at under 1.5 GB peak on the M3 Pro (`reports/WO-012-m1-compute-split.md`).

**CPU physics on the Mac, measured on the owner's M3 Pro (`reports/BLOCKER-2026-10-31-m0.md`, last section):** `mani_skill` 3.0.1 and `sapien` 3.0.3 install on Python 3.12, and creating an environment fails only for lack of a Vulkan driver. With Khronos's MoltenVK v1.4.2 unpacked anywhere and `VK_ICD_FILENAMES` pointing at its `MoltenVK_icd.json`, ManiSkill3 runs state-only CPU physics at about 1,260 control steps per second. Nothing is installed system-wide. The robotics environment runs this package with `PYTHONPATH=src`. Rendering works through the same driver with `render_backend="cpu"`, and `src/vishwaroop/sim/inspect_episode.py` uses it for contact sheets. GPU simulation and large-scale visual data still need Linux and NVIDIA.

The simulator stays outside the tooling environment. To run a simulator command, set `VK_ICD_FILENAMES` and `PYTHONPATH=src`, and use the robotics environment's Python. The Vulkan loader prints its driver path on stdout, even with `MVK_CONFIG_LOG_LEVEL=0`, so save results through each command's `--out`, which `replay`, `negative_tests` and `inspect_episode` all have, and never store raw simulator stdout under `artifacts/`.

## 5. Stack lock discipline
- `config/stack-lock.pending.json` lists the pins that must be resolved. `null` is a blocker, not "use latest".
- WO-001 writes `config/stack-lock.resolved.json` with: OS image digest or distro+kernel, Python, CUDA, driver, `mani_skill` version/commit, `sapien` version, `torch` version, base VLA weights sha256 (when imported), tokenizer/preprocessor sha256, and the date. Mark each entry **tested** (ran here) or **proposed**.
- A changed pin is a new lock file version (`stack-lock.resolved.v2.json`); the old one stays for reproducibility of earlier reports.

## 6. Isolation
Own venv, own `runs/`, own ports, own process names; GPU memory checked before launch (`nvidia-smi --query-gpu=memory.used`), never reset. On a shared rental, record the instance id and ensure no other project's job is on it (`AGENTS.md §1.3`).

## 7. Unverified at packaging time (2026-10-31)
Current ManiSkill3/SAPIEN release numbers and Python support; PyTorch/CUDA pairing; Vulkan requirements on any rental image; LeRobot SO-101 driver status; base VLA family and its license. WO-001 resolves and records these with dates and evidence.
