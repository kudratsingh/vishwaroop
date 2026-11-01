# WO-011 — Adopt ironclad v1.1.0

**Status:** passed
**Date:** 2026-11-01 · **Author:** claude-code-vishwaroop · **Work order:** WO-011 · **Phase:** M0 · **Protocol version:** none; no frozen file changes
**Program link:** PROGRAM §5.3; program ADR-0004

> Four words with fixed meanings throughout this report: **measured** (ran here, evidence attached), **estimated** (arithmetic from stated assumptions), **mocked/fixture** (fabricated for tests), **not run**.

## 1. Claim and scope
Shared files now come from the pinned `ironclad-kit` v1.1.0, and the vendored copies are gone. This is housekeeping: it says nothing about any milestone. The simulator tier is **not run** on this change.

## 2. Frozen method
The owner's instruction and the `ironclad` release notes. The owner set CI as the only review for this change (`ledgers/approvals.jsonl`).

## 3. Reproduction
```bash
python3.13 -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements-dev.txt
make check
make immutable BASE=origin/main
```
Pin: `ironclad-kit @ git+https://github.com/kudratsingh/ironclad@v1.1.0`, installed commit `d5b91b6`.

## 4. Results
All **measured**, on the owner's Mac with Python 3.13. CI on the merged commit is the status ledger's `accepted` record.
- `make check` passed, with `ironclad verify OK: v1.1.0`, and 334 tests passed, 2 skipped (simulator) and 1 deselected by the plugin.
- `ironclad-check-immutable` passed against `origin/main`.
- `sync-policy` changed 62 lines beyond the 11 marker lines and added `docs/adr/ADR-0004-PROGRAM-shared-dependency.md`: `docs/BUDGET_AND_LAUNCHER.md` 43 lines, `docs/WORKFLOW.md` 15, `docs/DATA_POLICY.md` 2, `work_orders/README.md` 2. The `AGENTS.md` core and `PROGRAM.md` changed by the marker only. The owner's first condition allowed markers only, so I stopped. The owner then accepted this diff in writing.
- Contract, vendored against package: no schema or fixture byte differs. `validate.py` reads its schemas as package data and adds `ContractResourceError`, and `writer.py`, `audit_splits.py` and the contract test differ in their imports. `SHA256SUMS.json` differs accordingly.

## 5. Failure analysis
None in this change. A Mac crash lost one uncommitted attempt, and I redid it from the branch.

## 6. Cost and latency
$0.

## 7. Sealed access
None.

## 8. Exit tests and acceptance
This work order closes no exit test.

## 9. Limits
- **The simulator commands on `main` need a new environment.** `ironclad-kit` requires Python 3.12, and the robotics environment was 3.11. The same pins install on 3.12 and import (**measured**), but no episode has run there yet, and the simulator tier is **not run** on this change. WO-001 does that next.
- WO-001's PR #5 predates this change, and adapts to it when it merges `main`.
- The owner-run GPU machine will need read access to the private repository.
- `config/phases.json` and `evals/M0-protocol.md` keep old paths, because exit-test text is frozen. ADR-0007 maps them.

## 10. Next bounded work order
WO-001, then WO-002. Rollback: a new pull request restores the removed paths from the commit before this change.

## 11. Retro note
- A stop rule written before seeing the release's own diff tripped on expected text. Stopping cost a round trip, and that was the right trade.
- Sizing: M, as estimated.

## Errata (append-only)
