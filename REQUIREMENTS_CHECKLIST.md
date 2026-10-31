# REQUIREMENTS_CHECKLIST.md — requirement → where it lives → status

Status words: **confirmed** (owner decision), **proposed default** (suggested, not objected to), **unknown**, **future option**. Milestone references point to `docs/PHASES.md`.

| # | Requirement (owner or review) | Where it lives | Status |
|---|---|---|---|
| 1 | One central program document for all agents, covering the trajectory of all projects and the owner's ML/robotics advancement | `PROGRAM.md` (identical in both kits; `config/program-lock.json`) | confirmed |
| 2 | Two independent projects; world model's first environment is the arm; M4 branches from M0/M1 | `PROGRAM.md §5–6`, `docs/PHASES.md`, ADR-0001 | confirmed |
| 3 | No Microduck, no rocket warm-up, no third project / shared runtime | `PROGRAM.md §5.5`, ADR-0001 | confirmed |
| 4 | Three world-model products with separate evidence; M1 scorer ≠ M2 evaluator | `docs/ARCHITECTURE.md §1`, `docs/PHASES.md` M1/M2a | confirmed |
| 5 | Exit tests for every phase, written before the phase starts; clear phase outline anyone can follow | `config/phases.json`, `docs/PHASES.md`, `AGENTS.md §5`, `docs/STATUS_BOARD.md` | confirmed |
| 6 | Never delete or overwrite data/runs/logs; append or new record | `AGENTS.md §6`, `docs/DATA_POLICY.md`, `tools/check_immutable.py`, `src/world_model/core/`, `contracts/v1/writer.py`, validation ledger | confirmed |
| 7 | Agile development: backlog of WOs, ready/done, WIP, cycles, retros | `AGENTS.md §3`, `docs/WORKFLOW.md §1`, `work_orders/README.md` | confirmed |
| 8 | Fundamental ML/software rules for agents | `AGENTS.md §8, §10` | confirmed |
| 9 | Autonomous iterative development; branches/PRs/merges in designated repos; no approval request per ordinary PR | `AGENTS.md §2.1, §4.6`, ADR-0002, `prompts/FIRST_SESSION.md` | confirmed |
| 10 | Separate approval for spending, hardware motion, paid compute outside envelope, deployment, destructive ops, access, publication, existing-project changes, scope/safety changes, sealed access | `AGENTS.md §2.3`, `ledgers/approvals.jsonl` | confirmed |
| 11 | Remote operations only for an explicitly designated repository; never invent a remote or make public | `config/repo.json`, `AGENTS.md §2.2`, `docs/WORKFLOW.md §8` | confirmed (remote: unknown) |
| 12 | Git/subagent/CI workflow: worktrees, ownership, integrating agent, merge rule, tiers, rollback, least privilege | `AGENTS.md §4`, `docs/WORKFLOW.md`, `.github/workflows/ci.yml` | confirmed |
| 13 | One shared versioned contract, identical in both kits, with conformance tests and labelled fixtures | `contracts/v1/`, `config/contract-lock.json`, `tools/check_hashes.py` | confirmed |
| 14 | Contract steward, release and compatibility rules, migration requirement; model manifests in the same boundary | `contracts/v1/RELEASE.json`, `contracts/v1/README.md`, `AGENTS.md §11` | confirmed |
| 15 | Arm integration read-only via completed immutable exports; auto-export is a future owner-approved producer change | `docs/DATA_AND_SNAPSHOTS.md §4–5`, `src/world_model/importer.py`, `AGENTS.md §13.4` | confirmed |
| 16 | Independent final assessment vs training reward; policy holdouts by run/family; dev vs sealed suites; logged access; paired randomized trials; session-aware analysis; abstention; false optimism and selection regret | `docs/EVALUATION_PROTOCOL.md`, `AGENTS.md §13.2–13.3`, M2a/M2b exit tests | confirmed |
| 17 | M3: separate pipelines; matched scenes; initial-state-only replay; executability ≠ physical success; SFT route; matched-budget and filter ablations | `docs/SYNTHETIC_DATA_M3.md`, M3 exit tests, `AGENTS.md §13.5` | confirmed |
| 18 | Measured results separate from estimates, mocks, plans; every report has methods, baselines, versions, lineage, commands, outcomes, limits, failures, costs | `AGENTS.md §7`, `docs/REPORT_TEMPLATE.md` | confirmed |
| 19 | Protect existing projects; isolate environments; no broad cleanup | `AGENTS.md §1` | confirmed |
| 20 | Budgets: default $0; measured pilot; authorization-bound files; reservations; time/step limits; cost ledger; provider teardown verification; preflight is not a launcher | `config/budget.json`, `docs/BUDGET_AND_LAUNCHER.md`, `tools/budget_preflight.py`, WO-003 | confirmed |
| 21 | Reproducible environment guidance; platform/GPU assumptions; what runs where | `docs/ENVIRONMENT.md`, `config/stack-lock.pending.json` | confirmed (pins: unknown) |
| 22 | Credentials outside source control; untrusted inputs; safe loading; licenses; privacy; retention; manifests | `AGENTS.md §6.6–6.7, §10`, `docs/DATA_POLICY.md`, `tools/scan_secrets.py` | confirmed |
| 23 | Simple modular components, typed interfaces, structured logs, no enterprise infrastructure | `AGENTS.md §8.6, §8.9`, `src/world_model/interfaces.py`, `core/log.py` | confirmed |
| 24 | Validation of the final packages with checksums and a verification report | `VERIFICATION.md`, `SHA256SUMS.json` | confirmed |
| 25 | Future builds (hand, locomotion sim, small humanoid, whole-body, real-robot RL) and research questions per build | `PROGRAM.md §7–8`, `docs/PHASES.md` M5–M8 | confirmed / future option |
| 26 | Hardware plan recorded, nothing purchased by these files | `PROGRAM.md §9` | confirmed intent |
| 27 | First ManiSkill3 task if no arm export exists | `docs/CONTEXT_AND_DECISIONS.md §5` | proposed default |
| 28 | Sealed-data physical location | `docs/CONTEXT_AND_DECISIONS.md §5` | unknown (owner) |
| 29 | Open-source license for the repository | `PROGRAM.md §12` | unknown (owner) |
| 30 | Verification of current PX4/ManiSkill/Isaac versions | `docs/SOURCES.md` "Not verified" | unknown (WO-001 resolves) |
