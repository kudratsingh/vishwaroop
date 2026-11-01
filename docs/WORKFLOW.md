<!-- ironclad-policy v1.2.0 -->
# WORKFLOW.md — how work moves through this repository

Rules live in `AGENTS.md` (§3–§5). This file is the procedure: the commands, templates and cadence that satisfy those rules. If this file and `AGENTS.md` disagree, `AGENTS.md` wins.

## 1. The agile cycle (one work order)

1. **Pick** — the next WO in `work_orders/` whose prerequisites are satisfied and whose scope is inside `AGENTS.md §2.1`. Check `docs/STATUS_BOARD.md` and `work_orders/STATUS.jsonl` first.
2. **Ready** — confirm the definition of ready: prerequisites evidenced, exit tests frozen in `evals/` (numbers, not placeholders), approvals recorded, pins resolved or the WO is the one resolving them. Append `ready`.
3. **Branch** — `git switch -c wo/<WO-id>-<slug>` (or a worktree, §3). Append `in_progress`.
4. **Build in slices** — smallest end-to-end slice first (one episode, one mission, one check). Commit early and often; every commit passes `make check` locally.
5. **Verify** — run the WO's verification steps and the phase exit tests it advances; write the report from `docs/REPORT_TEMPLATE.md` into `reports/<WO-id>-<slug>.md` (append-only once merged).
6. **PR** — open the PR with the template below; CI must be green on the final commit; revalidate against `main`; merge per `AGENTS.md §4.6`.
7. **Accept** — append `accepted` with the report path and commit hash; regenerate the board (`make board`). The WO file is now frozen.
8. **Retro** — the report's retro note says what to change next time; convert durable lessons into an ADR or a new WO. Then go to step 1.

Expected cadence: a WO is sized S (hours), M (a day or two of agent work), or L (split it). Estimates are recorded in the WO and compared with actuals in the report so sizing improves.

## 2. Status ledger commands

```bash
# append an event (validates the transition and the WO/phase ids)
ironclad-status --append --wo WO-001 --event in_progress --note "branch wo/WO-001-m0"
ironclad-status --append --phase M0 --event in_progress
ironclad-status --append --wo WO-001 --event accepted --report reports/WO-001-m0.md --commit <sha>
# regenerate the derived board
ironclad-status --render > docs/STATUS_BOARD.md
```
Events for a WO: `created, ready, in_progress, blocked, unblocked, accepted, failed, superseded`.
Events for a phase: `ready, in_progress, blocked, unblocked, passed, failed`.
Before `v1.0.0`, and in a repository that has not adopted `ironclad`, the same commands are `python tools/status_board.py ...`.
The ledger is append-only; a mistaken event is corrected by appending a `superseded`/`unblocked` event with a note, never by editing the file.

## 3. Branches, worktrees, subagents

```bash
# integrating agent creates a worktree per subagent
git worktree add ../<repo>-WO-004 -b wo/WO-004-predictor
# subagent works only inside ../<repo>-WO-004 and only on the files its WO lists
# integrating agent reviews, runs checks, merges, then removes the worktree (not the branch history)
git worktree remove ../<repo>-WO-004
```
Ownership: each concurrent WO declares the directories it may touch (`Files` section). Overlap is resolved by the integrating agent before work starts, not during merge. Never open two editors on the same checkout.

## 4. Pull request template

```
## WO
WO-xxx — <title>  (phase <id>; exit tests advanced: ET-...)

## What changed and why
...

## Evidence
- Commands run (exact):
- Results (measured / estimated / mocked / not run — label each):
- Report: reports/...

## Checks
- [ ] ruff format --check, ruff check, mypy clean
- [ ] pytest CPU tier green on this commit
- [ ] `ironclad verify` green (policy copies, vendored files, install source, contract manifest)
- [ ] secrets/absolute-path scan green
- [ ] append-only check green (no protected path modified or deleted)
- [ ] no new dependency, or justified below
- [ ] authorization: inside AGENTS.md §2.1; approvals referenced: ledgers/approvals.jsonl#<line>

## Risks and rollback
Revert commit <sha> restores the previous state because ...
```

## 5. Local check commands

```bash
make check          # everything the CPU tier runs in CI
make lint type test # individually
make verify         # ironclad sync-policy --check and ironclad verify
make secrets        # secret and absolute-path scan
make links          # markdown link check
make board          # regenerate docs/STATUS_BOARD.md
make immutable BASE=origin/main   # what CI runs on PRs
```

## 6. CI tiers in practice

| Tier | Trigger | Where | Reports |
|---|---|---|---|
| CPU | every push, every PR | GitHub Actions `ci.yml` | check status on the PR |
| Simulator/integration | label `run-sim` or manual dispatch; or run locally on a machine with the stack and attach the report | self-hosted or local | `reports/` + PR comment with the run id |
| GPU | separately authorized WO on a designated machine | local/rented, supervised | `reports/` + `ledgers/costs.jsonl` |
| Physical | separately authorized WO with the operating protocol | bench or test site | `reports/` + video/sensor manifests |

A tier that did not run is written as **not run** in the PR and the report.

## 7. Releases and rollback

- Tag at phase passes: `git tag -a v0.<phase-number>.0 -m "Phase <id> passed: <report path>"`.
- The tag message names the report that proves the pass. Tags are never moved.
- Rollback is `git revert` in a PR with the same checks. If a release is withdrawn, add an errata record to the report (append-only) and a new status event; never delete the tag or the report.

## 8. When the owner designates a remote

1. Owner fills `config/repo.json` (`remote`, `visibility: private`, `designated: true`) and creates the empty repository themselves or explicitly authorizes an agent to create it under the named account.
2. Agent: `git remote add origin <url>`, push `main` and open branches, enable the required check `cpu-tier` (a gate job: a matrix job reports one check per version and cannot be required by its own name), require PRs to `main`, apply the rules to administrators, disallow force-push and deletion on `main`, read the settings back, and record them in an ADR.
3. Until step 1 happens, everything above still applies to local branches and local merges; the PR template is kept as the merge commit message.
