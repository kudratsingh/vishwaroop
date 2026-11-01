<!-- ironclad-policy v1.1.0 -->
# ADR-0002 — Autonomous iterative agents inside designated repositories; append-only records

**Date:** 2026-10-31 · **Status:** accepted · **Work order:** starter kit · **Program link:** PROGRAM §10–11

## Context
The reference starter kits (2026-10-30) forbade branches, PRs and any GitHub writes and required agents to stop after every completed work order. The owner's latest instructions (Oct 30, 2026) ask for autonomous, iterative development within the designated new repositories — branches, worktrees, PRs and merges under CI — with separate approval only for spending, hardware motion/flight, destructive operations, access changes, publication, existing-project changes, sealed-suite access, and scope/safety changes. The owner also ruled that no data, run, log or report is ever deleted or overwritten.

## Decision
1. Agents work autonomously within `AGENTS.md §2.1`; remote operations wait for a designated remote (`config/repo.json`); §2.3 gates require dated owner approvals recorded in `ledgers/approvals.jsonl`.
2. Ordinary PRs merge without human review when every required check is green on the exact candidate commit, acceptance criteria are met, conflicts are resolved, the change is inside authorization, and the branch is revalidated against `main` (`AGENTS.md §4.6`).
3. Agents continue to the next prerequisite-satisfied, in-scope work order without asking after every step.
4. `data/`, `runs/`, `ledgers/`, `reports/`, `artifacts/` and accepted work orders are append-only: enforced in CI by `tools/check_immutable.py` (pure-append rule for ledgers and reports; write-once for data and manifests; frozen accepted WOs) and in code by the `core` helpers (append-mode ledgers, content-addressed store without delete, exclusive-create run directories, write-once episode export). Corrections are new records.
5. Phases have exit tests frozen before work starts; status is an append-only ledger with a derived board.

## Alternatives considered
| Option | Why not |
|---|---|
| Keep "stop after every WO" | contradicts the owner's instruction; slows iteration without adding safety (gates already cover the risky actions) |
| Human review on every PR | the owner is one person; CI plus acceptance criteria plus independent review only on RL/evaluator WOs is the agreed balance |
| Soft "please don't delete" guidance | unenforceable; the owner considers silent deletion unacceptable |

## Consequences
Faster iteration; a complete, auditable trail; some friction (corrections are new records, not edits). CI must exist from the first commit.

## Reversibility
Any rule here can be tightened by editing `AGENTS.md` in both repositories through a program-level ADR; loosening the append-only rule is an owner decision.
