# WO-001 | M0 grounded environment: one reproducible simulator episode and its evidence chain
**Phase:** M0
**Exit tests advanced:** ET-M0-1, ET-M0-2, ET-M0-3, ET-M0-4, ET-M0-5
**Size:** L (split into PRs: stack lock → adapter + export → replay + negatives → frozen spec)
**Prerequisites:** WO-007 `accepted` (status ledger). Otherwise none beyond a Linux + NVIDIA machine for the simulator (rented is fine; $0 spend unless the owner approves a rental line in `ledgers/approvals.jsonl`). CPU-tier work (`make check`, scaffolding, specification) proceeds on any machine.
**Authorization:** AGENTS §2.1 only, except: any paid rental needs a §2.3 approval recorded first.
**Files:** `src/vishwaroop/sim/`, `src/vishwaroop/outcome/`, `tests/`, `config/stack-lock.resolved.json`, `evals/M0-*`, `evals/M1-*`, `reports/WO-001-m0-grounded-environment.md`, `docs/adr/`, ignored `data/`, `runs/`.

## Objective
Produce one genuinely reproducible ManiSkill3 episode with its full evidence chain, so that everything the project later claims rests on a simulator that is pinned, exportable through the contract, replayable from its initial state only, and judged by code that shares nothing with any policy or reward. Then freeze the evaluation specification that M1 will be measured against.

## Scope
1. **Environment selection and lock.** Pick the ManiSkill3 task that best matches the arm project's setup. If the arm project has not exported its task configs/action space yet, use a readily available pick-and-place task and **label the embodiment honestly** (no transfer claim). Install on the pinned stack; write `config/stack-lock.resolved.json` (every entry *tested* or *proposed*, dated). Record an ADR for the task choice.
2. **Deterministic baseline policy.** A scripted or motion-planned controller that succeeds often and fails sometimes; its code path is the only policy in this WO.
3. **Independent outcome.** `src/vishwaroop/outcome/` computes task success from simulator state (object pose inside the target region, released grasp, dwell) in code with no dependency on the policy or any learned model. Write its rubric to `evals/M0-protocol.md`.
4. **Logging adapter.** `src/vishwaroop/sim/export.py` records every step as a contract-v1 transition (observations with capture/receive times and validity masks, action stages, context) and exports through `contracts/v1/writer.py` with `environment_kind: physics_sim`, saved initial state and asset manifest, `restore_mode: initial_state_only`.
5. **Replay.** `src/vishwaroop/sim/replay.py` restores the saved initial state only, executes the recorded actions through physics, and reports per-step deviation and outcome agreement over 3 repeats. Freeze the tolerance in `evals/M0-exit-tests.json` *before* the first replay run.
6. **Negative tests.** Corrupted action semantics (swap two action labels), broken artifact hash, missing asset, wrong timebase (shift `t_ns`), intermediate-state forcing (a replay mode that sets state every step) — each must fail validation or invalidate the replay claim.
7. **Frozen evaluation specification** (ET-M0-5): `evals/M0-protocol.md` (task rubric, split specification, group ids, policy-holdout plan by run/family, sealed opening budget, baselines) and `evals/M1-exit-tests.json` with the M1 thresholds frozen from the proposed defaults in `config/phases.json` or justified alternatives. Append `frozen` status events for every M1 exit test.
8. **Report** `reports/WO-001-m0-grounded-environment.md` from the template.

## Out of scope
Neural training, VLA fine-tuning, video generation, teleop data, physical hardware, any change to `vla-rl-so101` or other repositories, remote git operations before designation, dataset collection at scale (WO-002).

## Deliverables
- `config/stack-lock.resolved.json`; `docs/adr/ADR-0004-m0-task-choice.md`.
- `src/vishwaroop/sim/{env.py,export.py,replay.py}`, `src/vishwaroop/outcome/pickplace.py`, with unit tests that run on CPU (use recorded fixtures for logic; mark simulator-dependent tests with `@pytest.mark.sim` and skip them when the stack is absent).
- One exported episode directory (ignored path, manifest in `artifacts/manifests/m0-first-episode.json`) and its replay report in `runs/`.
- `evals/M0-protocol.md`, `evals/M0-exit-tests.json`, `evals/M1-exit-tests.json` (hashed in the report).
- Report with commands, hashes, failure cases, unresolved pins.

## Steps
1. `make check` green on a clean checkout → status `in_progress` for WO-001 and phase M0 (`ready` first if not yet).
2. Resolve the stack on the GPU machine; write the lock; commit (PR 1).
3. Implement outcome code and its CPU tests; implement the baseline policy; run 1 success and 1 failure episode; inspect and record (PR 2).
4. Implement the export adapter; export both episodes; `python contracts/v1/validate.py <episode>/episode.json` must print `contract_valid` (PR 2).
5. Freeze `evals/M0-exit-tests.json` (replay tolerance) → `frozen` events for ET-M0-3; implement replay; run 3 repeats; record deviations (PR 3).
6. Run the five negative tests; record each failure message (PR 3).
7. Write `evals/M0-protocol.md` and `evals/M1-exit-tests.json`; append `frozen` events for ET-M1-1…5 (PR 4).
8. Write the report; append `accepted` with report path and merge commit; `make board`.

## Verification
```bash
make check
python contracts/v1/validate.py data/derived/m0/<episode>/episode.json
python -m vishwaroop.sim.replay --episode data/derived/m0/<episode> --repeats 3 --tolerance-file evals/M0-exit-tests.json
python -m vishwaroop.sim.negative_tests --episode data/derived/m0/<episode>   # 5/5 must be rejected
python tools/status_board.py --render > docs/STATUS_BOARD.md
```
Expected: validator prints `contract_valid`; replay report shows max deviation ≤ frozen tolerance on all 3 repeats and identical outcome labels; negative-test log shows 5 rejections with distinct reasons; `make check` green on the final commit.

## Exit criteria
ET-M0-1 … ET-M0-5 pass with evidence in the report. ET-M0-6 is WO-002.

## Stop conditions
Simulator unavailable or incompatible on any reachable machine; need for paid compute without an approval line; inability to restore the saved initial state deterministically; any step that would touch another repository; a replay tolerance that would have to be loosened after seeing results (report the failure instead). Preserve finished CPU work and write `reports/BLOCKER-<date>-m0.md`.

## Report
`reports/WO-001-m0-grounded-environment.md`
