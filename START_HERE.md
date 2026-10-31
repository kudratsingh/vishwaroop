# START_HERE — World Model & Planner

**You are a coding agent starting a session in the `vishwaroop` repository. This page tells you what to read, what to run, and what to do first.**

## 1. Read (in this order, every session)
1. `PROGRAM.md` — where the whole program is going and why this project exists (§5.2, §6, §8).
2. `AGENTS.md` — the rules: authorization matrix (§2), workflow (§3–4), phases and exit tests (§5), append-only records (§6), evidence words (§7), stop conditions (§12), project addendum (§13).
3. `docs/STATUS_BOARD.md` — where the project is right now.
4. The active or next work order in `work_orders/`.
On a first session also read `docs/PHASES.md`, `docs/ARCHITECTURE.md`, `docs/CONTEXT_AND_DECISIONS.md`, `docs/EVALUATION_PROTOCOL.md`, `docs/DATA_AND_SNAPSHOTS.md`, `docs/ENVIRONMENT.md`.

## 2. Run (before touching anything)
```bash
python3 -m venv .venv && . .venv/bin/activate && python -m pip install -r requirements-dev.txt
make check && make board
git status   # if this is not yet a git repository: git init -b main && git add -A && git commit -m "Starter kit import"
```
`make check` must be green. If it is not, fixing it is the first task and gets its own PR.

## 3. Status today (2026-10-31)
- Phase M0 is `blocked`; every other phase is `not_started`. See `docs/STATUS_BOARD.md` for work-order states: WO-007 (the program-wide rename, ADR-0003), WO-008, WO-009 and WO-010 are `accepted`. WO-001 is `blocked` on its simulator steps, and its CPU-tier parts are done (`reports/BLOCKER-2026-10-31-m0.md`). Nothing has run on a simulator. Fixtures are fabricated.
- `config/repo.json`: the private remote `kudratsingh/vishwaroop` is designated (ADR-0005). No other remote may be added. `main` is protected, so changes reach it through pull requests.
- `config/budget.json`: $0 approved → no paid compute; the arm and coding-agent budgets are separate projects' and do not transfer.
- Hardware: the SO-101 is ordered, not confirmed arrived; it is not needed for M0/M1.

## 4. First work order
`work_orders/WO-001-m0-grounded-environment.md` is the first work order. Its CPU-tier parts are done; its simulator parts wait on the owner's decision in `reports/BLOCKER-2026-10-31-m0.md`. Then WO-003 (budget enforcement, local) can run in parallel in its own worktree. WO-002 follows WO-001.

## 5. Unresolved owner decisions you may hit
See `docs/CONTEXT_AND_DECISIONS.md §5` and `PROGRAM.md §12`: first ManiSkill3 task if no arm export exists (default: a readily available pick-and-place task, honestly labelled); GPU rental approval (none yet); sealed-data location. Take the recorded default, write the assumption into the report, and continue — stop only at `AGENTS.md §2.3` gates or §12 conditions.

## 6. Exact next actions
The next action on WO-001 is the owner's decision in `reports/BLOCKER-2026-10-31-m0.md`. WO-003 is not blocked and can proceed meanwhile. Merge on green checks, with a full review where `AGENTS.md §13.8` requires one.

1. `make check` green. Branch from `main`.
2. `evals/M0-exit-tests.json`, `evals/M0-protocol.md` and `evals/M1-exit-tests.json` are frozen, and their `frozen` events are appended. Phase M0 and WO-001 are `blocked`. Exit tests are frozen before `ready`, as `AGENTS.md §5.3` requires.
3. Outcome code, export, replay and negative tests are done, and tested on a fabricated fake. The real adapter in `src/vishwaroop/sim/env.py` has not run.
4. **Blocked:** the simulator needs a machine where it starts (`reports/BLOCKER-2026-10-31-m0.md`). Then resolve the stack lock, write the scripted baseline, export the first episode, replay, and run the negative tests.
5. Write `reports/WO-001-m0-grounded-environment.md`; append `accepted`; `make board`; continue to WO-002.

The first-session prompt the owner pastes into a fresh agent is `prompts/FIRST_SESSION.md`.
