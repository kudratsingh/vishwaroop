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

## 3. Bootstrap (robotics/ML env) — proposed, unverified

Resolved by WO-001. Proposed starting point (versions are **proposed, not tested** here; record the exact commits/digests you install):

- Ubuntu 22.04 or 24.04 with an NVIDIA driver supporting the CUDA build you pick; one GPU with ≥ 24 GB VRAM for M1.
- `uv venv --python 3.11` (ManiSkill3 has historically targeted 3.9–3.11; confirm against the pinned release) → `pip install mani_skill` at a pinned version, `torch` at the matching CUDA build, `jsonschema`.
- Headless rendering: SAPIEN's Vulkan backend needs the Vulkan loader and ICD on the box; verify with the ManiSkill demo before writing the adapter.
- Containers are preferred when the provider supports them; record the image digest in the stack lock.

## 4. What the Macs can and cannot do (owner's machines)
- Can: everything in the tooling env; LeRobot teleop/recording with the SO-101 (MPS for small policies); CAD, printing, docs.
- Cannot: ManiSkill3/SAPIEN GPU sim, Isaac Lab, VLA fine-tuning at useful speed, tier-1 world-model training. These rent until the workstation exists.

**CPU physics on the Mac, measured on the owner's M3 Pro (`reports/BLOCKER-2026-10-31-m0.md`, last section):** `mani_skill` 3.0.1 and `sapien` 3.0.3 install on Python 3.11, and creating an environment fails only for lack of a Vulkan driver. With Khronos's MoltenVK v1.4.2 unpacked anywhere and `VK_ICD_FILENAMES` pointing at its `MoltenVK_icd.json`, ManiSkill3 runs state-only CPU physics at about 1,260 control steps per second. Nothing is installed system-wide. The robotics environment runs this package with `PYTHONPATH=src`. GPU simulation and visual data still need Linux and NVIDIA.

## 5. Stack lock discipline
- `config/stack-lock.pending.json` lists the pins that must be resolved. `null` is a blocker, not "use latest".
- WO-001 writes `config/stack-lock.resolved.json` with: OS image digest or distro+kernel, Python, CUDA, driver, `mani_skill` version/commit, `sapien` version, `torch` version, base VLA weights sha256 (when imported), tokenizer/preprocessor sha256, and the date. Mark each entry **tested** (ran here) or **proposed**.
- A changed pin is a new lock file version (`stack-lock.resolved.v2.json`); the old one stays for reproducibility of earlier reports.

## 6. Isolation
Own venv, own `runs/`, own ports, own process names; GPU memory checked before launch (`nvidia-smi --query-gpu=memory.used`), never reset. On a shared rental, record the instance id and ensure no other project's job is on it (`AGENTS.md §1.3`).

## 7. Unverified at packaging time (2026-10-31)
Current ManiSkill3/SAPIEN release numbers and Python support; PyTorch/CUDA pairing; Vulkan requirements on the rental image; LeRobot SO-101 driver status; base VLA family and its license. WO-001 resolves and records these with dates and evidence.
