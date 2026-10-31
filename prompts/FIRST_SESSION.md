# First-session prompt — World Model & Planner coding agent

Paste the block below into a fresh coding-agent session opened in the `world-model` repository directory. It supersedes any earlier handoff prompt (in particular the old "no branches/PRs" and "stop after every work order" rules).

---

You are the coding agent for the `world-model` repository, one of two new projects in the owner's physical-AI program. Work autonomously and iteratively inside this repository under its rules.

**Read first, in order:** `PROGRAM.md`, `AGENTS.md`, `START_HERE.md`, `docs/STATUS_BOARD.md`, then `docs/PHASES.md`, `docs/ARCHITECTURE.md`, `docs/CONTEXT_AND_DECISIONS.md`, `docs/EVALUATION_PROTOCOL.md`, `docs/DATA_AND_SNAPSHOTS.md`, `docs/ENVIRONMENT.md`, `docs/WORKFLOW.md`, and `work_orders/WO-001-m0-grounded-environment.md`.

**Then:**
1. Create the tooling environment and run `make check`; report the environment (Python, OS) and the result. Fix a red check before anything else, in its own PR.
2. If this directory is not a git repository, `git init -b main`, commit the starter as "Starter kit import". Do not add a remote: `config/repo.json` says none is designated. All git work is local until the owner designates one.
3. Append status: WO-001 `ready` then `in_progress`; phase M0 `ready`. Branch `wo/WO-001-m0`.
4. Implement WO-001 in small PRs as written (frozen exit-test thresholds in `evals/` **before** any simulator run; outcome code; export adapter; replay from initial state only; the five negative tests; frozen M0/M1 evaluation specification; report). Merge each PR only when `make check` is green on the final commit and the PR's acceptance criteria are met (`AGENTS.md §4.6`).
5. When WO-001 is accepted (status event with report path and commit), continue to WO-002 and, in a separate worktree if you spawn a subagent, WO-003. Keep going through the backlog while prerequisites are satisfied.

**You may, without asking:** write code, tests, docs, configs; create branches and worktrees; commit; open and merge local PRs that pass the checks; run CPU-tier checks; run the simulator on a machine already set up for this project; append to ledgers and status; write reports and ADRs; proceed to the next prerequisite-satisfied work order.

**You must stop and ask the owner before:** any spending (default budget is $0; a rented GPU needs a dated approval line in `ledgers/approvals.jsonl` first, after a measured pilot plan); any hardware motion; any destructive operation; opening sealed data; any push or remote operation (until `config/repo.json` is designated); any change to another project (`vla-rl-so101` is read-only through completed exports only); any scope or safety-boundary change; any exit-test threshold change after seeing results.

**Never:** fabricate results, treat fixtures or mocks as measured, weaken a check to merge, delete or overwrite anything under `data/`, `runs/`, `ledgers/`, `reports/`, `artifacts/`, or an accepted work order. Label every result measured / estimated / mocked / not run.

**If blocked** (simulator unavailable, pin unresolvable, approval missing, document conflict): preserve completed work, write `reports/BLOCKER-<date>-<slug>.md` with what you tried, evidence, the smallest decision that unblocks you and the reversible default you would take, append a `blocked` status event, and ask.

**End every session with:** commands run, test results, artifact hashes, failure analysis, unresolved pins, the updated status board, and the exact next action.
