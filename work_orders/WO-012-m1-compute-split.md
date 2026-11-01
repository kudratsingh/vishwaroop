# WO-012 | Split M1 between the Mac and a GPU, from a measured pilot
**Phase:** M1
**Exit tests advanced:** none directly (decides where ET-M1-1 to ET-M1-5 run)
**Size:** S
**Prerequisites:** phase M0 `passed` (`work_orders/STATUS.jsonl`); `artifacts/manifests/m0-dataset-v1.json`.
**Authorization:** AGENTS §2.1 only. No paid compute, and the owner's Mac only.
**Files:** `src/vishwaroop/models/`, `tests/test_compute_pilot.py`, `work_orders/`, `docs/`, `START_HERE.md`, `README.md`, `artifacts/manifests/`, `reports/WO-012-m1-compute-split.md`, ignored `runs/`.

## Objective
Owner request, 2026-11-01: before a GPU machine is set up, measure whether the M1 predictor, planner and chunk scorer train acceptably on the M3 Pro (PyTorch MPS, 36 GB unified memory), with time per epoch and peak memory. List exactly which M1 exit tests need CUDA or GPU simulation, because only those go to a rented machine. If a GPU is needed, give an hours estimate.

Also from the same request: record that the episode bytes have one copy and that the owner is arranging a backup, and record the review rule from M1 on.

## Scope
A short pilot on the train partition; the split of WO-004 and WO-005; the documents that assume a GPU for M1.

## Out of scope
Any exit-test result, dev data, the WO-004 and WO-005 models themselves, changing a frozen threshold, a backup of the episode bytes, `PROGRAM.md`.

## Deliverables
`src/vishwaroop/models/compute_pilot.py`, `src/vishwaroop/models/pilot_data.py`, `artifacts/manifests/m1-mac-pilot-v1.json`, WO-004 and WO-005 updated, and the report.

## Steps
1. Train on `train` only, with every workload in its own process under `/usr/bin/time -l`.
2. Measure the predictor, the latent model, the scorer, CEM decisions, closed-loop steps, simulator branches, rendering and encoder throughput.
3. Decide the split from those numbers and write it into WO-004 and WO-005.
4. Record the data and review notes.

## Verification
`make check`, then `python -m vishwaroop.models.compute_pilot --manifest artifacts/manifests/m0-dataset-v1.json` in the robotics environment. Expected: exit 0, `pilot.json` in a new run directory, a clean tree at the recorded commit. Negative tests: `tests/test_compute_pilot.py` refuses a dev seed labelled train, changed transitions and a manifest with no train episodes.

## Exit criteria
Closes no exit test. Done when the report lists, for each M1 exit test, where it runs and why, with the measured numbers behind that.

## Stop conditions
Any need for dev or sealed data, or for paid compute; memory pressure on the owner's machine; disk below 5 GB free.

## Report
`reports/WO-012-m1-compute-split.md`
