# WO-015 — Bump the ironclad pin to v1.2.0

**Status:** passed
**Date:** 2026-11-01 · **Author:** claude-code-vishwaroop · **Work order:** WO-015 · **Phase:** M1 · **Protocol version:** none; no frozen file changes
**Program link:** PROGRAM §5.3; program ADR-0007

> Four words with fixed meanings throughout this report: **measured** (ran here, evidence attached), **estimated** (arithmetic from stated assumptions), **mocked/fixture** (fabricated for tests), **not run**.

## 1. Claim and scope
The CPU-tier pin is now `ironclad-kit` v1.2.0, with its policy text taken, and the stored log no longer fails the secrets scan locally. This is housekeeping: it says nothing about any milestone. The simulator tier is **not run** on this change.

## 2. Frozen method
The owner's instruction of 2026-11-01. CI only, under `AGENTS.md §13.8`.

## 3. Reproduction
```bash
python3.13 -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements-dev.txt
ironclad sync-policy --root . --check
make check
make immutable BASE=origin/main
```
Pin: `ironclad-kit @ git+https://github.com/kudratsingh/ironclad@v1.2.0`, installed commit `f6af7d4`.

## 4. Results
All **measured**, on the owner's Mac with Python 3.13. CI on the merged commit is the status ledger's `accepted` record.
- `make check` passed in a clean worktree, with `ironclad verify OK: v1.2.0`, and 589 tests passed, 8 skipped (simulator and torch) and 1 deselected by the plugin.
- `ironclad-check-immutable` passed against `origin/main`.
- **The diff is the expected alignment.** `AGENTS.md`: line 3 and the core's tool paths, policy version 1.2. `PROGRAM.md`: version 1.2, the header, `§6`, `§9`, `§10`, `§12` row 7, `§14`. ADR-0004: the pin form and an amendment. ADR-0007 is new. The other eight policy files change only their marker line. `§13` has the same sha256 before and after, `7c37c3b6…`. The contract's `schema_version` stays 1.0.0.
- **The stored log clears.** In the checkout that holds it, `ironclad-scan-secrets` from v1.2.0 passes, and so does the shared test `test_repository_has_no_secrets_or_machine_paths`, which failed there under v1.1.0. The log stays in place, and git ignores it. That checkout is on another branch, so the rest of `make check` did not run there.
- **The scanner still works.** A fake AWS key planted in a tracked file was reported, and then removed.

## 5. Failure analysis
Two tests in `tests/test_setup_gpu_host.py` hardcoded `v1.1.0`, although the script reads its pin from `requirements-dev.txt`. They now read the same line, so they check the same thing and the next bump will not break them.

## 6. Cost and latency
$0.

## 7. Sealed access
None.

## 8. Exit tests and acceptance
This work order closes no exit test.

## 9. Limits
- **Two versions on purpose.** The robotics environment stays on 1.1.0, commit `d5b91b6`, as `config/stack-lock.resolved.v2.json` records. A changed pin there is a new lock version, and episode provenance is tied to that lock. No schema or fixture byte changed in this release, so the difference does not affect episode validity. A later work order can move it with a lock v3.
- **What the scan now skips.** By default it reads tracked files and untracked files that are not ignored, so it skips ignored files only, which is what clears the log. `ironclad-scan-secrets --all` is still the full walk, and it still reports the log.

## 10. Appendix
`AGENTS.md`'s `§13.9` resume rule, from WO-014, is not in this change.
