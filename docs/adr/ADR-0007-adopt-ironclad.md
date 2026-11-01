# ADR-0007 — Adopt ironclad v1.1.0

**Date:** 2026-11-01 · **Status:** accepted · **Work order:** WO-011 · **Program link:** PROGRAM §5.3; program ADR-0004

## Context
Program ADR-0004 makes shared material a versioned dependency, `ironclad`. Its release notes ask each project to adopt it in a work order of its own and record the adoption in an ADR. The owner instructed this one on 2026-11-01, CI only, and accepted the `sync-policy` diff in writing (`ledgers/approvals.jsonl`).

## Decision
- **Pin:** `ironclad-kit @ git+https://github.com/kudratsingh/ironclad@v1.1.0`, installed commit `d5b91b6`. The name `ironclad` on PyPI is an unrelated project and is never installed.
- **CI credential:** the read-only deploy key the owner created, `IRONCLAD_DEPLOY_KEY`, loaded by a step in our own workflow with GitHub's published host key. The secret goes to no third-party action.
- **Removed:** `contracts/`, `tools/`, `src/vishwaroop/core/`, the four shared test files and the two old locks. Git history keeps them.
- **Also removed:** the root `SHA256SUMS.json`. The release notes do not list it, but the tool that wrote it is gone and a stale manifest reads as current. `ironclad verify` does the work of the old hash checks.
- **Simulator environment:** `ironclad-kit` requires Python 3.12 or newer, so the robotics environment moves from 3.11 to 3.12. WO-001 records that stack in its lock.

Old paths that stay in frozen, shared or historical text mean the following. They remain in the frozen `evals/M0-protocol.md`, `config/phases.json`, accepted work orders and reports, ledgers, the policy core, and `VERIFICATION.md`.

| Old path | Now |
|---|---|
| `contracts/v1/validate.py` | `ironclad-validate`, or `ironclad.contracts.v1.validate` |
| `contracts/v1/audit_splits.py` | `ironclad-audit-splits`, or `ironclad.contracts.v1.audit_splits` |
| `contracts/v1/writer.py` | `ironclad.contracts.v1.writer` |
| `tools/status_board.py` | `ironclad-status` |
| `tools/check_immutable.py` | `ironclad-check-immutable` |
| `tools/scan_secrets.py` | `ironclad-scan-secrets` |
| `tools/check_links.py` | `ironclad-check-links` |
| `tools/budget_preflight.py` | `ironclad-budget-preflight` |
| `tools/check_hashes.py`, the two hash locks | `ironclad verify` |
| `src/vishwaroop/core/` | `ironclad.core` |

Two ADRs now carry the number 0004: this project's `ADR-0004-m0-task-choice.md` and the program's `ADR-0004-PROGRAM-shared-dependency.md`. Neither is renamed. Frozen text means the first when it says ADR-0004 about the M0 task.

## Alternatives considered
| Option | Why not |
|---|---|
| `webfactory/ssh-agent`, the release notes' example | it would hand the secret to a third-party action; the notes allow a step of our own |
| Pin by full commit | the owner specified the tag, and `verify` accepts both. A tag can move, and the installed commit is on record here |
| Stay on Python 3.11 and ignore the package's `requires-python` | the contract imports there, as measured, but that runs a shared dependency on a Python it does not support. The same pins install on 3.12 |
| Keep `SHA256SUMS.json` as history | git already keeps it |

## Consequences
- CI depends on the deploy key and on `ironclad`'s availability.
- The contract's code changed in form only. No schema or fixture byte differs. `validate.py` now reads its schemas as package data and adds `ContractResourceError`, and `writer.py` and `audit_splits.py` differ only in their imports.
- The shared tests run through the plugin, against this repository.
- `docs/WORKFLOW.md` now describes a `cpu-tier` gate job. This repository's protection requires the matrix checks, which also works, so nothing changes here.
- Local simulator runs need `ironclad-kit` in the robotics environment. So will the owner-run GPU machine, which also needs read access to the private repository.

## Reversibility
A new pull request can restore the removed paths from the commit before this change, keeping every ledger and report line.
