# WO-010 | Protect accepted work orders, widen the secret scan, restore the broad ignore rule
**Phase:** M0
**Exit tests advanced:** none; this must finish before WO-001.
**Size:** S
**Prerequisites:** none. Owner instructions dated 2026-10-31, recorded in `ledgers/approvals.jsonl`.
**Authorization:** AGENTS §2.1, on the owner's instruction. It does not authorize a merge, a purchase or any hardware action.
**Files:** `tools/status_board.py`, `tools/scan_secrets.py`, `tools/check_immutable.py`, `tests/test_tools.py`, `.gitignore`, `CHANGES.md`, `VERIFICATION.md`, `README.md`, `START_HERE.md`, `prompts/FIRST_SESSION.md`, `ledgers/approvals.jsonl`, `work_orders/`, `docs/STATUS_BOARD.md`, `SHA256SUMS.json`, `reports/WO-010-status-freeze-and-token-scan.md`.

Serves `PROGRAM §10`. In `banshee` this work is its WO-009; work-order numbers are per repository.

## Objective
Stop an accepted work order and its freeze from being reset, make the secret scan catch the tokens this program is most likely to hold, and close the gap the narrower ignore rules left.

## Source of the copied files
`banshee` commit `3a66e3c6a93436f3bd6673708715264d1e4781c8`, on its branch `wo/WO-006-program-rename`, which the owner named on 2026-10-31. The five files below compare equal to that commit's git objects. They first landed here from `1880773` and are unchanged since `26f0ce2`.

## Scope
Copied byte for byte, none of it authored here:
- `tools/status_board.py`: refuses a `created` event for a work order that already has a ledger record.
- `tools/check_immutable.py`: keeps the freeze once any `accepted` event exists, and rejects replacing a protected file with a symlink.
- `tools/scan_secrets.py`: adds Hugging Face and RunPod token patterns, and scans files with no extension.
- `.gitignore`: returns to `*secret*`, keeps `secrets/` and `.secrets*`, and keeps an exception for the scanner. The owner decided this, and `banshee` made the change first.
- `tests/test_tools.py`: tests for all of the above.

This work order also adds itself to the order before WO-001. Its own file was first named with `secret` in it, which the restored rule would have ignored, so it was renamed to use `token`.

## Out of scope
- Anything in `contracts/v1/`, `PROGRAM.md` or the `AGENTS.md` core.
- Copying any `banshee` record, including its `CHANGES.md`, `VERIFICATION.md`, `SHA256SUMS.json`, status files and work orders.
- Merging. The owner merges the pull request.

## Deliverables
The five copied files; an entry in `CHANGES.md` naming the source commit; a regenerated repository manifest; at acceptance, a report under `reports/`.

## Steps
1. Copy the five files from the source commit and compare them with its git objects.
2. Log them in `CHANGES.md`, record the results in `VERIFICATION.md`, regenerate the manifest, run `make check`, and commit.
3. At acceptance, write the report, then regenerate the manifest again, because a new file invalidates it.

## Verification
```bash
make check
make immutable BASE=main
python tools/check_hashes.py --verify-kit-manifest
git ls-files -ci --exclude-standard   # must print nothing
```
In a scratch copy, all of these must hold:
- A second `created` event for a work order is refused, exit 2.
- `git check-ignore` ignores `secret_prod.env`, `mysecret` and `secretkey`, and does not ignore `tools/scan_secrets.py`.
- `git init && git add -A` tracks every file in `SHA256SUMS.json`.

## Exit criteria
No exit test closes here. This WO is accepted when the checks are green on the merged commit and the report below exists.

## Stop conditions
A copied file would need editing to pass; a fix would touch a shared file; any need for another remote, a purchase or a hardware action.

## Report
`reports/WO-010-status-freeze-and-token-scan.md`, written at acceptance from `docs/REPORT_TEMPLATE.md` and citing `VERIFICATION.md` for the measurements. Pass that path to `--report`.
