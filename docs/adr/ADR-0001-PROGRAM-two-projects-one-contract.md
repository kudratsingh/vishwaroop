<!-- ironclad-policy v1.2.0 -->
# ADR-0001 — Two independent projects, one versioned trajectory contract, no shared runtime

**Date:** 2026-10-31 · **Status:** accepted · **Work order:** starter kit · **Program link:** PROGRAM §5–6

## Context
The owner wants a general-purpose aerial autonomy platform (Omni Drone) and a learned world-model / planning / evaluation / synthetic-data platform (World Model & Planner). The sim-to-real gap for a drone is large, and the world model must serve a purpose beyond the drone (the arm project first). Two external reviews (Oct 30, 2026) agreed with the split and warned against any third project, shared runtime, or prerequisite that makes one project wait for the other.

## Decision
- Two repositories, developed in parallel by separate agents, each able to start immediately.
- Exactly one shared technical boundary: `contracts/v1/` (trajectory episode and transition schemas, append-only validation ledger schema, validator, split audit, reference writer, model-manifest template), vendored byte-identically in both repositories and pinned by hash.
- The arm project is a third producer through completed, immutable, owner-provided exports; it is never modified by either new project.
- World Model proposes and evaluates; Omni Drone owns command authority, estimation, mission execution and safety. The drone can always reject a proposal or run without the learned component.
- Governance text (`PROGRAM.md`, the shared `AGENTS.md` core) is also vendored identically, but it is documentation, not an interface.

## Alternatives considered
| Option | Why not |
|---|---|
| One monorepo | couples release cadence and agents; a drone crash or a GPU outage would stall the other track |
| Shared runtime service / database between the two | enterprise infrastructure without demonstrated need; creates a live dependency the reviews warned against |
| World model as a module inside the drone | loses the arm-first evaluator/data-engine purpose and the cross-embodiment research question |
| Rocket twin as world-model warm-up | another dependency rather than a shortcut (dropped Oct 30, 2026) |

## Consequences
Both repositories carry identical `contracts/v1` and `PROGRAM.md`; contract changes follow `AGENTS.md §11.3` (minor for additive, major with migration for breaking) and are adopted by both in the same week. Each repository has its own phases, exit tests, budget and status board.

## Reversibility
Merging the repositories later is a mechanical move; splitting a monorepo later would not have been. Low cost to reverse.
