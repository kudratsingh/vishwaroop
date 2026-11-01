# WO-002 — M0 dataset: scripted and perturbed episodes with successes and failures

**Status:** passed
**Date:** 2026-11-01 · **Author:** claude-code-vishwaroop · **Work order:** WO-002 · **Phase:** M0 · **Protocol version:** `m0-protocol-2`, `evals/M0-exit-tests.json` sha256 `22fbc41c88e549b97076725e61af6ce38d3ee8d0f3f6bb8f7cd7ecfcd4efadda`
**Program link:** PROGRAM §5.2 → vishwaroop M0

> Four words with fixed meanings throughout this report: **measured** (ran here, evidence attached), **estimated** (arithmetic from stated assumptions), **mocked/fixture** (fabricated for tests), **not run**.

## 1. Claim and scope
M0 now has a dataset with both successes and failures: 320 real simulated episodes, each validated by the contract, with splits audited and checked against their seeds. ET-M0-6 passes. Environment: simulation on the owner's M3 Pro with CPU physics, M0's platform of record. This is the simulated SO-100, and **nothing here says anything about a physical arm**. No model was trained.

## 2. Frozen method
ET-M0-6, frozen before any episode: at least 200 episodes, at least 30% failures, at least 3 distinct failure modes, and `audit_splits` passes. Outcomes come only from the frozen rubric `m0-place-1`. Splits follow `evals/M0-protocol.md §3`: blocks 0–7 `train`, blocks 8–9 `dev`, each family wholly in one partition, and each run in one partition.

`evals/M0-dataset-plan.json`, sha256 `c45c646f9839dc67bf7b2debd9dd8068c6e74df085480c53c90416b9d3713f23`, was committed before collection. I lowered `nominal` from 120 to 80 while writing it, before any of this data existed, to give a margin over the 30% bar. `train` uses block 2, which no earlier tuning or sweep touched, and `dev` uses block 8.

| Family | Partition | Episodes | What it changes |
|---|---|---|---|
| `nominal` | train | 80 | nothing |
| `missed-grasp` | train | 30 | grasps 0.04 m off |
| `no-release` | train | 30 | never opens |
| `wrong-place` | train | 30 | places 0.03 m off |
| `noisy-actions` | train | 40 | 0.01 rad of seeded noise on the arm joints |
| `early-release` | train | 30 | opens at carrying height |
| `timeout` | train | 20 | stops at step 120 |
| `dev-grasp-offset` | dev | 20 | grasps 0.012 m off |
| `dev-place-offset` | dev | 20 | places 0.016 m off |
| `dev-noisy-actions` | dev | 20 | 0.02 rad of seeded noise |

## 3. Reproduction
Stack lock: `config/stack-lock.resolved.v2.json`. Manifest: `artifacts/manifests/m0-dataset-v1.json`, sha256 `267d77ead98119715350f0fc82987e715f7ce41a4d0337401b7469206711b9c7`, holding every episode's hashes, groups, seed and label.

| Run | Code | Partition | Episodes |
|---|---|---|---|
| `20261101T053745Z_fe51550b` | `7cbe9ee`, clean | train | 260 |
| `20261101T053940Z_87e0fa2c` | `f19c5d7`, clean | dev | 60 |

`f19c5d7` adds only the first run's ledger lines. From the repository root, in the robotics environment for `collect`:

```bash
python -m vishwaroop.sim.collect --config evals/M0-dataset-plan.json --partition train \
    --tolerance-file evals/M0-exit-tests.json --out data/derived/m0-dataset/<commit>
python -m vishwaroop.sim.collect --config evals/M0-dataset-plan.json --partition dev \
    --tolerance-file evals/M0-exit-tests.json --out data/derived/m0-dataset/<commit>
ironclad-audit-splits data/derived/m0-dataset/<commit>/*/episode.json
python -m vishwaroop.data.registry build --root data/derived/m0-dataset/<commit> \
    --out artifacts/manifests/m0-dataset-v1.json
python -m vishwaroop.data.registry summarize artifacts/manifests/m0-dataset-v1.json
```

## 4. Results
All **measured**.

| | Count |
|---|---|
| Episodes | 320 (260 train, 60 dev) |
| `success` | 159 |
| `never_lifted` | 66, of which 27 are `planning_failed` |
| `outside_target` | 50 |
| `still_grasped` | 45 |
| Failures | 161 of 320, 50.3% (Wilson 95% interval 44.9% to 55.8%) |
| Failures without planning failures | 134 of 293, 45.7% (Wilson 95% interval 40.1% to 51.5%) |
| Failure modes | 3 |
| `audit_splits` | `declared_group_and_lineage_checks_passed` |
| Sampled replays, the first 3 seeds of each family, 3 repeats each | 30 of 30 valid, all at 0.0 |

| Family | `success` | `never_lifted` | `still_grasped` | `outside_target` |
|---|---|---|---|---|
| `nominal` | 67 | 12 | 0 | 1 |
| `missed-grasp` | 0 | 30 | 0 | 0 |
| `no-release` | 0 | 3 | 27 | 0 |
| `wrong-place` | 0 | 0 | 0 | 30 |
| `noisy-actions` | 34 | 5 | 0 | 1 |
| `early-release` | 27 | 3 | 0 | 0 |
| `timeout` | 0 | 2 | 18 | 0 |
| `dev-grasp-offset` | 8 | 11 | 0 | 1 |
| `dev-place-offset` | 4 | 0 | 0 | 16 |
| `dev-noisy-actions` | 19 | 0 | 0 | 1 |

**The review's open finding is closed.** On a scratch copy of a real episode, I changed the split to `dev`. The contract validator still passed it, and the registry refused it: `seed 2000 belongs to train, but its split says dev`. `registry build` refuses a whole set holding one such episode. WO-002's own review then found that `purpose`, `suite_id`, `inherited_from_parent`, the declared outcome and the unhashed `planning_failed` note could still be edited unnoticed, so the registry now checks those too, and compares the set with the plan and each session with the run ledger. Rebuilt with those checks, the 320 real episodes pass and give the same manifest apart from its date. Like the other checks, this catches mistakes, not forgery: someone who edits the seed and re-hashes the state can defeat it.

## 5. Failure analysis
- **Planning failures are 27 of the 66 `never_lifted` episodes, 12 of them in `nominal`.** They hold still because a waypoint is out of reach, and the manifest marks each one. Reach depends on the waypoints, so families are not matched: on seed 2009, `wrong-place` plans and runs while six other train families cannot. `nominal`'s 12 of 80 here is higher than the 6 of 100 on seeds 0–99. They count as failures, since the controller did fail, and the frozen share holds with or without them. Anyone training on this data can tell them apart: they are 15 steps long and carry no contact.
- **`nominal` reached 67 of 68 planned episodes** (Wilson 95% interval 92.1% to 99.7%). The other seed ended `outside_target`.
- **Failure families do not always fail.** `early-release` succeeded 27 times: dropped from about 5 cm, the cube mostly lands in the target. It is a poor failure family, and useful as contact data. Counts come from the rubric, not from family names.
- **`dev-grasp-offset` shows a real threshold:** an offset of 0.012 m misses on some seeds and holds on others (8 successes, 11 misses with a plan made, 1 `outside_target`). Why a given seed holds was not investigated.
- **Only 3 failure modes, the frozen minimum.** `not_on_table` and `not_settled` never occurred, so a learned model sees no examples of them from this dataset.
- **Out-of-range object poses were not collected.** WO-002's scope lists them, but `evals/M0-protocol.md §3` freezes M0's shift axes to placement by seed.

## 6. Cost and latency
$0: the owner's Mac. Collection took about 2.5 minutes for 320 episodes and 30 sampled replays, 112 MB on disk (**measured**, from file sizes and ledger times). `collect` checks for 5 GB free before each episode, and stops at 1800 s per run.

## 7. Sealed access
None. M0's sealed budget is 0, and no `sealed` partition exists.

## 8. Exit tests and acceptance
| Exit test | Threshold (frozen) | Result | Evidence | Pass? |
|---|---|---|---|---|
| ET-M0-6 | ≥ 200 episodes; ≥ 30% failures; ≥ 3 distinct failure modes; `audit_splits.py` passes | 320; 50.3%; 3; passed | `artifacts/manifests/m0-dataset-v1.json`; `runs/20261101T053940Z_87e0fa2c/audit-splits.json` | yes |

The frozen text names `audit_splits.py`, which is `ironclad-audit-splits` since ADR-0007. ET-M0-1 to 5 passed in WO-001, so this completes M0's exit tests. On acceptance, the tag `v0.1.0` marks M0's pass (`AGENTS.md §4.7`). It proves that these exit tests passed on this stack, for the simulated SO-100, and nothing about a physical arm.

## 9. Limits
- **Replay was sampled, not exhaustive:** 30 of 320 episodes here, and those are each family's first three seeds, so no planning failure is among them. WO-001's sweep is the wider evidence on this stack.
- **Replay is claimed only on this stack.** By the owner's decision, Linux replay and negative tests are re-run before Linux-recorded data is used in M1, and replay platforms are not mixed.
- **These episodes exist in one place:** git-ignored on the owner's Mac, with hashes in the tracked manifest and no second copy.
- **One known local test failure.** `artifacts/sha256/be/beaab0b3d5a7dd857d0e6d15f41d5b1dab02f37a65c6189e0f97bb88a2fd5cde`, an earlier negative-test log, holds a scratch path from the Vulkan loader's stdout, and no secret. `ironclad-scan-secrets` and its test therefore fail in the owner's checkout only, and pass in a clean clone and in CI, where this work was verified. By the owner's decision it stays as a record until `ironclad`'s fix ships.
- `audit_splits` itself says it gives no guarantee against undeclared confounders.

## 10. Next bounded work order
WO-004, M1 predictors, whose prerequisites include the owner-run Linux GPU machine by the owner's decision. Rollback: reverting this PR removes the collector and registry. Recorded data stays where it is.

## 11. Retro note
- Writing the plan before collecting, and sizing it with margin, kept the frozen bar from becoming a temptation.
- The disk guard is new here, after another project's setup filled the disk and crashed the Mac.
- Sizing: M, as estimated.

## Errata (append-only)
