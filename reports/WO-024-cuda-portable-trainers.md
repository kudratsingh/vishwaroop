# WO-024 — CUDA-portable trainers, with the Mac path unchanged

**Status:** passed on the Mac; **CUDA execution not run (untested)** · **Date:** 2026-11-08 · **Author:** claude-code-vishwaroop · **Work order:** WO-024 · **Phase:** M2a (tooling; no exit test) · **Protocol version:** none
**Program link:** PROGRAM §9 (rent before buying) → vishwaroop training code

> Four words with fixed meanings throughout this report: **measured** (ran here, evidence attached), **estimated** (arithmetic from stated assumptions), **mocked/fixture** (fabricated for tests), **not run**.

## 1. Claim and scope
Every training, scoring and planning entry point in scope now accepts `--device cuda`, through one device module (`src/vishwaroop/models/device.py`).

- **The Mac path is unchanged** (**measured**): the 99 torch tests that pass on `main` pass here too.
- **CUDA is untested.** The CUDA code is tested only with torch mocked (**mocked/fixture**). By the owner's instruction, CUDA execution is **not run** until it runs on a CUDA machine.

## 2. Frozen method
No exit test; this is tooling under `AGENTS.md §13.10`. The owner's words (`approvals-20261108T132556755986Z-2add2fa0`, item 4): "make the trainers CUDA-portable while preserving the Mac path. Report CUDA execution as untested until it runs on a CUDA machine."

## 3. Reproduction
- `make check`: the CPU tier, with no torch.
- `make torch-test`: new. It runs every test file that skips without torch, in the robotics environment (`~/.cache/vishwaroop-robotics/sim-venv`, torch 2.15.0, MPS).
- **Baseline:** the same pytest command on a detached checkout of `main` at `5cac298`, in the same environment.

## 4. Results
| Check | Result |
|---|---|
| Torch tests on `main` (baseline) | **measured:** 99 passed, 0 failed |
| Torch tests on this branch (`make torch-test`) | **measured:** 124 passed, 0 failed, 0 skipped: the same 99 plus 25 new device tests, including the MPS resume test |
| `make check` (CPU tier) | **measured:** passed; `tests/test_device.py` 24 passed, 1 skipped (the MPS test, no torch there) |
| Any run on a CUDA machine | **not run** |

What changed:

| Item | Change |
|---|---|
| `models/device.py` (new) | Defines the three devices and `add_device_argument`. `require` refuses a missing device and, on CUDA only, sets cuDNN to deterministic, turns benchmark off, enables deterministic algorithms (warn only) and sets `CUBLAS_WORKSPACE_CONFIG`. It also provides `sync` and `peak_tracker`, accelerator RNG save and restore, and `machine()`, which uses sysctl on macOS and `/proc` on Linux and records the CUDA device when present. |
| 11 entry points | `--device` via `add_device_argument`, with each default unchanged, and `require(args.device)` after parsing: `planning/suite.py` (cpu), `models/m1_confirm.py`, `m1_followups.py`, `family_sweep.py`, `cube_study.py`, `latent_predictor.py`, `m1_evaluate.py`, `m3_remeasure.py`, `m2a_pilot.py`, `scoring/score_branches.py`, `score_et5_retest.py` (all mps). |
| Resume | `cube_study` and `latent_predictor` checkpoints carry the accelerator's random-number state. `cube_study` had saved only the CPU state before, so its MPS resumes now restore MPS's generator too. Checkpoints without that state restore nothing extra. |
| `m2a_pilot` | Records the real machine identity on CUDA, instead of the placeholder `{"host": "gpu vm"}`. |
| `compute_pilot` | Its helpers delegate to the device module, so their importers become portable. |
| Kept Mac-only | `compute_pilot`: WO-012's Mac pilot, run under macOS `/usr/bin/time -l`, which needs MPS. `et_m3_6_score`, and `et_m3_6_train` (`DEVICE = "mps"`): the frozen ET-M3-6 arms were trained on MPS and must not be mixed across devices. A test fails if any other entry point gets its own device list. |

New tests:
- `add_device_argument` keeps defaults and refuses unknown devices.
- `cpu` never imports torch.
- `cuda` and `mps` are refused when absent.
- CUDA sets deterministic kernels; MPS leaves them alone.
- CUDA sync, peak memory and RNG go through the CUDA functions.
- `machine()` on Linux reads `/proc` and never asks sysctl, including when `/proc` files are missing.
- Every in-scope entry point accepts `cuda` with its old default; the Mac-only ones keep their lists.
- On MPS, a run resumed after 2 of 3 epochs equals an unbroken run, and the checkpoint holds `mps_rng`.

## 5. Failure analysis
Two failures appeared in the first `make torch-test`, both in the new test file:
- the Linux `machine()` test mocked every subprocess, which also caught `platform.platform()`'s own `uname` call on the Mac;
- the static scan counted `device.py` itself.

Both tests were corrected. No trainer behaviour was involved.

## 6. Cost and latency
$0. No GPU was rented or used.

## 7. Sealed access
None.

## 8. Acceptance gate by gate
| WO-024 exit criterion | State |
|---|---|
| Verification passes on the Mac | met (**measured**) |
| Report states CUDA execution is untested | this report, §1 and §4 |

## 9. Limits
- **Untested on CUDA hardware:** nothing here has run on a CUDA GPU, including CUDA determinism, bf16 autocast on CUDA, and the peak-memory figure.
- **Machine identity:** `machine()` on macOS now also records `cuda_available` (false). Earlier run records lack that key; no check compares machine dictionaries across runs.
- **Warn-only determinism:** `torch.use_deterministic_algorithms(True, warn_only=True)` warns rather than fails when an operation has no deterministic CUDA kernel. A CUDA run must report any such warnings.
- **No CUDA environment:** the repository does not yet pin a CUDA robotics environment. The first CUDA run needs a resolved lock (`config/stack-lock.*`) and an owner-approved machine.

## 10. Next work order
- The revised WO-018 pilot plan (owner item 2). It returns to the owner for a fresh approval before any rental, and it would be the first CUDA run.
- The storage check (owner item 5).

## 11. Retro note
Run the new test file under both environments before the first commit. The CPU tier skips torch-dependent paths, so a test that passes there can still fail where torch is present.
