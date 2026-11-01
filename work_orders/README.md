<!-- ironclad-policy v1.2.0 -->
# Work orders

A work order (WO) is the backlog item and the unit of agent work. Rules: `AGENTS.md §3, §5`. Procedure: `docs/WORKFLOW.md`.

## File format

`work_orders/WO-<nnn>-<slug>.md`, starting with this header block (a test parses it):

```
# WO-<nnn> | <title>
**Phase:** <phase id from config/phases.json>
**Exit tests advanced:** ET-<phase>-<n>, ...
**Size:** S | M | L
**Prerequisites:** <WO ids or phase states, each with how it is evidenced>
**Authorization:** AGENTS §2.1 only | needs §2.3 approval for: <item>
**Files:** <directories this WO may touch>
```

followed by sections: **Objective**, **Scope**, **Out of scope**, **Deliverables**, **Steps**, **Verification** (exact commands and expected results, including negative tests), **Exit criteria** (which ET ids this WO closes or advances and how), **Stop conditions**, **Report** (path).

## Lifecycle

`created → ready → in_progress → (blocked ↔ in_progress) → accepted | failed | superseded`

- Append every transition to `STATUS.jsonl` with `ironclad-status --append ...`.
- `accepted` requires: verification ran and is recorded in the report; CI green on the merged commit; status event with report path and commit.
- Once `accepted`, the WO file is **frozen** (append-only check enforces it). Follow-ups are new WOs.
- Numbering is global and never reused. Later WOs may be milestone-level stubs; they are expanded into full detail only when they become the next WO (`AGENTS §3.2`).

## Definition of ready / done

See `AGENTS.md §3.2–3.3`. A WO without frozen exit-test thresholds for the exit tests it claims to advance is not ready.

## Status board

`docs/STATUS_BOARD.md` is generated from `STATUS.jsonl` and `config/phases.json` (`make board`). Do not edit it by hand.
