# WO-007 | Program-wide rename of this repository and package to vishwaroop
**Phase:** M0
**Exit tests advanced:** none; this is program housekeeping ahead of WO-001.
**Size:** S
**Prerequisites:** none. Owner decisions dated 2026-10-31, recorded in `ledgers/approvals.jsonl`.
**Authorization:** AGENTS §2.1, plus the §2.3 contract-change and §4.9 test-change approvals recorded in `ledgers/approvals.jsonl`. It does not authorize a remote, a purchase or any hardware action.
**Files:** `src/vishwaroop/` (moved from the old package directory), `pyproject.toml`, `tests/`, `tools/status_board.py`, `.gitignore`, `config/`, `contracts/v1/`, `PROGRAM.md`, `AGENTS.md`, `README.md`, `START_HERE.md`, `CHANGES.md`, `REQUIREMENTS_CHECKLIST.md`, `VERIFICATION.md`, `SHA256SUMS.json`, `docs/`, `prompts/`, `work_orders/`, `ledgers/approvals.jsonl`, `ledgers/corrections.jsonl`.

Serves `PROGRAM §5.2, §11, §14`.

## Objective
Apply the owner's name decision in this repository under ADR-0003, copying unchanged the shared files the `banshee` repository authored.

## Source of the shared files
`banshee` commit `95f7a343fed5ab7726bad9178f6778c530136675`, on its branch `wo/WO-006-program-rename`. The owner's instruction left the hash as a placeholder, `<FINAL HASH>`. This commit was chosen because at 09:19 UTC it was the head of that branch with a clean working tree, it is the only commit carrying the WO-008 tooling fixes, and all five hashes computed from the commit object match its ADR-0003 table. If the owner meant another commit, the copy is mechanical to repeat.

## First copy superseded
The first copy of the shared files was written at 09:03:41 UTC from `banshee`'s uncommitted working tree, and its bytes match `banshee` commit `e39c4c7`. The owner's message dates it 09:11 UTC, the time `banshee` recorded reading this working tree; there was only one copy. It was never committed here.

The owner held and replaced it because it was an earlier draft. Compared with the final bytes:
- The `AGENTS.md` core was policy version 1.0 with no Names paragraph. It is now policy version 1.1 with that paragraph.
- ADR-0003 had a three-row hash table and earlier wording. It now has the five-row table, the name meanings, and the owner's decision on the contract version.
- `PROGRAM.md`, the whole `contracts/v1/` tree and both lock files ended byte-identical to the first copy. `banshee` moved the contract to release 2.0.0 at `0ac1bd7` and restored 1.0.0 at `3c4614e`. Nothing from `0ac1bd7` was copied here.

## Scope
- Rename the package to `vishwaroop` and update packaging, tests, `config/phases.json`, the README, `START_HERE.md`, prompts and work orders.
- Copy these byte for byte from the source commit, without editing them: `PROGRAM.md`, `contracts/v1/` (whole tree), `config/contract-lock.json`, `config/program-lock.json`, `docs/adr/ADR-0003-PROGRAM-project-names.md`, and the `AGENTS.md` bytes before `## 13.`.
- Splice `AGENTS.md`: the `banshee` core plus this repository's own section 13, updated for the new package name.
- In a separate commit, copy the three WO-008 tooling fixes from the same source commit: `.gitignore`, `tools/status_board.py`, and the test files WO-008 lists, `tests/test_tools.py` and `tests/test_project_consistency.py`.
- Move the planned M0 task-choice ADR from ADR-0003 to ADR-0004.
- Regenerate the repository manifest. The manifest check would otherwise fail because files moved.

## Out of scope
- Any write to the `banshee` repository, which has its own session and work orders. It is read only, to take and compare the shared files.
- Merging to `main` before the owner has the hash confirmation.
- Any remote, purchase, hardware action or milestone work (WO-001 onward).
- Changing the contract's own name or its `urn:omni-world:...` schema ids (ADR-0003).

## Deliverables
The renamed package; the copied shared files; the copied tooling fixes; a regenerated repository manifest; approval and correction records; a post-rename section in `VERIFICATION.md`.

## Steps
1. Import the starter kit on `main` and record a green baseline `make check`.
2. Apply the rename on branch `wo/WO-007-program-rename`.
3. Copy the shared files from the source commit, then confirm the five hashes against its ADR-0003 table.
4. Regenerate the repository manifest last, then run the verification below.
5. Copy the tooling fixes in a separate commit, regenerate the manifest again, and repeat the verification.
6. Report the hash confirmation to the owner. Merge once the owner has it.
7. Owner action: replace the Claude Project copy of `PROGRAM.md` with version 1.1. Agents cannot do this from the repository.

## Verification
```bash
make check
make immutable BASE=main
python tools/check_hashes.py --verify-kit-manifest
python contracts/v1/validate.py contracts/v1/examples/imagined_arm/episode.json
python contracts/v1/audit_splits.py contracts/v1/examples/arm_sim/episode.json contracts/v1/examples/drone_sim/episode.json contracts/v1/examples/imagined_arm/episode.json
grep -rn "world""_model" . --exclude-dir=.git
```
Expected: the `grep` finds nothing and every other command exits 0. The repository `SHA256SUMS.json` is a point-in-time record: `make board` and any append to `work_orders/STATUS.jsonl` invalidate it, so verify it on a clean checkout of the commit under test. Negative test: a copy of `imagined_arm/episode.json` with this project's retired `producer` value must fail validation.

## Exit criteria
No exit test closes here. This WO is accepted when the checks are green on the merged commit and the five ADR-0003 hashes are confirmed equal in both repositories.

## Stop conditions
Any change beyond names and the copied fixes; a shared-file mismatch with `banshee` that copying cannot resolve; any need for a remote, purchase or hardware action.

## Report
`VERIFICATION.md`, section "Post-rename verification". A report under `reports/` can be written at acceptance, now that the copied WO-008 change has removed the test that blocked it.
