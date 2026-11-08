# WO-023 | Real SO-101 episodes: LeRobot v3.0 export → contract v1, on fixtures first
**Phase:** M2b
**Exit tests advanced:** none (tooling; it feeds the M2 twin's calibration and validation data and M5-early's scorer)
**Size:** M
**Prerequisites:** the owner's approval of this work order (`approvals-20261108T132556755986Z-2add2fa0`, item 4); `src/vishwaroop/importer.py` (completed-export verification, WO-006's groundwork); contract `ironclad.contracts.v1` from the pinned ironclad-kit v1.2.0.
**Authorization:** AGENTS §2.1 only, $0. Owner, 2026-11-08: "Start with the real-episode importer on fixtures and use completed, hash-verified arm exports when available."
**Files:** `src/vishwaroop/data/so101_import.py`, `tests/test_so101_import.py`, `tests/lerobot_fixture.py`, `docs/SO101_EXPORT.md`, `requirements-dev.txt`, `pyproject.toml`, `work_orders/`, `reports/WO-023-so101-real-episode-importer.md`, and the ignored `data/imports/` and `data/derived/so101-real/`.

## Objective
Turn a completed, hash-verified export of real SO-101 recordings, in LeRobot's dataset format v3.0, into contract-v1 episodes this repository can train and evaluate on. Each episode keeps:
- joint state and commanded actions, with declared units;
- the camera streams, by reference to the recorded video, never re-encoded;
- an optional `reference_only` object-pose stream;
- session, policy-run and split identity.

Built and tested on fabricated fixtures now. It runs on real recordings only when a completed export exists.

## Scope
1. **Export shape** (`docs/SO101_EXPORT.md`). An export is a directory with `MANIFEST.json` and `COMPLETE`, verified by `importer.verify_export` (every file hashed, `COMPLETE` last). Its `identities.so101` block declares:
   - the LeRobot dataset root inside the export;
   - the joint and gripper units: one of `deg`, `rad`, `normalized_m100_100`, `normalized_0_100` per joint, with no default;
   - the calibration file;
   - the session of every episode;
   - policy origin (`teleop` or `trained`), with checkpoint, run and family ids when trained;
   - purpose (`demonstration` or `evaluation`);
   - optional per-episode outcome labels with their assessment file and method;
   - the optional object-pose feature name.

   Anything missing or unknown is refused, never guessed.
2. **A split declared before import.** A committed split file maps every session to `train` or `dev` and names the scene, session and policy-run groups. An episode whose session is not declared is refused. `sealed` is refused: sealed suites stay outside agent reach (§6.8, §13.3).
3. **Conversion.** Per episode, a write-once contract-v1 directory under `data/derived/so101-real/<export_id>/<episode_id>/`:
   - `environment_kind: real`, `producer: arm`, `simulator: null`, `embodiment_id: so101_real`;
   - `observation.state` becomes stream `state`, with the declared units;
   - each `observation.images.<camera>` becomes an `rgb` input stream;
   - the object pose becomes a `reference_only` stream;
   - `action` becomes `requested` only. Filtered, transmitted and applied stay `null`, because LeRobot does not record them.
   - Timestamps are LeRobot's nominal frame times (`frame_index / fps`) in a clock domain named for exactly that. Capture and receive times are those nominal times; true camera latency is unknown and is not invented.
   - The last step's next observation is marked invalid.
   - Outcome: `success` is set only when a label file is declared, with that file as the final assessment. Otherwise `success: null`.
4. **Video without re-encoding.** Each frame's artifact is the camera's MP4 shard, hard-linked into the episode directory. An adapter file (`lerobot-adapter.json`, the configuration's `preprocessing_artifact`) records, per camera:
   - the shard;
   - `from_timestamp` and `to_timestamp`;
   - fps, codec and resolution, from `meta/info.json`.

   Frames are not decoded here, so frame content is not checked beyond the shard's sha256. The report says so.
5. **Validation and audit.** Every episode passes `validate_episode`. The imported set passes `audit_splits`, with session, scene and policy-run groups. One `ledgers/imports.jsonl` line is written per export.
6. **Owner tool `seal`.** It writes `MANIFEST.json` and then `COMPLETE` for a finished LeRobot dataset directory the owner recorded, into an export root the owner names. It never edits the dataset. The owner runs it; agents run it only on fixtures.
7. **Dependency.** `pyarrow==26.0.0` (Apache-2.0, released 2026-10-09) reads LeRobot's Parquet files. No other new dependency: no LeRobot, no torch, no video decoder.

## Out of scope
- Any arm motion, recording, or connection to arm hardware. The owner records.
- Any change to the arm project (`vla-rl-so101`), and running its code.
- Decoding video frames, image preprocessing, checkpoint input-compatibility checks (the M2 twin's work order), and the scorer (M5-early).
- LeRobot formats other than v3.0, and Lance-backed datasets.
- CUDA portability (the next work order).

## Deliverables
- The importer and `seal`, with tests on fabricated LeRobot v3.0 fixtures.
- `docs/SO101_EXPORT.md`, the export shape for the owner's recordings.
- `reports/WO-023-so101-real-episode-importer.md`.

## Steps
1. Fixture builder: a fabricated LeRobot v3.0 tree (two sessions, three episodes, two cameras, an object-pose feature), with Parquet written by pyarrow and stand-in MP4 bytes marked as fixtures.
2. `seal`, `verify`, `import` and `audit` commands.
3. Negative tests (below).
4. `make check`.

## Verification
- `make check`.
- Positive: the fixture export seals, verifies, imports, validates and audits.
- Negative tests, each refused with a clear reason:
  - no `COMPLETE`;
  - a hash mismatch;
  - `codebase_version` other than `v3.0`;
  - undeclared units;
  - an unknown unit;
  - an episode whose session is missing from the split;
  - a `sealed` partition;
  - a trained policy without checkpoint, run or family ids;
  - a Parquet row count different from the episode's `length`;
  - non-monotonic frame indices;
  - a state vector of the wrong length;
  - a video key in the episodes table that is not in `info.json`;
  - a second import of the same export (write-once).
- The episode directories validate with `ironclad-validate`. The set passes `ironclad-audit-splits`.

## Exit criteria
Done when the importer passes on fixtures with every negative test, the export shape is documented for the owner, and the report is written.

Real recordings are imported only when a completed, hash-verified export exists. If one exists before acceptance, its import is reported as measured. Otherwise the report says "not run on real data".

## Stop conditions
- An export without `COMPLETE`, or with a hash mismatch: refuse and report. Never fix it.
- Any need to touch the arm project, arm hardware, or a sealed suite.
- A real requirement the contract cannot represent: write an ADR (§11.3) and stop. Do not fork semantics.

## Report
`reports/WO-023-so101-real-episode-importer.md`

## Progress (append-only)
- **2026-11-08, built and tested on fixtures; real data not run.** The report is `reports/WO-023-so101-real-episode-importer.md`.
  - `seal`, `verify` and `import` work on fabricated LeRobot v3.0 exports (**measured**, fixtures): 23 tests, including every negative test listed above; `ironclad-validate` and `ironclad-audit-splits` pass on the converted episodes.
  - A split leak is refused before anything is copied (`precheck_groups`), and a failed conversion keeps the read-only copy with a `conversion_failed` ledger line.
  - **Not run:** no real SO-101 export exists yet. Frames are not decoded.
