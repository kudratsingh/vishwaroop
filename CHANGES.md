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
| Scaffolding | `src/vishwaroop/core/` (tested), `importer.py` (tested read-only import with completion marker and hash checks), `interfaces.py` (typed Protocols); `pyproject.toml` with ruff/mypy/pytest config | Makes WO-001/WO-006 actionable; typed interfaces per review prompt §7 |
| Docs | `ARCHITECTURE`, `CONTEXT_AND_DECISIONS` (conversation context + contradictions table), `EVALUATION_PROTOCOL`, `DATA_AND_SNAPSHOTS`, `SYNTHETIC_DATA_M3`, `ENVIRONMENT` (what runs where; Macs vs Linux/NVIDIA), `BUDGET_AND_LAUNCHER`, `SOURCES` (dated; hardware sources added; unverified items listed), `REPORT_TEMPLATE` (evidence words, exit-test table, retro, errata), `ADR_TEMPLATE` + two program ADRs | Review prompt §1–§7 |
| Handoff | `prompts/FIRST_SESSION.md` rewritten under the new authorization; `START_HERE.md` with exact next actions | Review prompt §2–§3 |
| Verification | `VERIFICATION.md` written from the actual packaging run (environment, commands, outcomes, not run); kit-level `SHA256SUMS.json` | Review prompt §8 |

## Preserved from the reference (audited, kept)
Contract schemas and fixtures (fabricated, labelled); validator semantics; split-audit semantics; budget preflight semantics and tests; evaluation protocol content (policy holdouts, sealed suites, Wilson/McNemar, physical sensing + blinded review, reward-hacking alarm); M0–M4 structure and the M4 branch rule; data/snapshot protocol; synthetic-data corrections; the $0 default budget; regulatory sources S1–S5 and the technical sources S6–S11.

## Not done in this pass (honest list)
No simulator, model, evaluator, generator, or launcher was implemented. No stack pins were resolved (`config/stack-lock.pending.json`). No web re-verification of PX4/ManiSkill/Isaac versions (owner declined the searches); hardware prices were verified on 2026-10-30 and are recorded with dates. No remote repository, CI run on GitHub, paid service, hardware, or other project was touched.

## After import: program-wide rename (2026-10-31, ADR-0003, WO-007)
The starter kit shipped as `world-model`. The repository and package are now `vishwaroop`, and the sibling project is `banshee`. Paths in this file were updated so they still resolve. The contract `producer` enum and fixtures, `PROGRAM.md` (version 1.1), the shared `AGENTS.md` core (policy version 1.1), manifests and locks changed with it; this repository applied the change second, so it copied those bytes from `banshee` and did not re-author them, as ADR-0003 directs. The one behaviour change: the validator now rejects the retired `producer` values and accepts the new ones. No other behaviour, threshold or authorization changed. The planned M0 task-choice ADR moved from ADR-0003 to ADR-0004 (`docs/adr/ADR-0003-PROGRAM-project-names.md`).

## After import: starter-kit defects fixed (2026-10-31, WO-008)
The rename did not cause these. This repository tracks them as its WO-008. The fixes were copied byte for byte from `banshee` commit `da128e3`, the source the owner named at that time, in separate commits on the WO-007 branch.
- **`tools/status_board.py`:** `--phase` and `--et` appends were always refused, because the record carried `"wo": null` and took the work-order path. The command line now drops unset fields before `append()`, and `current_states` tests its keys by `.get()` truthiness. It now refuses a record naming more than one id, which would otherwise mark a phase `passed` without recording the exit test. `tests/test_tools.py` adds tests for these appends through the command line.
- **`tests/test_project_consistency.py`:** deleted `test_no_fixture_claims_in_reports`, as `banshee` did on the owner's instruction. It failed on any `.md` report in `reports/`, so it blocked every real work-order report.
- **`.gitignore`:** replaced `*secret*`, which silently dropped `tools/scan_secrets.py` from `git add -A` and hid it from `ruff`, with specific patterns plus `!tools/scan_secrets.py`. `tests/test_tools.py` adds a test for this.

## After import: private GitHub remote (2026-10-31, WO-009)
The owner asked for the repository to be created. `kudratsingh/vishwaroop` is private, and `main` is protected (ADR-0005). `wo/WO-007-program-rename` stays local until the owner approves its push and pull request, and `main` keeps the kit's old package name until the branch merges.

## After import: work-order freeze, wider secret scan, broad ignore rule (2026-10-31, WO-010)
Copied byte for byte from `banshee` commit `3a66e3c6a93436f3bd6673708715264d1e4781c8`, where this is its WO-009, on the owner's instruction.
- **`tools/status_board.py`:** refuses a `created` event for a work order that already has a ledger record.
- **`tools/check_immutable.py`:** keeps the freeze once any `accepted` event exists, so a line appended later cannot lift it, and rejects replacing a protected file with a symlink.
- **`tools/scan_secrets.py`:** adds Hugging Face and RunPod token patterns, and now scans files with no extension.
- **`.gitignore`:** returns to `*secret*`, keeps `secrets/` and `.secrets*`, and keeps the exception for the scanner. This replaces the narrower patterns from WO-008, which left names such as `secret_prod.env`, `mysecret` and `secretkey` trackable.
- **`tests/test_tools.py`:** adds tests for these.

## After import: rename merged and accepted (2026-10-31)
Pull request 1 merged as `85027d4` on the owner's approval, after the owner's check across the two repositories passed at `banshee` `3a66e3c`. WO-007, WO-008 and WO-010 are accepted, with reports under `reports/`.

## After import: M0 and M1 specification frozen (2026-10-31, WO-001)
Before any simulator run or training: `evals/M0-exit-tests.json`, `evals/M0-protocol.md`, `evals/M1-exit-tests.json` and ADR-0004. Replay deviation is measured in rad and m, not the "normalized joint units" `config/phases.json` proposed, which nothing defined. M1 thresholds are the proposed defaults, unchanged. `config/phases.json` and `docs/PHASES.md` now state the frozen values. `START_HERE.md` and the first-session prompt no longer mark M0 `ready` before its exit tests are frozen, which fixes a defect `VERIFICATION.md` had listed. WO-001's Files line grew to cover these documents, and WO-002 no longer creates a sealed partition, matching the frozen protocol.

**Program decision:** shared files become a pinned dependency, `ironclad`, built by its own agent. No shared file is edited here or copied across, including the tooling lock. This repository migrates in its own work order when v1.0.0 is tagged.

**Merge and review rule (`AGENTS.md §13.8`):** agents merge their own pull requests on green required checks, and owner approval is only for the authorization matrix. A full review comes first only for work orders that close exit tests, touch the contract, or integrate RL or evaluator components.

## After import: WO-001 CPU-tier work (2026-10-31)
Adds the independent outcome (`src/vishwaroop/outcome/`), contract export, initial-state-only replay and the five negative tests (`src/vishwaroop/sim/`), tested on a fabricated fake environment. The ManiSkill3 adapter is written and has **not run**. WO-001's simulator steps are blocked (`reports/BLOCKER-2026-10-31-m0.md`). Package code reaches the contract through `src/vishwaroop/sim/contract.py`; what else the `ironclad` migration touches is unknown until it exists.

An independent review before the push found that this code failed open in several ways, including NaN read as a perfect replay, zero repeats passing, and a forged recorded outcome going unnoticed. All were fixed with regression tests before anything was pushed, and the protocol became `m0-protocol-2` before any result.

## After import: the simulator runs on the Mac; WO-003 moved (2026-10-31)
On the owner's one-attempt approval, ManiSkill3 runs state-only CPU physics on the Mac with MoltenVK in a scratch folder. `reports/BLOCKER-2026-10-31-m0.md` records the measurements in an appended section. WO-003 is superseded: the launcher is built in `ironclad` and adopted at the v1.0.0+ migration. WO-006 stays unstarted until an arm export exists.

## After import: shared files come from `ironclad` (2026-11-01)
WO-011 pins `ironclad-kit` v1.1.0 and removes the vendored contract, tools, record helpers, shared tests, hash locks and the root `SHA256SUMS.json`. `docs/adr/ADR-0007-adopt-ironclad.md` records it, and maps the old paths that stay in frozen or historical text.
