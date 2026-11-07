# WO-021 | M3: protocol, scene engine and the scene-consistency check (ET-M3-1)
**Phase:** M3
**Exit tests advanced:** ET-M3-1
**Size:** M
**Prerequisites:** WO-020 accepted; the owner's acceptance of D1 to D8 (2026-11-06).
**Authorization:** AGENTS §2.1 only. The Mac, $0. Owner, 2026-11-06: "Continue with the M3 scene engine on the Mac at $0. Freeze the missed-grasp held-out-family test before generating operator data."
**Files:** `evals/M3-protocol.md`, `evals/M3-exit-tests.json`, `evals/M3-checker-tolerances.json`, `config/phases.json`, `docs/PHASES.md`, `src/vishwaroop/synth/`, `tests/`, `artifacts/manifests/`, `work_orders/`, `reports/WO-021-m3-protocol-and-scene-engine.md`, ignored `runs/` and `data/derived/`.

## Objective
Freeze M3's protocol and exit tests before any M3 data exists: seed blocks 10 to 19, the leak rules, ET-M3-1's details and the held-out-family test ET-M3-6 with `missed-grasp` as its target. Then build the scene engine and close ET-M3-1. The engine covers scene snapshots, the reproducibility gate, the operators, the consistency checker and the mismatch injector.

## Scope
1. Freeze `evals/M3-protocol.md` and `evals/M3-exit-tests.json`, with their sha256 in the status ledger, before any scene is created.
2. Build `src/vishwaroop/synth/`: M3 seed partitions; snapshots; renders; the two operators; the injector; the checker.
3. Run the tolerance pilot on block 10 seeds 10900 to 10919. Write `evals/M3-checker-tolerances.json` from it by the frozen rule, and record its sha256 in the status ledger.
4. Generate the 60 controls and 60 injections, run the checker once, and report ET-M3-1.

## Out of scope
F2's operator data for ET-M3-6, the evaluation family's recording, any training, any generator, and any GPU work (D4). Those come in the next work order.

## Verification
`make check`, then the engine's commands at clean commits. Negative tests: each injection type on fabricated frames; a refused second scoring; a seed in a reserved or dev block refused for training.

## Exit criteria
Done when ET-M3-1 is reported as passed or failed under the frozen rule. It closes an exit test, so `AGENTS.md §13.8` asks for one review plus one recheck.

## Stop conditions
A pilot that cannot fit a band inside the frozen limits (the owner is told); any need for blocks 0 to 9 or 18 to 19; any GPU or paid work.

## Report
`reports/WO-021-m3-protocol-and-scene-engine.md`
