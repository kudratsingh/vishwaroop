# WO-011 | Adopt ironclad v1.1.0 and remove the vendored shared files
**Phase:** M0
**Exit tests advanced:** none; this is program housekeeping.
**Size:** M
**Prerequisites:** `ironclad` `v1.1.0` tagged; `IRONCLAD_DEPLOY_KEY` set by the owner in this repository (`ledgers/approvals.jsonl`).
**Authorization:** AGENTS §2.1, on the owner's instruction of 2026-11-01. The owner created the deploy key and accepted the `sync-policy` diff. No full review is needed, on the owner's instruction, although this touches the contract's location.
**Files:** `contracts/`, `tools/`, `src/vishwaroop/core/`, `src/vishwaroop/importer.py`, `src/vishwaroop/sim/`, `tests/`, `config/contract-lock.json`, `config/program-lock.json`, `SHA256SUMS.json`, `pyproject.toml`, `requirements-dev.txt`, `Makefile`, `.gitignore`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml`, policy copies written by `ironclad sync-policy`, `docs/`, `README.md`, `CLAUDE.md`, `CHANGES.md`, `VERIFICATION.md`, `REQUIREMENTS_CHECKLIST.md`, `data/README.md`, `reports/WO-011-adopt-ironclad.md`.

This follows `docs/releases/v1.0.0.md` and `v1.1.0.md` in `kudratsingh/ironclad`. WO-001 continues on its own branch, and merges this change when it lands.

## Objective
Move this repository onto the pinned `ironclad` release, so shared files have one source.

## Scope
1. Pin `ironclad-kit @ git+https://github.com/kudratsingh/ironclad@v1.1.0` in `requirements-dev.txt` and `pyproject.toml`.
2. Load the read-only deploy key in CI, in a step of our own.
3. Make the `Makefile` a wrapper for the installed commands.
4. Run `ironclad sync-policy --root .` and read the diff.
5. Remove the vendored copies the release lists, fix imports, and fix references in documents that are not frozen.
6. Record the adoption in ADR-0007.

## Out of scope
Changing any policy text, program ADR or frozen exit test; accepted work orders and reports, which keep their old paths; `PROGRAM.md §9` and `§12` row 7, which go to `ironclad`'s v1.2.0 text release; WO-001's own changes; using the launcher.

## Deliverables
The changes above, ADR-0007, and `reports/WO-011-adopt-ironclad.md`.

## Steps
1. Append `created`, `ready` and `in_progress`.
2. Make the changes, and check that the `sync-policy` diff is the one the owner accepted.
3. `make check`; open the pull request; merge on green; append `accepted`.

## Verification
```bash
make check
make immutable BASE=origin/main
```
Expected: both green. CI's first install through the deploy key is that key's first real test.

## Exit criteria
`make check` green, CI green on the merged commit, the adoption recorded.

## Stop conditions
A `sync-policy` diff other than the one the owner accepted; a schema or fixture byte differing from the vendored contract; CI failing to install through the key.

## Report
`reports/WO-011-adopt-ironclad.md`
