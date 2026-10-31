# WO-009 — Designate the private GitHub remote and create the repository

**Status:** passed
**Date:** 2026-10-31 · **Author:** claude-code-vishwaroop · **Work order:** WO-009 · **Phase:** M0 (no exit test advanced) · **Protocol version:** not applicable
**Program link:** PROGRAM §12 decision 7, for this repository only

> Every result below is **measured** unless marked otherwise: read back from GitHub or run here on 2026-10-31.

## 1. Claim and scope
This repository has a private GitHub remote, `kudratsingh/vishwaroop`, with `main` pushed and protected. This says nothing about the simulator, models or hardware. It also says nothing about the rename branch `wo/WO-007-program-rename`, which stays local on the owner's instruction, so CI has **not run** on it.

## 2. Frozen method
The procedure in `docs/WORKFLOW.md §8` and `AGENTS.md §2.2`: record the owner's request, set `config/repo.json`, create the repository, push `main`, wait for CI, request protection, read everything back. The expected results were written in WO-009 before the repository existed.

## 3. Reproduction
```bash
gh repo view kudratsingh/vishwaroop --json visibility,defaultBranchRef
gh run view 41192093373 --repo kudratsingh/vishwaroop
gh api repos/kudratsingh/vishwaroop/branches/main/protection
git ls-remote --heads https://github.com/kudratsingh/vishwaroop.git
```
The pushed commit is `654bc0d`. Approval record: `approvals-20261031T101632175772Z-154b113e`.

## 4. Results
| Item | Result |
|---|---|
| Visibility | `PRIVATE` |
| Default branch | `main` |
| Branches on GitHub | `main` only |
| Collaborators | `kudratsingh` only |
| CI run 41192093373 on `654bc0d` | success: `cpu-tier (3.12)` and `cpu-tier (3.13)` passed; `sim-tier (manual)` skipped |
| Pull requests | required, with 0 approvals |
| Required checks | `cpu-tier (3.12)` and `cpu-tier (3.13)`, branch must be up to date |
| Administrators | included |
| Force-push and deletion | disallowed |

## 5. Failure analysis
None. The name was free and every step succeeded the first time.

`main` still holds the kit's old package name, because the rename has not merged. This is expected, and it is recorded in ADR-0005.

## 6. Cost and latency
No purchase and no entry in `ledgers/costs.jsonl`. CI on a private repository uses the account's GitHub Actions allowance. The allowance and its use were **not run** as a check. The CI run finished about 45 seconds after the push.

## 7. Sealed access
None.

## 8. Exit tests and acceptance
No exit test closes here. Acceptance rests on the expected results in WO-009:

| Check | Expected | Result | Evidence | Pass? |
|---|---|---|---|---|
| `make check` before the push | exit 0 | exit 0 | designation commit | yes |
| Visibility | `PRIVATE` | `PRIVATE` | `gh repo view` | yes |
| Default branch | `main` | `main` | `gh repo view` | yes |
| CPU tier on the pushed commit | both jobs pass | both passed | run 41192093373 | yes |
| Protection | reads back as requested | as requested | `gh api` | yes |

## 9. Limits
The account was inferred. The owner named the repository but not the account, and `kudratsingh` is the only account `gh` is logged in to; the approval record says so. Protection was read back, but a direct push to `main` was not attempted against it.

## 10. Next bounded work order
WO-007 and WO-008 merge once the owner approves pushing the rename branch and opening its pull request. WO-001 follows. Rollback: the owner can set `designated` back to `false` and delete or move the repository; deleting it is a §2.3 action for the owner.

## 11. Retro note
Designating on `main` while the rename branch was open forced a merge in the ledgers. It lost no lines, but the branch's lines moved after `main`'s. Designating before starting long-lived branches would avoid that. Estimate S, actual S.

## Errata (append-only)
