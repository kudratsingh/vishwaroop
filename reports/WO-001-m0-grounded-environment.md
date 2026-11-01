# WO-001 — M0 grounded environment: real episodes, replay and evidence chain

**Status:** passed
**Date:** 2026-11-01 · **Author:** claude-code-vishwaroop · **Work order:** WO-001 · **Phase:** M0 · **Protocol version:** `m0-protocol-2`, `evals/M0-exit-tests.json` sha256 `22fbc41c88e549b97076725e61af6ce38d3ee8d0f3f6bb8f7cd7ecfcd4efadda`
**Program link:** PROGRAM §5.2 → vishwaroop M0

> Four words with fixed meanings throughout this report: **measured** (ran here, evidence attached), **estimated** (arithmetic from stated assumptions), **mocked/fixture** (fabricated for tests), **not run**.

## 1. Claim and scope
A scripted controller on ManiSkill3's `PickCubeSO100-v1` produces real successes and failures. Each is exported through the shared contract, judged by an independent rubric, and replayed from its saved initial state alone with zero deviation. ET-M0-1 to ET-M0-5 pass.

Environment: simulation, CPU physics, on the owner's M3 Pro with MoltenVK, which the owner made M0's platform of record. This is the simulated SO-100, not the owner's SO-101. **Nothing here says anything about a physical arm.** ET-M0-6 belongs to WO-002 and is **not run**. The Linux GPU path is **not run**.

## 2. Frozen method
Frozen before any episode existed, and unchanged here. The rubric is `m0-place-1`: lift at least 0.02 m, then over the last 10 steps stay within 0.015625 m of the target, within 0.005 m of the 0.0125 m rest height, not grasped, and moving at most 0.001 m per step. Replay compares `joint_position`, `object_position` and `target_position` over 3 repeats, with a maximum deviation of 0.001.

After a failed sweep, the recording path changed (`docs/adr/ADR-0006-record-from-the-restored-state.md`). **The tolerance did not change.**

The controller was tuned on seeds 0–39, and the failure offsets were corrected after a sweep on seeds 100–124, so those seeds are not fresh. The final sweep used seeds 100–149 and the sensitivity tool seeds 0–99, all in `train` blocks. No seed in blocks 8–9 was simulated in any ledgered run, so the `dev` holdout is untouched. Early probes before the ledger existed have no record of their own.

## 3. Reproduction
Stack lock: `config/stack-lock.resolved.v2.json`, sha256 `f8db517142b3d720192fa51e23965d6637667d90c492519764503d79f6da19be`, with the full environment in `config/robotics-requirements.macos.v2.txt`: Python 3.12.13, `mani_skill` 3.0.1, `sapien` 3.0.3, `torch` 2.15.0, `ironclad-kit` 1.1.0, MoltenVK v1.4.2. Evidence hashes: `artifacts/manifests/m0-first-episode-v2.json`. Outcome code: `src/vishwaroop/outcome/pickplace.py`, sha256 `5cac5f27bfcf088151e6b4cfd7fc1507ff842b6b2f003e58812d580205f6f323`.

| Run | Code | Holds |
|---|---|---|
| `20261101T051303Z_16437bc4` | `1a51273`, clean | the two episodes, their validation, replay, negative tests and inspection |
| `20261101T051337Z_31331650` | `900d9f5`, clean | the sweep |
| `20261101T051759Z_e444ac57` | `50eebe9`, clean | the sensitivity measurement |

The later two commits add only ledger lines to the first. The run ledger is tracked, so commit it between runs, or the next run records itself as dirty. The bytes are in git-ignored paths on the owner's Mac only.

From the repository root, with `VK_ICD_FILENAMES` set to MoltenVK's `MoltenVK_icd.json`, `PYTHONPATH=src`, and the robotics environment's Python:

```bash
python -m vishwaroop.sim.record --episode 12:nominal --episode 12:wrong-place \
    --tolerance-file evals/M0-exit-tests.json --out data/derived/m0/<commit>
ironclad-validate <episode>/episode.json
python -m vishwaroop.sim.replay --episode <episode> --tolerance-file evals/M0-exit-tests.json \
    --repeats 3 --out runs/<run>/replay-<name>.json
python -m vishwaroop.sim.negative_tests --episode <episode> \
    --tolerance-file evals/M0-exit-tests.json --out runs/<run>/negative-<name>.json
python -m vishwaroop.sim.inspect_episode --episode <episode> --out runs/<run>/inspect-<name> --render
python -m vishwaroop.sim.sweep --first-seed 100 --seeds 50 --tolerance-file evals/M0-exit-tests.json
python -m vishwaroop.sim.sensitivity --first-seed 0 --seeds 100 --branch-seeds 20 \
    --tolerance-file evals/M0-exit-tests.json
python -m pytest tests/test_sim_maniskill.py -o addopts="" -p no:cacheprovider
```

## 4. Results
All **measured** unless marked.

**The two evidence episodes, seed 12:**

| | `m0-scripted-nominal` | `m0-scripted-wrong-place` |
|---|---|---|
| Contract validator | `contract_valid` | `contract_valid` |
| Rubric | `success` | `outside_target`, 0.0349 m from the target |
| Steps | 185 | 185 |
| Replay deviation, 3 repeats | 0.0, 0.0, 0.0 | 0.0, 0.0, 0.0 |
| Replay labels | `success` × 3 | `outside_target` × 3 |
| Peak cube height | 0.0524 m | 0.0554 m |
| Final distance to target | 0.0062 m | 0.0349 m |
| Negative tests rejected | 5 of 5 | 5 of 5 |

**Negative tests**, five rejections with distinct reasons on each episode, each after the undamaged episode passed its own replay: corrupted action semantics, broken artifact hash, missing asset, wrong timebase, and intermediate-state forcing.

**Inspection, 2 of 2 agree.** `inspect_episode` validated each episode, read the transitions without using any rubric code, and rendered 12 frames by replaying the recorded actions. The rendered runs deviated 0.0 from the recordings. I looked at both contact sheets. In the success, the cube is lifted, carried, released, and rests under the goal marker with the arm clear. In the failure, the same grasp and carry end with the cube resting visibly to one side of the goal. Both match their labels and raw numbers. The agent that wrote the controller did this inspection. The second independent review looked at both sheets of the earlier recording, whose physical streams are identical, and reached the same view.

**Sweep**, seeds 100–149, each of 4 families, each replayed 3 times: 200 of 200 episodes had a deviation of exactly 0.0, with no invalid replay (Wilson 95% interval for "replay holds": 98.1% to 100%).

| Family | Rubric labels of 50 | Plan could not be made |
|---|---|---|
| `nominal` | `success` 50 | 0 |
| `missed-grasp` | `never_lifted` 50 | 0 |
| `no-release` | `still_grasped` 50 | 0 |
| `wrong-place` | `outside_target` 49, `success` 1 | 0 |

Nominal success on these seeds is 50 of 50 (Wilson 95% interval 92.9% to 100%). On seeds 0–99 it is 94 of 100, by the review's measurement, and all six failures are the unreachable seeds below.

**Reach.** For `nominal` and `no-release`, six of seeds 0–99 cannot be planned (19, 27, 51, 67, 81, 91), because the far edge of the task area is beyond a straight-down pose. `missed-grasp` and `wrong-place` place their waypoints differently and fail on subsets of these: the review measured that `missed-grasp` plans 19, 27, 51 and 81, and `wrong-place` plans 67 and 91. The arm then holds still, the rubric labels the episode `never_lifted`, and the manifest's notes say `planning_failed`.

**Sensitivity** is in ADR-0006. On the same actions, a 0.0000001 m change at the start exceeded the tolerance on 31 of 94 seeds.

**Python 3.12 against 3.11.** Evidence was first recorded on 3.11, at `5a80e67`, run `20261101T015203Z_24865645`, and `artifacts/manifests/m0-first-episode.json` keeps that record. `ironclad-kit` requires 3.12, so the stack moved (ADR-0007). On seed 12, every observed stream of both episodes is identical across the two stacks, and the commanded actions differ by at most 8e-12. The replay command refuses the 3.11 episode under the 3.12 stack, which is the owner's rule: replay is claimed only on the same stack.

**CPU tier:** `make check` green on a clean clone at `1a51273`, with 527 passed, 8 skipped and 1 deselected. The skipped ones are the simulator tests, **not run** there. **Simulator tier:** 8 of 8 passed at `1a51273`.

## 5. Failure analysis
- **`wrong-place` seed 143 is a real success, not a mislabel.** The cube was 0.0267 m off when released, but as the jaws opened it moved 0.0119 m and settled 0.0150 m from the target, inside the 0.015625 m radius. A family's name states its intent, and only the rubric states the outcome. WO-002 must count outcomes from the rubric.
- **Most of the nominal offset comes before the release.** On seed 12, the cube is 0.0049 m off at the last grasped sample, the release moves it 0.0031 m, and it ends 0.0062 m off. Over 144 planned nominal seeds, by the review's measurement, the median is 0.0051 m before release and 0.0049 m at the end, with a median jump of 0.0016 m. The release sometimes moves the cube much further, as seed 143 shows, which is a natural source of near-threshold outcomes.
- **Recording straight after `reset` broke replay.** An early probe with superseded controller settings had 22 of 100 episodes over tolerance on seeds 100–124; its output was not kept, so rely on ADR-0006's table. Seed 12's first replay passed at 0.0003 by luck: a third of seeds fail that way.
- **Independent reviews.** The first (at `622fa39`) and second (at `928055a`) found no way for ET-M0-3 to pass without real reproducibility, and the second reproduced every ET-M0-1 to 5 number. They raised these, each now closed unless marked:

| Finding | Disposition |
|---|---|
| Restore is inexact and undisclosed | ADR-0006 |
| A family could span `train` and `dev`, breaking protocol §3 | refused; regression tests |
| Inspection accepted tampered data and unsafe paths; an environment id from a file could import a module | validates first; only known ids accepted; regression tests |
| Planning failures looked like ordinary `never_lifted` | `planning_failed` in the manifest's notes |
| GPU script passed without proving the GPU works; trusted a preset ICD; lost reasons; wrong exit codes | fixed, with tests on the failure paths, including the GPU check's own code against fake modules |
| Runs had no code commit; the commit could be false or absent; a stopped run stayed `started` | every simulator command is a ledgered run, from its own checkout, with git; SIGINT and SIGTERM close it as `interrupted` |
| The sweep's headline figure was outside any run | `vishwaroop.sim.sweep` is a committed, ledgered command |
| Render trust check and sensitivity cases had no test that could fail | tests now fail on those mutations |
| Lock overstated what was tested | wording fixed; `not_applicable` is its own state |
| Solver returned tilted poses after its last iteration | it now checks tilt and direction; regression tests |
| **A hand-edited split still passes validator and replay** | **open: WO-002's registry must tie seed to block to partition** |
| **A hard kill (SIGKILL, a crash) still leaves a run `started`** | **open by nature; the ledger shows it as unfinished** |
| **A file edited and correctly re-hashed passes validation.** Replay and `--render` catch it against physics; reading its facts without `--render` does not | **open by design: `ironclad verify` and validation catch mistakes, not forgery** |

**Three of my own errors in this work order:**
- I committed `f22dd72` with a message describing a fix it did not contain, because a patch failed and `set -e` did not stop that shell. It was never pushed. I amended it to `7142fe2`. The owner has since said to fix a bad commit with a new commit, even before pushing.
- `tools/check_hashes.py --write-kit-manifest` walked ignored folders, so that commit also listed local evidence. That tool is gone since WO-011.
- I stored a negative-test log containing the Vulkan loader's stdout, which includes a scratch path. See section 9.

## 6. Cost and latency
$0: the owner's Mac, no paid compute, no line in `ledgers/costs.jsonl`. The sweep took about 3 minutes for 200 episodes, each recorded and replayed 3 times, about 800 control steps per second overall, including file writing (**estimated** from elapsed time and about 146,000 steps). The MoltenVK attempt took about a minute of its 1-hour cap. A Mac crash wiped the scratch folder, and on the owner's new approval MoltenVK was downloaded again, with the same sha256, to `~/.cache/vishwaroop-robotics`.

## 7. Sealed access
None. M0's sealed budget is 0.

## 8. Exit tests and acceptance
| Exit test | Threshold (frozen) | Result | Evidence | Pass? |
|---|---|---|---|---|
| ET-M0-1 | 100% of CPU-tier checks green | all green, 527 passed; simulator tests skipped in this tier | clean clone at `1a51273`; CI run ids on the merged commit in the `passed` event | yes |
| ET-M0-2 | `contract_valid`; zero null pins in the simulator section | `contract_valid` on both; no null in `simulator` | `validate-*.json`; `config/stack-lock.resolved.v2.json`; episode hashes in the manifest | yes |
| ET-M0-3 | max deviation ≤ 0.001 on all 3 repeats; identical label | 0.0 on all 3, on both episodes; labels identical | `replay-*.json` | yes |
| ET-M0-4 | 5/5 negative tests rejected; 2/2 inspected outcomes agree | 5/5 on both; 2/2 agree | `negative-*.json`; `inspect-*/`; outcome code hash in section 3 | yes |
| ET-M0-5 | specs present and hashed; holdout plan names run/family grouping; frozen events for every M1 exit test | all present, hashes match the latest `frozen` events, protocol §4 names the grouping, ET-M1-1 to 5 frozen | hashes below; `tests/test_evals_frozen.py` | yes |
| ET-M0-6 | ≥ 200 episodes, ≥ 30% failures, ≥ 3 failure modes, audit passes | **not run** | WO-002 | no |

ET-M0-2 is met as written. The lock also has a `not_needed_for_m0` section with four null entries for LeRobot and VLA pins, outside the simulator section and unresolved on purpose. Three simulator entries say `not_applicable` (image digest, CUDA, NVIDIA driver), because none exists on this Mac. The frozen text says `contracts/v1/writer.py`, and `docs/adr/ADR-0007-adopt-ironclad.md` maps that path to `ironclad.contracts.v1.writer`, which is what wrote these episodes. No schema or fixture byte differs.

Hashes: `evals/M0-exit-tests.json` `22fbc41c88e549b97076725e61af6ce38d3ee8d0f3f6bb8f7cd7ecfcd4efadda`; `evals/M0-protocol.md` `977b189bce26190a880e69877d02805ca2b1d81d4e8aa0cf09242924424a52bd`; `evals/M1-exit-tests.json` `145858ec1ff0f1d259e24756b832f2ce2ffe3497a0a769d799f5008d70388f07`.

## 9. Limits
- **ET-M0-3 shows bit-exact reproducibility on one machine and one stack, not robustness.** Small changes at the start move a run past the tolerance, and mid-episode branches do not stay within it (ADR-0006). WO-005 must measure branches for itself.
- **Another CPU or operating system: not run.** By the owner's decision, Linux replay and negative tests are re-run before Linux-recorded data is used in M1, and replay platforms are not mixed.
- **`scripts/setup_gpu_host.sh`: not run on Linux.** Only its logic is tested, against stubs, and `config/robotics-requirements.linux.txt` has never been installed.
- **The episodes exist in one place.** The bytes are on the owner's Mac, with hashes in the tracked manifest and no second copy.
- **One known local test failure.** `artifacts/sha256/be/beaab0b3d5a7dd857d0e6d15f41d5b1dab02f37a65c6189e0f97bb88a2fd5cde`, an earlier negative-test log, holds a scratch path from the loader's stdout. It is git-ignored and was never pushed, and it holds no secret. The scan and its test therefore fail in the owner's checkout only, and pass in a clean clone and in CI, which is where this work was verified. By the owner's decision it stays as a record, and the real fix is in `ironclad`.
- The cube's yaw is unknown to the controller, and its behaviour on seeds never run is **not run**.

## 10. Next bounded work order
**WO-002**, the M0 dataset, closes ET-M0-6. It must:
- tie seed to block to partition in its registry, closing the review's open finding;
- give `dev` its own families, since `record.py` refuses a `train` family on a `dev` seed;
- record what `planning_failed` episodes count as;
- count outcomes from the rubric, not from family names.

Rollback: reverting this PR restores the state where no real episode exists. Recorded data stays where it is.

`PROGRAM.md §9` and `§12` row 7 go to `ironclad`'s v1.2.0 text release, by the owner's decision.

## 11. Retro note
- A sweep found in minutes what one good episode hid. Sweep before believing a single replay.
- `set -e` does not reliably stop a multi-line command in this shell. Chain real dependencies with `&&`, especially before a commit.
- Independent reviews were worth their cost: they found the partition bug, the file-driven import, and report text that would have become permanent.
- Keep nothing that must survive a restart under `/private/tmp`.
- Sizing: L, as estimated.

## Errata (append-only)
