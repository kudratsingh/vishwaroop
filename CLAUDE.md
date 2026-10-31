# CLAUDE.md

All rules for this repository live in **`AGENTS.md`** (single authoritative policy). Read, in order: `PROGRAM.md` → `AGENTS.md` → `START_HERE.md` → the active work order. This file adds only Claude Code specifics.

- Run `make check` before every commit; it is the same CPU tier CI runs.
- Use the status ledger (`python tools/status_board.py --append ...`) at every work-order transition; regenerate the board with `make board`.
- Never run deletion or cleanup commands on `data/`, `runs/`, `ledgers/`, `reports/`, `artifacts/`, or any checkout you did not create (`AGENTS.md §1.3–1.4, §6`).
- Approvals (spending, hardware motion, destructive operations, sealed-suite access, remote designation) come from the owner in writing and are recorded in `ledgers/approvals.jsonl` before you rely on them (`AGENTS.md §2`).
- Subagents get their own worktrees and a declared file ownership list (`docs/WORKFLOW.md §3`).
- Label every result as measured, estimated, mocked/fixture, or not run (`AGENTS.md §7.2`).
