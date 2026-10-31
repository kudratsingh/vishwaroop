# vishwaroop (World Model & Planner)

`vishwaroop` is the repository and Python package of World Model & Planner; the name is Sanskrit *viśvarūpa*, the universal form Krishna shows Arjuna — all of creation seen at once, which Arjuna asks him to stop showing; a world model sees everything and is trusted only as far as it has earned. Standalone learning, planning, evaluation and synthetic-data infrastructure for robot policies. First environment: the arm project's ManiSkill3 setup (`vla-rl-so101`), read-only; first evaluation subject: its VLA; later the drone's flight logs (M4) and a LEAP hand (M8). Part of the owner's physical-AI program — read `PROGRAM.md` first.

## Three products, three bodies of evidence
1. Compact predictive model, latent planner and **action-chunk scorer** (M1).
2. Action-conditioned, policy-compatible **closed-loop evaluator** (M2a sim, M2b real arm).
3. Filtered synthetic demonstrations for the **SFT route**, with matched-budget downstream evidence (M3).
M4 adapts motion prediction to drone logs offline/shadow-only and branches from M0/M1.

## Read in order
`PROGRAM.md` → `AGENTS.md` → `START_HERE.md` → `docs/PHASES.md` → `docs/ARCHITECTURE.md` → `docs/CONTEXT_AND_DECISIONS.md` → `docs/EVALUATION_PROTOCOL.md` → `docs/DATA_AND_SNAPSHOTS.md` → `work_orders/WO-001-m0-grounded-environment.md`.

## CPU-tier checks (any machine)
```bash
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements-dev.txt
make check          # lint, types, tests, hash locks, secrets scan, link check
make board          # regenerate docs/STATUS_BOARD.md
python contracts/v1/validate.py contracts/v1/examples/arm_sim/episode.json
python tools/budget_preflight.py --budget config/budget.json --plan config/cpu-smoke-plan.json
```
These commands do not run ManiSkill, train anything, read the arm repository, or constitute evidence of any milestone. The contract fixtures are fabricated.

## Current status (2026-10-31)
| Implemented and tested here | Specified, not implemented |
|---|---|
| contract v1 (schemas, validator with append-only ledger merge, split audit, write-once reference writer, fixtures, 41 tests) | ManiSkill3 adapter, export, replay (WO-001) |
| core record helpers: append-only ledgers, content-addressed artifacts, write-once run dirs, structured logs, strict config | dataset collection and registry (WO-002, WO-006) |
| read-only export importer with completion-marker and hash verification | predictors, planner, scorer (WO-004, WO-005) |
| typed Protocol interfaces for every planned module | evaluator, synthetic engine, drone adaptation (M2–M4) |
| tools: status ledger/board, append-only CI check, hash locks, secrets scan, link check, budget preflight | enforcing paid launcher (WO-003), provider adapter |
| CI workflow (CPU tier), Makefile, pre-commit hooks | sealed-data storage, physical outcome sensing |

All phases are `not_started`; see `docs/STATUS_BOARD.md`. No paid compute, hardware, or remote repository is authorized by these files (`AGENTS.md §2`).

## Layout
```
PROGRAM.md  AGENTS.md  CLAUDE.md  START_HERE.md  CHANGES.md  REQUIREMENTS_CHECKLIST.md  VERIFICATION.md
config/      phases.json, budget.json, repo.json, locks, stack-lock.pending.json, sealed-access schema/policy
contracts/v1 the one shared boundary (byte-identical in banshee)
docs/        PHASES, ARCHITECTURE, CONTEXT_AND_DECISIONS, EVALUATION_PROTOCOL, DATA_AND_SNAPSHOTS, SYNTHETIC_DATA_M3,
             ENVIRONMENT, WORKFLOW, DATA_POLICY, BUDGET_AND_LAUNCHER, REPORT_TEMPLATE, ADR_TEMPLATE, SOURCES, STATUS_BOARD, adr/
src/vishwaroop/    core/, importer.py, interfaces.py   (sim/, data/, models/, planning/, scoring/, eval/, synth/ to come)
tests/       CPU tier;  contracts/v1/tests/  conformance
tools/       status_board, check_immutable, check_hashes, scan_secrets, check_links, budget_preflight
work_orders/ WO-001..007 + STATUS.jsonl (append-only)      prompts/FIRST_SESSION.md
data/ runs/ ledgers/ artifacts/ reports/ evals/   append-only record locations
```
