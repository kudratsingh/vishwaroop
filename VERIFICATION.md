# VERIFICATION.md — world-model starter kit

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

