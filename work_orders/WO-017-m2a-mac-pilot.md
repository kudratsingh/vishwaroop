# WO-017 | M2a observation model: a 30-minute Mac pilot to check the GPU estimate
**Phase:** M2a
**Exit tests advanced:** none
**Size:** XS
**Prerequisites:** M1 passed; WO-005's estimate.
**Authorization:** owner instruction, 2026-11-02: "run the 30-minute Mac pilot to confirm the estimate. No rental until the pilot gives a number." AGENTS §2.1 only, $0. CI only, per `AGENTS.md §13.8`: it closes no exit test.
**Files:** `src/vishwaroop/models/m2a_pilot.py`, `tests/test_m2a_pilot.py`, `work_orders/`, `docs/CONTEXT_AND_DECISIONS.md`, `reports/WO-017-m2a-mac-pilot.md`, ignored `runs/`.

## Objective
A measurement only; no M2a work order is opened. Replace the assumed training rate in WO-005's M2a estimate with a measured one. The assumed rate was 80 images per second for a ViT-S/14-shaped encoder at 224 × 224, on MPS.

## Scope
Render real simulator frames from scripted episodes on train seeds 6000 to 6019 (block 6, never simulated before). Then train a small tokenizer for 20 minutes on MPS: a ViT-S/14-shaped encoder (12 layers, width 384) with a per-patch pixel decoder, batch 32. Record images per second, memory and the loss curve, and redo the estimate's arithmetic with the measured rate.

The whole run stays under 30 minutes, so it is repeated if stopped, and resume is not needed. It is a measurement, not a model.

## Out of scope
Any M2a model, any rental, a decoder or dynamics model beyond the per-patch pixel head, multiple cameras.

## Verification
`make check`, then `python -m vishwaroop.models.m2a_pilot`. Expected: exit 0 and `m2a_pilot.json` with a measured rate.

## Exit criteria
Done when the report gives the measured rate and the redone estimate, labelled measured and estimated.

## Stop conditions
Any paid compute; a run projected over 30 minutes; memory pressure on the owner's Mac; disk below 5 GB free.

## Report
`reports/WO-017-m2a-mac-pilot.md`
