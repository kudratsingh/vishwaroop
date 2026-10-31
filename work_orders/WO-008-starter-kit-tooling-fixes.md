# WO-008 | Fix three starter-kit tooling defects found during the rename review
**Phase:** M0
**Exit tests advanced:** none; these block WO-001.
**Size:** S
**Prerequisites:** none. Owner instruction dated 2026-10-31, recorded in `ledgers/approvals.jsonl`. The work sits on the WO-007 branch.
**Authorization:** AGENTS §2.1, plus the §4.9 test-change approval recorded in `ledgers/approvals.jsonl`. It does not authorize a remote, a purchase or any hardware action.
**Files:** `.gitignore`, `tools/status_board.py`, `tests/test_tools.py`, `tests/test_project_consistency.py`, `CHANGES.md`, `VERIFICATION.md`, `START_HERE.md`, `prompts/FIRST_SESSION.md`, `work_orders/`, `docs/STATUS_BOARD.md`, `SHA256SUMS.json`, `ledgers/approvals.jsonl`, `reports/WO-008-starter-kit-tooling-fixes.md`.

Serves `PROGRAM §10`.

## Objective
Make the first-session steps in `START_HERE.md` and `prompts/FIRST_SESSION.md` work as written. The defects came with the starter kit; the rename did not cause them.

## Scope
Copied byte for byte from `banshee` commit `da128e31307fd71351e787ac99c971d13d508fe9`, the final source the owner named. This repository authors none of these four files:
1. `.gitignore`: the kit's `*secret*` pattern also matched `tools/scan_secrets.py`, so `git add -A` dropped the scanner and `ruff` skipped it. The pattern is replaced by specific ones plus an exception for the scanner.
2. `tools/status_board.py`, with its tests in `tests/test_tools.py`: `--phase` and `--et` appends were always refused. They now work, and a record naming more than one id is refused.
3. `tests/test_project_consistency.py`: `test_no_fixture_claims_in_reports` failed on any `.md` report in `reports/`, so it blocked every real report. It is deleted.

The copies landed in commits `b42d391` and `d6e1460`. This work order also records them and puts WO-008 in the order before WO-001.

## Out of scope
- Anything in `contracts/v1/`, `PROGRAM.md` or the `AGENTS.md` core (WO-007).
- Copying any record from `banshee`, including its `CHANGES.md`, `VERIFICATION.md`, `SHA256SUMS.json`, status board, status ledger and work orders.
- Any other change to behaviour or checks, and any remote, purchase or hardware action.

## Deliverables
The copied fixes; an entry in `CHANGES.md`; updated start-of-work documents; a regenerated repository manifest; at acceptance, a report under `reports/`.

## Steps
1. Copy the four files from the source commit and compare them with its git objects.
2. Log the fixes in `CHANGES.md` and list what they cost in `VERIFICATION.md`.
3. Make WO-001 wait on WO-008 in its prerequisites, `START_HERE.md` and `prompts/FIRST_SESSION.md`.
4. Regenerate the repository manifest last, then run the verification below.
5. At acceptance, write the report, then regenerate the manifest again, because a new file invalidates it.

## Verification
```bash
make check
git check-ignore tools/scan_secrets.py   # must exit 1
```
In a scratch copy, all of these must hold:
- `python tools/status_board.py --append --phase M0 --event ready` and `--et ET-M0-3 --event frozen` are accepted.
- A call naming both `--phase` and `--et` is refused, exit 2.
- `git init && git add -A` tracks every file in `SHA256SUMS.json`.
- A real `.md` report in `reports/` passes `tests/test_project_consistency.py`.

## Exit criteria
No exit test closes here. This WO is accepted when the checks are green on the merged commit and the report below exists.

## Stop conditions
A fix would touch a shared file; a fix would weaken a check beyond what is listed in the scope; any need for a remote, purchase or hardware action.

## Report
`reports/WO-008-starter-kit-tooling-fixes.md`, written at acceptance from `docs/REPORT_TEMPLATE.md` and citing `VERIFICATION.md`, section "Post-rename verification", for the measurements. Pass that path to `--report`.
