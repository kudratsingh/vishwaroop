# WO-007 — Program-wide rename of this repository and package to vishwaroop

**Status:** passed
**Date:** 2026-10-31 · **Author:** claude-code-vishwaroop · **Work order:** WO-007 · **Phase:** M0 (no exit test advanced) · **Protocol version:** not applicable
**Program link:** PROGRAM §5.2, §11, §14 → vishwaroop M0

> Every result below is **measured** unless marked otherwise. `VERIFICATION.md`, section "Post-rename verification", holds the full table.

## 1. Claim and scope
The repository and package are named `vishwaroop`, and the shared files match `banshee` byte for byte. This is a CPU-tier result on fabricated fixtures. It says nothing about any simulator, model or robot.

## 2. Frozen method
The owner's instructions of 2026-10-31 and ADR-0003: copy shared files from `banshee`, author none of them, and confirm five hashes against the ADR-0003 table. The expected results were written in WO-007 before the final copy.

## 3. Reproduction
```bash
make check
make immutable BASE=main
python tools/check_hashes.py --verify-kit-manifest
/usr/bin/grep -rn "world""_model" . --exclude-dir=.git
```
Source commit: `banshee` `3a66e3c6a93436f3bd6673708715264d1e4781c8`. Merged here as `85027d4864c14c6e862812576f812dc107da1e4e`, from pull request 1, head `405efa5`.

## 4. Results
| Item | Result |
|---|---|
| CI on head `405efa5`, runs 41194909627 and 41194913640 | success on Python 3.12 and 3.13 |
| CI on the merged commit `85027d4`, run 41247192471 | success on Python 3.12 and 3.13 |
| Five ADR-0003 hashes | 5 of 5 match |
| Shared files against `banshee` `3a66e3c` git objects | byte-identical |
| Old underscore package name outside `.git`, system `grep` | no hits |
| Retired `producer` values | 2 of 2 rejected, exit 2 |

The owner's own cross-repository check passed against `3a66e3c`.

## 5. Failure analysis
- The first copy came from a moving working tree, and the owner replaced it. WO-007 records what differed.
- A session-level `grep` wrapper and a clean clone each hid stale binary caches, so an early "no hits" claim was wrong for the working checkout. It was corrected.
- The scanner claim in `VERIFICATION.md` was wrong twice before an independent review corrected it.

## 6. Cost and latency
No purchase and no entry in `ledgers/costs.jsonl`. CI used the account's GitHub Actions allowance, which was **not run** as a check.

## 7. Sealed access
None.

## 8. Exit tests and acceptance
No exit test closes here. Acceptance rests on WO-007's exit criteria:

| Check | Expected | Result | Evidence | Pass? |
|---|---|---|---|---|
| Checks on the merged commit | green | green | run 41247192471 | yes |
| Five hashes in both repositories | equal | equal | ADR-0003 table; owner's check | yes |
| This report | exists | exists | this file | yes |

## 9. Limits
The Claude Project copy of `PROGRAM.md` was verified by the owner's assistant, not by an agent here. `PROGRAM.md §12` row 7 is out of date; fixing it needs a program change authored in `banshee`.

## 10. Next bounded work order
WO-001. Rollback: revert merge commit `85027d4`, together with the matching change in `banshee`, because the shared files must stay identical.

## 11. Retro note
Copy shared files only from a commit object, and check them against that commit's own hash table. State the final hash explicitly when two repositories wait on each other. Estimate S; actual was larger, because the source moved repeatedly.

## Errata (append-only)
