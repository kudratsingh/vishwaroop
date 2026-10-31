# WO-009 | Designate the private GitHub remote and create the repository
**Phase:** M0
**Exit tests advanced:** none; this is repository setup ahead of WO-001.
**Size:** S
**Prerequisites:** owner request dated 2026-10-31, recorded in `ledgers/approvals.jsonl`.
**Authorization:** AGENTS §2.2, on the owner's request. It does not authorize public visibility, collaborators, secrets, tokens, spending, a purchase or any hardware action.
**Files:** `config/repo.json`, `docs/adr/ADR-0005-github-remote.md`, `ledgers/approvals.jsonl`, `work_orders/`, `docs/STATUS_BOARD.md`, `SHA256SUMS.json`, `reports/WO-009-designate-github-remote.md`.

Serves `PROGRAM §12` decision 7, for this repository only.

## Objective
Give this repository the private remote the owner asked for, following `docs/WORKFLOW.md §8`.

## Scope
Set `config/repo.json`; create `kudratsingh/vishwaroop` as a private repository; push `main`; request the protection `docs/WORKFLOW.md §8` describes; confirm the result by reading it back from GitHub.

## Out of scope
Pushing or merging `wo/WO-007-program-rename`, which stays local on the owner's instruction; public visibility; collaborators, secrets or tokens; any change to the `banshee` repository.

## Deliverables
The designated configuration, ADR-0005, the private repository, an approval record and a report.

## Steps
1. Record the owner's request, then set `config/repo.json`.
2. Merge to `main` after `make check` passes.
3. Create the repository and push `main`.
4. Wait for CI on the pushed commit, then request protection.
5. Read back visibility, default branch, CI results and protection.
6. Record acceptance on the rename branch, because this branch's `main` still has the test that blocks files under `reports/` until WO-008 merges.

## Verification
```bash
make check
gh repo view kudratsingh/vishwaroop --json visibility,defaultBranchRef
gh run list --repo kudratsingh/vishwaroop
gh api repos/kudratsingh/vishwaroop/branches/main/protection
```
Expected: `make check` exits 0, visibility is `PRIVATE`, the default branch is `main`, both CPU-tier jobs pass on the pushed commit, and protection reads back as requested.

## Exit criteria
No exit test closes here. Accepted when the verification above is recorded in the report.

## Stop conditions
The name is taken; the repository would not be private; a step would need spending or a permission change beyond this scope.

## Report
`reports/WO-009-designate-github-remote.md`, written at acceptance from `docs/REPORT_TEMPLATE.md`. Pass that path to `--report`.
