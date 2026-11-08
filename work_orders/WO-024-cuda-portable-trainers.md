# WO-024 | CUDA-portable trainers, with the Mac path unchanged
**Phase:** M2a
**Exit tests advanced:** none (tooling; it lets later work orders run on a rented or local NVIDIA GPU once one is approved)
**Size:** M
**Prerequisites:** WO-023 accepted (owner, item 4: "Then make the trainers CUDA-portable while preserving the Mac path"); `approvals-20261108T132556755986Z-2add2fa0`.
**Authorization:** AGENTS §2.1 only, $0. Owner, 2026-11-08: "Report CUDA execution as untested until it runs on a CUDA machine." No GPU is rented or used by this work order.
**Files:** `src/vishwaroop/models/device.py` (new), the `--device` options and device helpers in `src/vishwaroop/models/`, `src/vishwaroop/planning/suite.py`, `src/vishwaroop/scoring/`, `tests/`, `Makefile`, `work_orders/`, `reports/WO-024-cuda-portable-trainers.md`.

## Objective
Every training, scoring and planning entry point accepts `--device cuda`. The device code (synchronisation, peak memory, machine identity, random-number state on resume, determinism settings) works the same on CUDA as on MPS and CPU. Mac results must not change: the Mac path stays byte-for-byte the same in behaviour.

## Scope
1. **One device module** (`models/device.py`):
   - `DEVICES = ("cpu", "mps", "cuda")`;
   - `add_device_argument(parser, default)`, keeping each entry point's current default;
   - `require(device)`: refuses a device this machine does not have, and on CUDA turns on the deterministic settings (cuDNN deterministic, no benchmark, deterministic algorithms, the cuBLAS workspace setting);
   - `sync`, `peak_tracker`, and `rng_state` / `set_rng_state` for the accelerator's generator;
   - `machine()`: no macOS-only command on Linux. It reads `/proc` there and records the CUDA device name, capability, memory, driver and CUDA version when present.
2. **Every `--device` option** goes through `add_device_argument`, with defaults unchanged. Eleven entry points: ten that had `choices=("mps", "cpu")` plus `m2a_pilot`, which already listed `cuda`. They are listed in the report.
3. **Resume on CUDA.** `latent_predictor` and `cube_study` save and restore the accelerator's random-number state (CUDA as well as MPS), so a resumed CUDA run continues the same stream (`AGENTS.md §13.9`).
4. **`compute_pilot` stays Mac-only.** It is WO-012's Mac measurement pilot: its parent runs each workload under macOS's `/usr/bin/time -l`, refuses without MPS, and plans around MPS weights. Its device helpers move to the device module, so the other entry points that import them become portable, but its own `--device` stays `mps` or `cpu`.
5. **`make torch-test`.** It runs the whole test suite in the robotics environment, which has torch, so the torch tests that the CPU tier skips run under a make target. It reports what was skipped.
6. **Kept MPS-only, by design.** `compute_pilot` (item 4), and ET-M3-6's trainer (`et_m3_6_train.DEVICE = "mps"`) and its scorer, which refuses arms trained on another device, stay MPS-only. The frozen ET-M3-6 arms were trained on MPS, and mixing devices would break the comparison.

## Out of scope
- Running anything on a CUDA machine. CUDA execution is reported **not run, untested**.
- Renting or buying a GPU.
- Changing any frozen protocol, threshold or result.
- Mixed-precision training changes, multi-GPU, and `torch.compile`.

## Deliverables
The device module, the edited entry points, tests, `make torch-test`, and the report.

## Verification
- `make check`: the CPU tier, with no torch.
- `make torch-test` on the Mac: every torch test that passed before still passes.
- Device-module tests with torch mocked:
  - `cuda` is refused when unavailable;
  - the CUDA determinism settings are applied;
  - CUDA peak memory and sync call the CUDA functions;
  - `machine()` on Linux reads `/proc` and never runs `sysctl`.
- A test that every entry point's `--device` accepts `cuda` (except `compute_pilot` and ET-M3-6's scorer) and keeps its old default.
- A resume test on CPU: a model trained 2 epochs, then resumed for 2 more, matches one trained 4 epochs straight. On MPS this runs under `make torch-test`.

## Exit criteria
Done when the verification passes on the Mac and the report states plainly that CUDA execution is untested.

## Stop conditions
- Any change in a Mac result: a torch test that passed before now fails, or a default changes.
- Any need for a GPU, a rental or spending.

## Report
`reports/WO-024-cuda-portable-trainers.md`

## Progress (append-only)
- **2026-11-08, done on the Mac; CUDA execution not run (untested).** The report is `reports/WO-024-cuda-portable-trainers.md`.
  - The device module and 11 portable entry points; `compute_pilot` and ET-M3-6's trainer and scorer stay Mac-only.
  - `make torch-test`: 124 passed (the 99 that pass on `main`, plus 25 new), MPS resume included (**measured**). CUDA paths are tested with torch mocked only.
