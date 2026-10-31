# VERIFICATION.md — vishwaroop (World Model & Planner), imported from the world-model starter kit

## Post-rename verification (2026-10-31, branch `wo/WO-007-program-rename`)

**These are the current hashes.** The packaging record further down is kept as history and shows the values before the rename.

Environment: Python 3.13.7 on macOS 26.5.2 (Darwin 25.5.0, arm64), with the pins in `requirements-dev.txt`. The baseline `make check` on the unmodified import, also measured here, passed before any edit (82 tests).

### Identity
Copied byte for byte from `banshee`, and byte-identical at its commit `3a66e3c6a93436f3bd6673708715264d1e4781c8`, the source commit the owner named. Each value below was computed from the files in this repository and matches the hash table in ADR-0003.

| Item | sha256 |
|---|---|
| `PROGRAM.md` (version 1.1) | `58f4c930ca08aaa2fd630826905e9ef9892968e7ceda8e2d920863f5142d02a9` |
| `config/program-lock.json` | `6c6e8cf7ddfb8434754b223d12e1d12a23023be7da2a41e6f118f964c0f77e17` |
| `contracts/v1/SHA256SUMS.json` | `9c0b9347be3758b359c7c7e9fdf7eb7798086167fb1162112fcc9d22bd5a61c3` |
| `config/contract-lock.json` | `f8c3cc1f24919af858a6d77038f3e2127f64d6206610e02f7d9b6b59cbe595ff` |
| `AGENTS.md` core (bytes before `## 13.`) | `8f174fdc05d6184675491181d91a9a8921f7678b22006378f696ec27847659b6` |

### Measured
Run in a throwaway clone, on a scratch commit of this tree.

| Check | Result |
|---|---|
| `make check` (lint, types, tests, hash locks, secrets, links) | passed; 104 tests, 41 of them contract conformance |
| `make immutable` against `main` | passed; the same tool failed as it should on a scratch control commit that removed a line from `work_orders/STATUS.jsonl` |
| `tools/check_hashes.py --verify-kit-manifest` | passed |
| `contracts/v1/validate.py` on all three fixtures | exit 0 |
| `contracts/v1/audit_splits.py` on all three fixtures | exit 0 |
| Negative test: `imagined_arm` with this project's retired `producer` value | rejected, exit 2 |
| Negative test: `drone_sim` with the drone project's retired `producer` value | rejected, exit 2 |
| `import vishwaroop` with its `core`, `importer` and `interfaces` modules | passed; the old package name raises `ModuleNotFoundError` |
| `PYTHONPATH=src python -m vishwaroop.importer verify` on a missing directory | refused, exit 2 |
| Wheel built from the clone | `vishwaroop-0.0.1-py3-none-any.whl`, containing the `vishwaroop` package |
| `/usr/bin/grep -rn` for the old underscore package name, outside `.git` | no hits, in the clone and in this working checkout after its stale caches were cleared |
| `tools/status_board.py --append` with `--phase M0` and with `--et ET-M0-3`, in the clone | accepted, exit 0 |
| `tools/status_board.py --append` naming both `--phase` and `--et`, in the clone | refused, exit 2 |
| A file under `reports/`, in the clone | `tests/test_project_consistency.py` passes |
| Fresh `git init && git add -A` on this tree | tracks every file in `SHA256SUMS.json` |
| Second `created` event for a work order, in the clone | refused, exit 2 |
| `git check-ignore` on `secret_prod.env`, `mysecret`, `secretkey`, `my_secret_key.txt` and `secret_config.py` | all ignored; `tools/scan_secrets.py` is not |
| `git ls-files -ci --exclude-standard` | no tracked file is ignored |

### Cross-repository check: against `banshee` commit `3a66e3c`
This repository applied the change second, so it copied the shared files and authored none of them. It then compared the `banshee` commit object with this tree: `contracts/v1/` as a whole tree, `PROGRAM.md`, both lock files, ADR-0003 and the `AGENTS.md` core. All were byte-identical at 10:57 UTC, as were `.gitignore`, `tools/status_board.py`, `tools/scan_secrets.py`, `tools/check_immutable.py`, `tests/test_tools.py` and `tests/test_project_consistency.py`. That commit is on the `banshee` branch `wo/WO-006-program-rename`, not on its `main`. Neither repository has merged this change. The owner confirms the match across the two repositories before merging.

### First copy superseded
The first copy was an earlier draft and was replaced on the owner's instruction. `work_orders/WO-007-program-rename-vishwaroop.md` records what changed and why.

### Remote (WO-009)
Read back from GitHub. `reports/WO-009-designate-github-remote.md` has the detail.
- `kudratsingh/vishwaroop` is private, with default branch `main`. The owner asked for it on 2026-10-31.
- `main` was pushed at `654bc0d`. CI run 41192093373 passed on that commit, on `cpu-tier (3.12)` and `cpu-tier (3.13)`.
- `main` requires pull requests with 0 approvals and both `cpu-tier` checks, administrators included. Force-push and deletion are disallowed.
- The owner approved pushing this branch and opening one pull request to `main`. When this commit was made, CI had **not run** on it; the pull request shows the result. The owner merges it, together with the `banshee` pull request.

### Old names left on purpose
- `Omni_Drone_World_Model_Starter_Kits_2026-10-30.zip` in `CHANGES.md`, a real file name.
- `world-model` in this file's title and in the rename note in `CHANGES.md`, which record where the repository came from.
- `omni-world` in `contracts/v1/RELEASE.json` and the schema `$id` URNs, the contract's own name, and in ADR-0003 and WO-007, which say it stays.
- "Omni Drone", "World Model & Planner", "world model" and "world-model" as descriptive prose, which the owner's decision keeps valid.

### Starter-kit defects, fixed under WO-008
These came with the kit, and this repository tracks them as its WO-008. The fixes were copied byte for byte from `banshee` commits `95f7a34` and `da128e3`, in this repository's commits `b42d391` and `d6e1460`. WO-010 later took newer copies. "Before" was measured at `a8a58b1`, the rename commit, and "After" on this tree:

| Defect | Before | After |
|---|---|---|
| `.gitignore`: `*secret*` also matches `tools/scan_secrets.py` | a fresh `git add -A` drops the tool, and `make lint` checks 25 files | `git add -A` tracks every manifest file, and `make lint` checks 26 |
| `tools/status_board.py`: `--phase` and `--et` appends | refused, exit 2 | accepted, exit 0; a record naming more than one id is refused |
| `tests/test_project_consistency.py::test_no_fixture_claims_in_reports` | any `.md` report in `reports/` fails the test; `README.md` and `INDEX.md` are exempt | test deleted, so real reports pass |

One cost comes with these copies: no test now checks reports for unbacked claims. `AGENTS.md §7` still requires evidence, by rule only.

### Work-order freeze, secret scan and ignore rule (WO-010)
Copied byte for byte from `banshee` commit `3a66e3c`.
- WO-008's narrower `.gitignore` patterns left `my_secret_key.txt`, `secret_config.py`, `secret_prod.env`, `mysecret` and `secretkey` trackable (measured). On the owner's decision, `.gitignore` is back to `*secret*`, keeping `secrets/` and `.secrets*`, with an exception for the scanner. All five names are now ignored (measured).
- **Cost of the broad rule:** any new file with "secret" in its path is silently ignored. `git add -A` leaves it out and `make check` stays green (measured: this repository's WO-010 file hit this under its first name, and was renamed). `test_no_tracked_file_is_ignored` covers only files that are already tracked.
- **Scanner limits that remain:** `tools/scan_secrets.py` now scans files with no extension and adds Hugging Face and RunPod patterns. It reads a file named exactly `.env`, because that name has no suffix, but not `.env.local`, `prod.env` or `secret_prod.env` (measured). A file named `prod.env` is neither ignored nor scanned (measured), a gap the kit shipped with. In any file, it does not catch a bare value with no recognizable pattern (measured).
- **Side effect:** the scanner walks the working tree, not git's index, so a git-ignored local `.env` holding a recognizable credential now turns `make secrets` and `make check` red (measured).

### Found during review, not fixed here
These predate the rename and are outside it.
- `docs/BUDGET_AND_LAUNCHER.md` cites `tests/test_budget_preflight.py`, which does not exist. Those tests are in `tests/test_tools.py`.
- The `python -m vishwaroop.*` commands in the work orders need `PYTHONPATH=src` or an install, and no document says so. Without it, the module is not found (exit 1).
- `START_HERE.md §6` and `prompts/FIRST_SESSION.md` step 3 mark WO-001 and M0 `ready` before the exit tests are frozen, which `AGENTS.md §5.3` does not allow.
- `PROGRAM.md §12` row 7 says no remote is designated for either project, which is no longer true of either project. Fixing it needs a program change, authored in `banshee`.

### Retro note
Copying from a moving working tree produced a draft that had to be replaced. Next time, copy shared files only from a commit object and check them against that commit's own hash table. Run the owner's exact check with the system binary in the real checkout: a session-level `grep` wrapper and a clean clone each hid stale binary caches here. The two repositories also depend on each other here: `banshee` waits on this confirmation, and this repository needs its final commit, so whoever holds the final hash should state it. Dry-run a copied ignore rule against this repository's own paths before adopting it: that is how the WO-010 file name was caught.

### Next work order
WO-001, once WO-007, WO-008 and WO-010 are `accepted`.

### Claude Project copy
Verified by the owner's assistant on 2026-10-31, not by an agent in this repository, which cannot read that copy: `claude/PROGRAM.md` in the Project is version 1.1, sha256 `58f4c930...`, the same bytes as both repositories.

### Not run
When this commit was made, GitHub CI had not run on this rename branch, so the Python 3.12 leg had not run on these bytes; it had passed only on `main` at `654bc0d`, before the rename. No simulator, no hardware.

## Packaging record (before the rename)

Packaging run: 2026-10-31 07:51 UTC. Everything below was executed on the assembled kit before zipping; nothing is copied from the reference bundle's reports.

## Environment (packaging machine)

- Python 3.13.18 on Linux 6.18.44-fc-v185 (x86_64)
- jsonschema 4.26.0
- pytest 9.1.1
- ruff 0.16.9
- mypy 2.3.1
- No simulator, GPU, robotics stack, network service, hardware, or other repository was used.

## Identity

- `contracts/v1/SHA256SUMS.json` sha256: `28a2bab148bd83a32bab547ddcc1318d081e2401ce0a8c627138de64a7ec116c` (pinned in `config/contract-lock.json`; identical in both kits)
- `PROGRAM.md` sha256: `a7f0b3f1d6f8bb5bc09ee00f44c7f657a3040a3453909f83b602379cfbfbe483` (pinned in `config/program-lock.json`; identical in both kits)
- `AGENTS.md` shared core (sections 1–12, before the project addendum) sha256: `11c7b92e9793342bd17d4ced447dbe3376d01e39b17b5d35ccd2f81cece0c444` (identical in both kits)
- Tests collected: 82 (CPU tier: contract conformance + core record helpers + tools + project consistency + project modules)

## Commands and outcomes

| Check | Command | Exit code | Result |
|---|---|---:|---|
| ruff format --check | `ruff format --check src tools tests contracts/v1` | 0 | 26 files already formatted |
| ruff check | `ruff check src tools tests contracts/v1` | 0 | All checks passed! |
| mypy | `mypy src tools contracts/v1/validate.py contracts/v1/audit_splits.py contracts/v1/writer.py` | 0 | Success: no issues found in 19 source files |
| pytest | `-m pytest -p no:cacheprovider` | 0 | 82 passed in 1.12s |
| check_hashes | `tools/check_hashes.py` | 0 | hash locks OK: contract release, program document |
| scan_secrets | `tools/scan_secrets.py` | 0 | secrets/absolute-path scan OK |
| check_links | `tools/check_links.py` | 0 | markdown links OK |
| budget_preflight | `tools/budget_preflight.py --budget config/budget.json --plan config/cpu-smoke-plan.json` | 0 | "status": "local_plan_within_configured_limits", |
| validate fixtures | `contracts/v1/validate.py contracts/v1/examples/arm_sim/episode.json` | 0 | "status": "contract_valid", |
| audit fixtures | `contracts/v1/audit_splits.py contracts/v1/examples/arm_sim/episode.json contracts/v1/examples/drone_sim/episode.json contracts/v1/examples/imagined_arm/episode.json` | 0 | "status": "declared_group_and_lineage_checks_passed", |

All commands above were run with the repository root as the working directory (`python` = the packaging interpreter).

## Not run (and therefore not claimed)

- No ManiSkill3, PX4, Gazebo, ROS 2, PyTorch or Isaac Lab installation or run; `config/stack-lock.pending.json` pins are unresolved.
- No milestone or stage exit test; every phase is `not_started` on the status board; `reports/` holds no milestone report.
- No GitHub CI run (`.github/workflows/ci.yml` is untested on GitHub; its steps are the same `make` targets executed here).
- No `tools/check_immutable.py` run against a real PR (its logic is covered by `tests/test_tools.py` on temporary git repositories).
- No paid service, hardware, flight, arm motion, remote repository, or other project was touched.

## Interpretation

A green CPU tier proves serialization, integrity and tooling behaviour on fabricated fixtures. It is not evidence about any simulator, model, robot or aircraft.

