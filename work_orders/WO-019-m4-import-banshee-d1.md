# WO-019 | M4: import banshee's D1 simulation episodes, read-only, and validate them
**Phase:** M4
**Exit tests advanced:** ET-M4-1
**Size:** S
**Prerequisites:** M1 passed (M4 needs only M1's infrastructure, `docs/PHASES.md`); the owner's answers to the questions below.
**Authorization:** owner instruction, 2026-11-02: "start M4 on banshee's D1 simulation logs (read-only exports)." Copying from banshee's `data/` needs the owner's answer to question 1. banshee stays read-only from here.
**Files:** `data/imports/` (ignored bytes), `ledgers/imports.jsonl`, `ledgers/licenses.jsonl`, `artifacts/manifests/`, `src/vishwaroop/data/`, `tests/`, `work_orders/`, `reports/WO-019-m4-import-banshee-d1.md`.

## Objective
Bring banshee's D1 software-in-the-loop episodes into vishwaroop through the shared contract, unchanged and hash-checked, so that M4's dynamics work has data. Every imported episode must validate as `contract_valid` (ET-M4-1).

## What exists in banshee (a read-only survey, 2026-11-02)
- **Episodes.** 473 episodes, on disk only and git-ignored.
  - `data/derived/d1/`: 82 nominal episodes (81 successes, 1 failed trial), 87 MB.
  - `data/derived/d1-faults/`: 391 fault and proxy-airframe episodes, 307 MB.
  - All are `partition: dev`, producer `banshee`, contract 1.0.0.
  - 406 ran on ROS 2 Jazzy and 67 on Humble.
- **Format.**
  - One state stream, 7 values in local ENU: position, velocity and yaw, from PX4's estimator.
  - The action is a velocity setpoint and a yaw rate.
  - 20 Hz. Nominal flights last about 48 s.
  - There is no attitude, body rate, IMU or motor data. ULogs hold those, but they are outside the contract (585 files, about 8 GB).
- **Validation.** The survey validated all 473 episodes as `contract_valid` (**measured**). It used banshee's pinned ironclad v1.1.0, whose schema and validator bytes equal our v1.2.0. That loaded code from banshee's environment, without writing anything. ET-M4-1 must rerun it with vishwaroop's own pin.
- **No export exists.** There is no `MANIFEST.json` or `COMPLETE` marker, and nothing is declared for vishwaroop. banshee's `docs/DATA_POLICY.md §4` says an importer refuses an export without them.
- **No license** is recorded for the episodes.
- **Not finished.** banshee is still adding episodes (latest 2026-11-02 12:17Z).
- **Thin for dynamics.** Only about 127 episodes change the physical dynamics: the x650 proxy, drag variants and a 4 kg payload. The nominal flights are one scripted route without wind. That limits ET-M4-2 (**inferred**).

## Scope
The plan below, once the owner answers.

### Plan
1. **Fix the export.** Fix the exact set: the run ids from banshee's `ledgers/runs.jsonl` and banshee's commit, with inclusion rules frozen before any data is read beyond hashes. Either banshee writes `MANIFEST.json` and `COMPLETE` in a banshee work order, or vishwaroop writes a consumer-side manifest from the declared hashes as a recorded deviation (question 2).
2. **Copy and check.** Hash every source file, copy into `data/imports/banshee-d1-<export id>/`, re-hash, and make the files read-only. Any mismatch stops the import.
3. **Validate.** Run vishwaroop's pinned `ironclad-validate` on every episode, and require 100% `contract_valid`.
4. **Record.** One `ledgers/imports.jsonl` line per export (hashes, producer, banshee commit, counts), and a `ledgers/licenses.jsonl` line.
5. **Report.** The manifest goes under `artifacts/manifests/`, then the report.

## Questions for the owner
1. **Authorization.** May vishwaroop read and copy files from banshee's `data/derived/d1*`? Reading `runs/` (the ULogs) is a separate yes or no.
2. **The export.** A banshee-side `MANIFEST.json` and `COMPLETE`, through a banshee work order in banshee's session, or a consumer-side manifest here as a recorded deviation from DATA_POLICY §4? I recommend the banshee-side export, because it keeps the producer authoritative.
3. **Which episodes.** All 473, or nominal plus the dynamics-changing faults only, and which stack (Jazzy, Humble or both)?
4. **License.** What terms apply? They are your own simulation data, so presumably owner-internal.
5. **Splits.** Who assigns train, dev and held-out for M4? ET-M4-2 needs held-out flights.
6. **ET-M4-2's numbers.** The 15% proposed default and the horizon (for example 0.5, 1 and 2 s) must be frozen before any M4 model result, ideally before the data is read beyond the import.

## Out of scope
Any model (that is the next work order); writing to banshee; ULogs unless question 1 says yes.

## Verification
`make check`; the import tool's hash checks; `ironclad-validate` output on every episode; negative tests for a changed byte, a missing file and an episode outside the frozen set.

## Exit criteria
Done when every selected episode is imported, hash-matched and `contract_valid`, with the import ledger lines. That closes ET-M4-1, so `AGENTS.md §13.8` asks for one review plus one recheck.

## Stop conditions
Any write to banshee; an import without the owner's answer to question 1; a hash mismatch; any invalid episode.

## Report
`reports/WO-019-m4-import-banshee-d1.md`
