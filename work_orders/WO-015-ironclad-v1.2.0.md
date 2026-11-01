# WO-015 | Bump the ironclad pin to v1.2.0
**Phase:** M1
**Exit tests advanced:** none
**Size:** XS
**Prerequisites:** ironclad v1.2.0 released.
**Authorization:** owner instruction, 2026-11-01. AGENTS §2.1 only. CI only, per `AGENTS.md §13.8`: it closes no exit test and changes no contract byte.
**Files:** `pyproject.toml`, `requirements-dev.txt`, the policy copies `ironclad sync-policy` writes, `work_orders/`, `docs/STATUS_BOARD.md`, `reports/WO-015-ironclad-v1.2.0.md`.

## Objective
Move the CPU-tier pin from v1.1.0 to v1.2.0, take the policy text alignment, and confirm that the stored log no longer fails the secrets scan locally, since v1.2.0's scanner defaults to git-tracked files.

## Scope
The pin, `ironclad sync-policy --root .`, reading its diff (expected: `PROGRAM.md` 1.2, AGENTS core wording, program ADR-0007, `§13` untouched), `make check`, a PR, merge on green.

## Out of scope
The robotics environment. It stays on ironclad 1.1.0 as `config/stack-lock.resolved.v2.json` records, because a changed pin there is a new lock version and `record.py` ties episode provenance to that lock. Any change to `§13`, or to the stored log.

## Verification
`make check` in a clean worktree with v1.2.0 installed, and `ironclad-scan-secrets` plus the shared scan test in the checkout that holds the stored log. Expected: both pass. Negative: the scanner still finds a planted secret in a tracked file.

## Exit criteria
Closes no exit test. Done when the merge commit and CI run are reported.

## Stop conditions
A diff beyond the expected alignment; a change to `§13` or to a contract byte.

## Report
`reports/WO-015-ironclad-v1.2.0.md`
