# WO-008 — Fix three starter-kit tooling defects found during the rename review

**Status:** passed
**Date:** 2026-10-31 · **Author:** claude-code-vishwaroop · **Work order:** WO-008 · **Phase:** M0 (no exit test advanced) · **Protocol version:** not applicable
**Program link:** PROGRAM §10 → vishwaroop M0

> Every result below is **measured** unless marked otherwise. `VERIFICATION.md` holds the full table.

## 1. Claim and scope
The first-session steps work as written: the status tool accepts phase and exit-test events, real reports pass the tests, and a fresh `git add -A` keeps the secret scanner. This is about tooling only.

## 2. Frozen method
Copy the fixes byte for byte from `banshee`; author none of them. The expected results were written in WO-008.

## 3. Reproduction
```bash
make check
git check-ignore tools/scan_secrets.py   # must exit 1
```
The scratch-copy checks are listed in WO-008. Copied in commits `b42d391` and `d6e1460`, from `banshee` `95f7a34` and `da128e3`. Merged as `85027d4`.

## 4. Results
| Defect | Before, at `a8a58b1` | After |
|---|---|---|
| `.gitignore` also matched `tools/scan_secrets.py` | a fresh `git add -A` dropped it, and `make lint` checked 25 files | every manifest file tracked, and `make lint` checks 26 |
| `tools/status_board.py` with `--phase` and `--et` | refused, exit 2 | accepted, exit 0; naming both is refused, exit 2 |
| `test_no_fixture_claims_in_reports` | any `.md` report failed it | deleted; a real report passes |

CI passed on Python 3.12 and 3.13 on the merged commit, run 41247192471.

## 5. Failure analysis
The first copied fix, at `b42d391`, let `--phase` and `--et` combine and mark a phase `passed` without recording the exit test. An independent review reproduced this, and `banshee`'s `e412aea` fixed it. That fix was copied in `d6e1460`, before this repository pushed.

## 6. Cost and latency
None beyond the CI allowance.

## 7. Sealed access
None.

## 8. Exit tests and acceptance
No exit test closes here.

| Check | Expected | Result | Evidence | Pass? |
|---|---|---|---|---|
| `make check` on the merged commit | green | green | run 41247192471 | yes |
| `git check-ignore tools/scan_secrets.py` | exit 1 | exit 1 | `VERIFICATION.md` | yes |
| Phase and exit-test appends, scratch copy | accepted | accepted | `VERIFICATION.md` | yes |
| Real report in `reports/`, scratch copy | passes | passes | `VERIFICATION.md` | yes |

## 9. Limits
No test now checks reports for unbacked claims; `AGENTS.md §7` requires evidence by rule only. WO-010 later replaced this work order's `.gitignore`, so the ignore rule in force is the one WO-010 reports.

## 10. Next bounded work order
WO-001. Rollback: revert merge commit `85027d4`, because this work has no merge of its own.

## 11. Retro note
Review a copied fix as carefully as an authored one: the regression arrived in a byte-for-byte copy. Estimate S, actual S.

## Errata (append-only)
