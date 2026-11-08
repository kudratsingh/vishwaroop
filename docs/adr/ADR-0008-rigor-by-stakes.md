# ADR-0008 — Rigor by stakes: dry runs before freezes, a redesign after two failed pilots, ordinary CI for tooling

**Date:** 2026-11-08 · **Status:** accepted (owner, `approvals-20261108T132556755986Z-2add2fa0`, item 7) · **Work order:** none (process) · **Program link:** PROGRAM §10

## Context
By 2026-11-08 the repository had recorded 45 freeze events against 16 accepted work orders. ET-M3-1 alone took four frozen protocols, each failing at its pilot or score, all from one cause: a fixed camera that the arm occludes (`reports/WO-021-et-m3-1-protocol-4.md`, "Record across protocols"). No review named that cause before protocol 4. The owner put ET-M3-1 on hold on 2026-11-07 and, on 2026-11-08, adopted three process changes.

## Decision
`AGENTS.md §13.10`:
1. A new test rule gets a design note and a dry run on declared, disposable train-block seeds before any protocol carrying it is frozen. Dry-run seeds are spent and never reused by a frozen pilot or score.
2. After two failed frozen pilots or protocols for the same exit test, the next deliverable is a design rethink for the owner, not a further protocol revision.
3. Routine tooling that closes no exit test (importers, converters, portability, diagnostics) merges on the CPU tier like any ordinary PR. Independent review plus recheck (`§13.8`) and freezing before data (`§5.2`) remain required for exit tests, contract changes, and evaluator or RL integration.

## Alternatives considered
| Option | Why not |
|---|---|
| Keep the current practice | It spent four protocols on one design error that a dry run would have shown at protocol 1. |
| Drop freezes for simulation-only exit tests | Freezing before data is what makes a result credible; the owner kept it for exit tests. |
| Review everything twice | The extra reviews caught implementation bugs and missed the design error. |

## Consequences
- Exit tests take one extra step (the dry run) before a freeze, and fewer frozen protocols.
- Tooling work orders, starting with the real-episode importer and CUDA portability, merge on CI without a review round.
- The shared core of `AGENTS.md` (§1 to §12) is unchanged; this is a project rule in §13.

## Reversibility
The owner can revoke §13.10 by a dated instruction; a new ADR records it. No data or result depends on it.
