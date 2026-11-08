# WO-023 — Real SO-101 episodes: LeRobot v3.0 export → contract v1

**Status:** passed (tooling, on fixtures) · **Date:** 2026-11-08 · **Author:** claude-code-vishwaroop · **Work order:** WO-023 · **Phase:** M2b (tooling; no exit test) · **Protocol version:** none
**Program link:** PROGRAM §5.4 → vishwaroop M2 twin and M5-early

> Four words with fixed meanings throughout this report: **measured** (ran here, evidence attached), **estimated** (arithmetic from stated assumptions), **mocked/fixture** (fabricated for tests), **not run**.

## 1. Claim and scope
`src/vishwaroop/data/so101_import.py` turns a completed, sealed export of LeRobot v3.0 recordings into contract-v1 episodes. The owner seals recordings with its `seal` command (`docs/SO101_EXPORT.md`). The importer then verifies, copies write-once, converts, validates and audits.

- **Fixtures:** works, **measured**. 23 tests, plus a command-line run.
- **Real recordings:** **not run**. No export of the owner's arm exists yet.
- **Camera frames:** **not decoded**. Video is checked only by the shard's sha256. Decoding belongs to the M2 twin's input-compatibility work.

## 2. Frozen method
No exit test; this is tooling under `AGENTS.md §13.10` (ordinary CI). The rules it enforces:
- **Owner's words:** "Start with the real-episode importer on fixtures and use completed, hash-verified arm exports when available" (`approvals-20261108T132556755986Z-2add2fa0`, item 4).
- **AGENTS:** `§1.2` and `§13.4`, completed exports only; `§6.8` and `§13.3`, splits declared, no sealed data.
- **Contract:** `ironclad.contracts.v1` 1.0.0, unchanged.

## 3. Reproduction
- **Tests:** `make check` (CPU tier).
- **Command line, on a fixture:**

  ```bash
  python -m vishwaroop.data.so101_import seal --dataset <recording> --declaration <decl.json> \
    --extra calibration.json --extra rubric.json --export-id fixture-export-cli --out <exports>
  python -m vishwaroop.data.so101_import verify --export <exports>/fixture-export-cli
  python -m vishwaroop.data.so101_import import --export <exports>/fixture-export-cli \
    --split split.json --repo-root <scratch repo>
  ironclad-validate <episode.json>; ironclad-audit-splits <episode.json ...>
  ```

- **New dependency:** `pyarrow==26.0.0` (Apache-2.0, released 2026-10-09), pinned in `pyproject.toml` and `requirements-dev.txt`. It reads LeRobot's Parquet tables; nothing else was added.

## 4. Results
| Check | Result |
|---|---|
| Fixture tests (`tests/test_so101_import.py`) | **measured:** 23 passed |
| Command-line run on a fixture | **measured:** sealed, verified, and imported 3 episodes, 15 transitions; `ironclad-validate` contract_valid on all 3; `ironclad-audit-splits` passed; removing `COMPLETE` gives exit 2, `REFUSED` |
| `make check` | **measured:** passed |
| Real SO-101 export | **not run:** none exists |

The format was checked against a real public dataset. Column names and layout were read from `lerobot/svla_so101_pickplace`'s `meta/info.json` and `meta/episodes` Parquet on 2026-11-08, and the fixtures follow them.

Negative tests, each refused with a reason:
- missing `COMPLETE`;
- hash mismatch;
- a dataset file not hashed in the manifest;
- `codebase_version` other than v3.0;
- undeclared units, or an unknown unit;
- a session missing from the split;
- a `sealed` partition;
- a trained policy without its ids;
- sessions that don't match the episodes;
- a row count different from the episode's `length`;
- out-of-order `frame_index`;
- timestamps more than half a frame off `frame_index / fps` (a dropped-frame sign);
- a short state vector;
- a video key absent from `info.json`;
- one training run across train and dev (refused before anything is copied);
- a second import of the same export.

Two more tests cover failure handling:
- a failed conversion keeps the read-only copy and writes a `conversion_failed` ledger line;
- the CLI exits 2 on a refusal.

## 5. Failure analysis
- **Found while testing:** the first version copied the export before running the split audit. A leaking split was refused, but it left a copy behind that would block a corrected retry. The fix: `precheck_groups` applies the audit's group rule to the declaration before copying, and the contract audit still runs after conversion as a backstop.
- **Also corrected:** a clean-up step that restored write permission on failure would have loosened the hard-linked import copy. It was removed; the code relies on directory permission to unlink.

## 6. Cost and latency
$0. Local CPU only. No GPU, network, or paid resource in the importer or its tests.

## 7. Sealed access
None. The importer refuses a `sealed` partition.

## 8. Acceptance gate by gate
| WO-023 exit criterion | State |
|---|---|
| The importer passes on fixtures with every negative test | met (**measured**, fixtures) |
| Export shape documented for the owner | met (`docs/SO101_EXPORT.md`) |
| Report written | this file |
| Real export imported | **not run**; none exists. This is in scope, not a blocker. |

## 9. Limits
- **Frame-level checks:**
  - Frames are not decoded, so frame counts, resolution and codec inside each MP4 are taken from `meta/info.json`, not measured.
  - Hard links put whole shards in each episode directory. A shard holding many episodes is shared, not copied.
- **Timing:**
  - Times are LeRobot's nominal frame times. Camera and servo latency are unknown.
  - LeRobot records the requested action only, so the contract's filtered, transmitted and applied stages are `null`.
- **Unit bounds:** `action_spec` bounds are each unit's representation range, not the arm's joint limits.
- **Formats:** LeRobot v2.1, image-backed (non-video) cameras, and Lance-backed datasets are refused.

## 10. Next work order
- **CUDA portability of the trainers** (owner item 4, second). It is CUDA-untested until it runs on a CUDA machine.
- **First real import:** when the owner seals the teleop pilot. That run goes through `ledgered_run` at a clean commit, with its split file committed first.

## 11. Retro note
Pre-check every refusal that can be made before any write. A refusal raised after a write-once step leaves state that blocks the corrected retry.
