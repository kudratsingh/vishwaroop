# WO-019 | M4: banshee's D1 simulation data imported read-only, revalidated and split-audited

**Date:** 2026-11-07 · **Exit test:** ET-M4-1 (`evals/M4-exit-tests.json`, amended by `evals/M4-amendment-1.json` and `evals/M4-amendment-2.json`) · **Result:** passed (**measured**, simulation data) · **Audit run:** `20261107T120856Z_a197b588` at clean `145a3bb` · **Artifact:** `artifacts/manifests/banshee-d1-import-v1.json`

## What was imported
banshee published four exports under its WO-029, each with `MANIFEST.json` and a `COMPLETE` marker. vishwaroop copied them byte for byte into `data/imports/<export_id>/` (ignored bytes), at clean `6aa3b38`. Each copy was re-verified file by file against the producer's manifest and made read-only. `ledgers/imports.jsonl` has one line per export and `ledgers/licenses.jsonl` one licence line (owner-private, all rights reserved).

| Export | Manifest sha256 | Files | Bytes | Episodes | Jazzy / Humble |
|---|---|---|---|---|---|
| `banshee-d1-sim-episodes` | `d7bc0545…11fc0` | 3,784 | 399,760,477 | 473 | 406 / 67 |
| `banshee-d1-sim-ulogs` | `9e8c1fb2…12f18` | 473 | 6,970,856,625 | 473 | 406 / 67 |
| `banshee-d1-variation-v1-episodes` | `383dfea0…14cfe` | 784 | 102,913,950 | 98 | 98 / 0 |
| `banshee-d1-variation-v1-ulogs` | `0b76d7b8…940c0` | 98 | 1,659,967,763 | 98 | 98 / 0 |

banshee was only read: no file was written there and none of its code ran. No consumer-side manifest was built.

## Checks before copying
All passed (**measured**). If any had failed, the import would have stopped before copying.
- **Completion:** each `COMPLETE` holds the sha256 of its `MANIFEST.json`, equal to the hash the owner was given.
- **Schema (amendment 1):** `contract.schema_version` is exactly `"1.0.0"` in all four manifests, with no conflicting declaration, and the JSON has no duplicate keys. Every `episode.json` declares `schema_version` `"1.0.0"`.
- **Files:** every listed file is present, with the listed size and sha256, and nothing unlisted is present.
- **Counts:** the counts by stack, by split and by success, computed here from the entries, equal the producer's. Every stack is Jazzy or Humble.
- **Episodes against ULogs:** each episode export and its ULog export list the same episodes, with the same run, stack, family, split, partition and success. Every episode has its ULog among the listed files.
- **Partitions (amendment 2):** `split.partition` is `train` for all 395 training-family episodes and `dev` for all 176 held-out-family episodes. The entry's `partition` equals it, and `scene_group_id` equals the producer's `family_id`, for all 571.

## Revalidation and split audit (run `20261107T120856Z_a197b588`)
| Check | Result |
|---|---|
| Pinned ironclad-kit 1.2.0 `validate_episode`, every episode of both exports | **571 / 571 `contract_valid`**, 0 invalid |
| Contract split audit (`audit_splits`) over both episode exports together | passed, session and policy-run groups |
| The same, with `scene_group_id` (the family) as a holdout axis | passed |
| ET-M4-2 (1): every episode_id once; no transitions sha256 in two families | passed |
| ET-M4-2 (2): every family in exactly one M4 partition, across both exports | passed |
| ET-M4-2 (3): exactly one training and one held-out partition | passed (`train`, `heldout`) |
| ET-M4-2 (4): action labels `[ve, vn, vu, yaw_rate]` and units; a 7-value `enu_local` state stream | passed |
| Family id ↔ (route, wind, fault) triple, one to one | passed, 43 families |
| Imported files re-hashed at audit time (episodes and ULogs) | all match |

**The M4 split across both exports** (from the manifests, which alone select M4 partitions):

| M4 partition | Families | Episodes | D1 / variation | Jazzy / Humble | Succeeded / failed |
|---|---|---|---|---|---|
| train | 33 | 395 | 319 / 76 | 350 / 45 | 351 / 44 |
| held-out | 10 | 176 | 154 / 22 | 154 / 22 | 148 / 28 |

Every completed failed flight is kept. Some held-out families are all failures: for example `wp-65dc8ff298|calm|V` (10 of 10) and `wp-748e2c871c|calm|G` (8 of 8). The artifact has per-family counts and a per-episode index with stack, family, M4 split, `split.partition` and success.

## Notes for the next M4 work order (not acted on here)
- **Frozen order.** ET-M4-2's window eligibility, nominal fit and scoring come next, in the order the freeze sets. Drone model training is a separate owner decision.
- **The stale-observation trips (reported by banshee, not checked here).** banshee's WO-029 report, as relayed by the owner, says all 12 failed variation flights and one incomplete attempt stopped at a stale-observation safety trip, which banshee has not explained. The contract check rejected the attempt because one of its 980 observations has a corrupt timestamp, and both variation exports (episodes and ULogs) exclude it. Here, each of the 12 failed flights' exported `outcome.json` shows `vm_returncode` 1, against 0 for the 86 successes, but no exported file names the trip. ET-M4-2's eligibility rules (fresh `capture_t_ns`, the cadence bounds) will exclude stale windows, and exclusions are reported by family.
- **Disk.** The import copied 9,133,498,815 bytes (8.5 GiB). Free space measured after the import was 18 GiB. No artifact records it.

## Review
An independent review of the import tool came before anything was copied. It found one blocker: `split.partition` was not `dev` for training families. That led to amendment 2, which the owner approved. It also found five should-fix items (resumability, the stack field, the artifact on failure, which checks gate, duplicate keys) and some nits. All were fixed before the import ran. A recheck of the results and this report follows (`AGENTS.md §13.8`).
