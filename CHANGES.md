# CHANGES.md — what this kit changed relative to the 2026-10-30 reference bundle, and why

Reference inputs: `Omni_Drone_World_Model_Starter_Kits_2026-10-30.zip` (reference starter), `Handoff_and_Release_Notes.zip`, `START_HERE.md`, the review prompt `Final_Starter_Kits_Review_Agent_Prompt.md`, and the Sept–Oct 2026 planning conversations (recorded in `PROGRAM.md` and `docs/CONTEXT_AND_DECISIONS.md`).

## Audit of the reference bundle (what was checked, what was found)
- Reran the reference tests in a clean environment (Python 3.13.18, jsonschema 4.26.0, pytest 9.1.1): **43 passed** per project, matching the reference claim. Contract hashes matched `SHA256SUMS.json` and `config/contract-lock.json`. Both JSON Schemas validate as Draft 2020-12.
- Lint: the reference utilities failed 144 `ruff` findings (compressed one-line style, unsorted imports, unused imports); `mypy --strict` passed on `validate.py`. Behaviour was correct; readability was not.
- Contradictions found: (1) "no branches/PRs/GitHub writes" and "stop after every work order" vs the owner's autonomous-development instruction; (2) `WO-002` id used twice in the drone kit; (3) the drone kit's `CLAUDE.md` carried world-model-only rules; (4) the contract README implied evidence is added by editing an episode manifest, which conflicts with the owner's never-overwrite rule; (5) the handoff prompt said "do not advance to another work order automatically".
- No fabricated results, secrets, or machine-specific paths were found in the reference.

## Substantive changes
| Area | Change | Reason |
|---|---|---|
| Program document | New `PROGRAM.md`, identical in both kits and in the Claude Project; hash-pinned (`config/program-lock.json`) | Owner asked for one central document every agent can refer to for the trajectory of all projects and his ML/robotics advancement |
| Policy source | `AGENTS.md` (shared core + project addendum) is the single authoritative policy; `CLAUDE.md` is a pointer | Review prompt §2; avoids independently maintained copies of the same rules |
| Authorization | Explicit matrix (`AGENTS.md §2`): autonomous work inside the repository; remote ops only after designation; separate dated approvals for spending, hardware motion, destructive ops, access, publication, sealed access, existing-project changes, scope/safety changes; agents continue to the next ready WO | Owner's Oct 30 instruction; reconciles the old blanket prohibitions |
| Git/subagent/CI | Feature branches, worktrees per subagent with file ownership, integrating agent, merge rule on exact candidate, CI tiers, rollback by revert, least-privilege CI (`AGENTS.md §4`, `docs/WORKFLOW.md`, `.github/workflows/ci.yml`, `Makefile`, `.pre-commit-config.yaml`) | Review prompt §4 |
| Append-only records | Rule (`AGENTS.md §6`), detail (`docs/DATA_POLICY.md`), CI enforcement (`tools/check_immutable.py`: pure-append for ledgers/reports, write-once for data/manifests, frozen accepted WOs), code enforcement (`src/*/core/`: append-mode ledgers, content-addressed store with no delete, exclusive-create run dirs; `contracts/v1/writer.py` write-once export) | Owner's rule: never delete or overwrite data, runs, logs; always append or create a new record |
| Phases and exit tests | `config/phases.json` (machine-readable, M0–M8 with ET ids, evidence, thresholds as proposed defaults) + `docs/PHASES.md` narrative + consistency test; `AGENTS.md §5` rules (frozen before start; state machine; evidence-only passes) | Owner asked for exit tests per phase and a phase outline anyone can follow |
| Status tracking | Append-only `work_orders/STATUS.jsonl` with validated transitions; derived `docs/STATUS_BOARD.md` (`tools/status_board.py`) | Anyone can track and follow the plan |
| Agile process | Cycle, definition of ready/done, WIP limits, sizing with estimate-vs-actual, retro note per report (`AGENTS.md §3`, `docs/WORKFLOW.md §1`) | Owner asked for agile development |
| ML/software fundamentals | `AGENTS.md §8` (reproducibility, pins, baselines first, tracking, tests, typed code, dependencies, resource bounds, simplicity, ADRs) and §10 (security) | Owner asked for fundamental rules for agents |
| Contract release | Schemas unchanged (v1.0.0); utilities reformatted without semantic change; added `validation_ledger.schema.json` and `validate.py --ledger` (append-only evidence); added `writer.py` (write-once reference exporter); added `RELEASE.json`; tests 32 → 41; `SHA256SUMS.json` regenerated; both kits pinned to the new manifest hash | Append-only rule; actionable export path for WO-001 and D1 |
| Work orders | Six WOs with the standard header (phase, exit tests, size, prerequisites, authorization, files); first three detailed, later ones milestone-level; budget WO renumbered | Review prompt §2; numbering fix |
| Scaffolding | `src/world_model/core/` (tested), `importer.py` (tested read-only import with completion marker and hash checks), `interfaces.py` (typed Protocols); `pyproject.toml` with ruff/mypy/pytest config | Makes WO-001/WO-006 actionable; typed interfaces per review prompt §7 |
| Docs | `ARCHITECTURE`, `CONTEXT_AND_DECISIONS` (conversation context + contradictions table), `EVALUATION_PROTOCOL`, `DATA_AND_SNAPSHOTS`, `SYNTHETIC_DATA_M3`, `ENVIRONMENT` (what runs where; Macs vs Linux/NVIDIA), `BUDGET_AND_LAUNCHER`, `SOURCES` (dated; hardware sources added; unverified items listed), `REPORT_TEMPLATE` (evidence words, exit-test table, retro, errata), `ADR_TEMPLATE` + two program ADRs | Review prompt §1–§7 |
| Handoff | `prompts/FIRST_SESSION.md` rewritten under the new authorization; `START_HERE.md` with exact next actions | Review prompt §2–§3 |
| Verification | `VERIFICATION.md` written from the actual packaging run (environment, commands, outcomes, not run); kit-level `SHA256SUMS.json` | Review prompt §8 |

## Preserved from the reference (audited, kept)
Contract schemas and fixtures (fabricated, labelled); validator semantics; split-audit semantics; budget preflight semantics and tests; evaluation protocol content (policy holdouts, sealed suites, Wilson/McNemar, physical sensing + blinded review, reward-hacking alarm); M0–M4 structure and the M4 branch rule; data/snapshot protocol; synthetic-data corrections; the $0 default budget; regulatory sources S1–S5 and the technical sources S6–S11.

## Not done in this pass (honest list)
No simulator, model, evaluator, generator, or launcher was implemented. No stack pins were resolved (`config/stack-lock.pending.json`). No web re-verification of PX4/ManiSkill/Isaac versions (owner declined the searches); hardware prices were verified on 2026-10-30 and are recorded with dates. No remote repository, CI run on GitHub, paid service, hardware, or other project was touched.
