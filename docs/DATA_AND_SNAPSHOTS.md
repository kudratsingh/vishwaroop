# DATA_AND_SNAPSHOTS.md — collection, immutable exports, read-only import

Repository-wide record rules: `docs/DATA_POLICY.md`. This file is the arm-specific detail.

## 1. Teleoperation pilot (for M2b/M3 real data; owner runs the hardware)
Proposed default: one task, a small named object set, fixed front-camera mount, documented arm and camera calibration. Freeze a collection manifest first. Pilot: ~10 successful demonstrations plus ~10 safe autonomous/intervention episodes to measure recording reliability and diversity. Choose the next episode count from failure coverage and measured learning/evaluation curves, not by declaration. Do not stage hazardous physical failures; generate those in simulation.

## 2. What to collect besides successes
Evaluators need weak, confused and partially successful behaviour: successful teleop, autonomous successes, recoverable failures, interventions — each with cause and outcome. Distinguish a missed grasp, a slipped object, an unreachable target, a perception error and a timeout; they are different prediction and evaluation problems. The useful loop: model disagrees with reality → categorize → collect targeted data → update → re-evaluate on untouched cases. Build a failure-review interface before a polished imagination viewer.

## 3. Session controls
Reference photo and fiducial/calibration check at session start; new calibration id after any mount change. Record raw timestamps and arrival times, controller mode, camera exposure, configuration, action units and frames. A moved camera is a measured distribution change, not a hidden edit.

## 4. Snapshot publication protocol (future, owner-enabled, in the arm project)
The arm producer finishes a checkpoint and its sim evaluation in a temporary export directory, computes weights/config/preprocessor/result hashes, writes `MANIFEST.json`, atomically renames the directory into the export root, then writes `COMPLETE` last. Each snapshot identifies run family, seed, checkpoint, training dataset, base weights and evaluation protocol. Auto-export is **not installed by this kit** and is never an importer side effect; until the owner adds it, consume completed owner-provided snapshots only.

## 5. Import behaviour (`src/vishwaroop/importer.py`)
- No imports from the arm's training modules; no writes, locks, callbacks, signal handling, GPU allocation or background polling inside the arm repository or its export root.
- `verify_export(dir)` refuses without `COMPLETE`, without `MANIFEST.json`, on any hash mismatch, or on any path escaping the export directory.
- `register_import(dir, repo_root)` copies files under `data/imports/<export id>/` (write-once), records `ledgers/imports.jsonl` with every hash and producer identity, and marks the copy read-only.
- A snapshot is not a holdout merely because it is new. Split by run/family; quarantine designated test policies; never calibrate on their real outcomes.

## 6. Provenance rules
`real`, `physics_sim`, `imagined` remain distinct forever. Replaying imagined actions creates a **new** physics_sim episode linked to the imagined parent; executing them physically creates a **new** real episode. Evidence is appended to the validation ledger (`contracts/v1/validation_ledger.schema.json`); generated pixels never become physical observations. Raw logs are retained; training-ready exports carry hashes and transformation versions.
