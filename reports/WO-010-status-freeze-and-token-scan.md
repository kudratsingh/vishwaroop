# WO-010 — Protect accepted work orders, widen the secret scan, restore the broad ignore rule

**Status:** passed
**Date:** 2026-10-31 · **Author:** claude-code-vishwaroop · **Work order:** WO-010 · **Phase:** M0 (no exit test advanced) · **Protocol version:** not applicable
**Program link:** PROGRAM §10 → vishwaroop M0

> Every result below is **measured** unless marked otherwise. `VERIFICATION.md` holds the full table.

## 1. Claim and scope
An accepted work order and its freeze cannot be reset, the scanner reads extensionless files and knows two more token formats, and names containing "secret" are ignored again. This is about tooling only. The scanner is a regular-expression guard, not proof that no credential is present.

## 2. Frozen method
Copy five files byte for byte from `banshee` `3a66e3c6a93436f3bd6673708715264d1e4781c8`; author none of them. Dry-run the copied ignore rule against this repository's own paths before adopting it.

## 3. Reproduction
```bash
make check
make immutable BASE=main
python tools/check_hashes.py --verify-kit-manifest
git ls-files -ci --exclude-standard   # must print nothing
```
The scratch-copy checks are listed in WO-010. Merged as `85027d4`.

## 4. Results
| Check | Result |
|---|---|
| The five files against `3a66e3c` git objects | byte-identical |
| `make check` | passed; 104 tests |
| Second `created` event for a work order, in a clone | refused, exit 2 |
| Scratch control removing a status line, append-only check | fails, exit 1 |
| `secret_prod.env`, `mysecret`, `secretkey`, `my_secret_key.txt`, `secret_config.py` | all ignored |
| `tools/scan_secrets.py` | not ignored |
| `git ls-files -ci --exclude-standard` | prints nothing |
| Fresh `git add -A` | tracks every manifest file |
| CI on the merged commit, run 41247192471 | success on Python 3.12 and 3.13 |

## 5. Failure analysis
With `*secret*` restored, this work order's own file, first named with `secret`, would have been left out of the commit while `make check` stayed green. A dry run caught it, and the file was renamed to use `token`.

## 6. Cost and latency
None beyond the CI allowance.

## 7. Sealed access
None.

## 8. Exit tests and acceptance
No exit test closes here.

| Check | Expected | Result | Evidence | Pass? |
|---|---|---|---|---|
| Checks on the merged commit | green | green | run 41247192471 | yes |
| Second `created` event | refused | refused, exit 2 | `VERIFICATION.md` | yes |
| Restored ignore rule | ignores the listed names, keeps the scanner | as expected | `VERIFICATION.md` | yes |
| Fresh `git add -A` | tracks every manifest file | as expected | `VERIFICATION.md` | yes |

## 9. Limits
Recorded in `VERIFICATION.md`:
- The broad rule silently ignores any new file with "secret" in its path.
- `prod.env` is neither ignored nor scanned.
- A git-ignored `.env` holding a recognizable credential turns `make check` red.
- The scanner does not catch a bare value with no recognizable pattern.

## 10. Next bounded work order
WO-001. Rollback: revert merge commit `85027d4`, because this work has no merge of its own.

## 11. Retro note
When adopting a copied ignore rule, test it against this repository's own paths; a green `make check` does not show that a new file was dropped. Estimate S, actual S.

## Errata (append-only)
