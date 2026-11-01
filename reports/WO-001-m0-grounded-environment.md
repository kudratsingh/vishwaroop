# WO-001 — M0 grounded environment: real episodes, replay and evidence chain

**Status:** passed
**Date:** 2026-11-01 · **Author:** claude-code-vishwaroop · **Work order:** WO-001 · **Phase:** M0 · **Protocol version:** `m0-protocol-2`, `evals/M0-exit-tests.json` sha256 `22fbc41c88e549b97076725e61af6ce38d3ee8d0f3f6bb8f7cd7ecfcd4efadda`
**Program link:** PROGRAM §5.2 → vishwaroop M0

> Four words with fixed meanings throughout this report: **measured** (ran here, evidence attached), **estimated** (arithmetic from stated assumptions), **mocked/fixture** (fabricated for tests), **not run**.

## 1. Claim and scope
A scripted controller on ManiSkill3's `PickCubeSO100-v1` produces real successes and failures. Each is exported through contract v1, judged by an independent rubric, and replayed from its saved initial state alone with zero deviation. ET-M0-1 to ET-M0-5 pass.

Environment: simulation, CPU physics, on the owner's M3 Pro with MoltenVK. This is the simulated SO-100, not the owner's SO-101. **Nothing here says anything about a physical arm.** ET-M0-6 belongs to WO-002 and is **not run**. The Linux GPU path is **not run**.

## 2. Frozen method
Frozen before any episode existed, and unchanged here. The rubric is `m0-place-1`: lift at least 0.02 m, then over the last 10 steps stay within 0.015625 m of the target, within 0.005 m of the 0.0125 m rest height, not grasped, and moving at most 0.001 m per step. Replay compares `joint_position`, `object_position` and `target_position` over 3 repeats, with a maximum deviation of 0.001.

After a failed sweep, the recording path changed (`docs/adr/ADR-0006-record-from-the-restored-state.md`). **The tolerance did not change.**

The controller was tuned on seeds 0–39, and the failure offsets were corrected after a sweep on seeds 100–124, so those seeds are not fresh. The final sweep used seeds 100–149 and the sensitivity tool seeds 0–99, all in `train` blocks. My first planned probe named block 8; I changed it to block 1 before it ran. No seed in blocks 8–9 was simulated, so the `dev` holdout is untouched.

## 3. Reproduction
Stack lock: `config/stack-lock.resolved.json`, sha256 `4568316ba29226cd0d93401708f690f6cac09f1975976be73c8a894c91fb2d4e`, with the full environment in `config/robotics-requirements.macos.txt`. Evidence hashes: `artifacts/manifests/m0-first-episode.json`.

| Run | Code | Holds |
|---|---|---|
| `20261101T015203Z_24865645` | `5a80e67`, clean | the two episodes, their validation, replay, negative tests and inspection, and the sweep |
| `20261101T020129Z_136f5b62` | `7142fe2`, clean | the sensitivity measurement |

Between those commits only `src/vishwaroop/sim/sensitivity.py`, its tests, the kit manifest and the run ledger changed. The bytes are in git-ignored paths on the owner's Mac only.

From the repository root, with `VK_ICD_FILENAMES` set to MoltenVK's `MoltenVK_icd.json`, `PYTHONPATH=src`, and the robotics environment's Python:

```bash
python -m vishwaroop.sim.record --episode 12:nominal --episode 12:wrong-place \
    --tolerance-file evals/M0-exit-tests.json --out data/derived/m0/<commit>
python contracts/v1/validate.py <episode>/episode.json
python -m vishwaroop.sim.replay --episode <episode> --tolerance-file evals/M0-exit-tests.json \
    --repeats 3 --out runs/<run>/replay-<name>.json
python -m vishwaroop.sim.negative_tests --episode <episode> --tolerance-file evals/M0-exit-tests.json
python -m vishwaroop.sim.inspect_episode --episode <episode> --out runs/<run>/inspect-<name> --render
python -m vishwaroop.sim.sensitivity --first-seed 0 --seeds 100 --branch-seeds 20 \
    --tolerance-file evals/M0-exit-tests.json
python -m pytest tests/test_sim_maniskill.py -p no:cacheprovider
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

**Negative tests**, the same five rejections with distinct reasons on both episodes, each after the undamaged episode passed its own replay:
1. Corrupted action semantics: action spec fields differ from the recording.
2. Broken artifact hash: `initial-state.json` checksum mismatch.
3. Missing asset: `assets.json` missing.
4. Wrong timebase: `t_ns` shifted at step 0.
5. Intermediate-state forcing: state restored 558 times over 3 repeats.

**Inspection, 2 of 2 agree.** By a route that uses no rubric code, `inspect_episode` read the transitions directly and rendered 12 frames by replaying the recorded actions, and the rendered runs deviated 0.0 from the recordings. I looked at both contact sheets. In the success, the cube is lifted, carried, released, and rests under the goal marker with the arm clear. In the failure, the same grasp and carry end with the cube released and resting visibly to one side of the goal. Both match their labels and raw numbers. The agent that wrote the controller did this inspection. The independent review separately looked at a contact sheet for seed 14 and found its raw facts matched its label.

**Sweep**, seeds 100–149, each of 4 families, each replayed 3 times: 200 of 200 episodes had a deviation of exactly 0.0, with no invalid replay (Wilson 95% interval for "replay holds": 98.1% to 100%).

| Family | Rubric labels of 50 | Plan could not be made |
|---|---|---|
| `nominal` | `success` 50 | 0 |
| `missed-grasp` | `never_lifted` 50 | 0 |
| `no-release` | `still_grasped` 50 | 0 |
| `wrong-place` | `outside_target` 49, `success` 1 | 0 |

Nominal success on these seeds is 50 of 50 (Wilson 95% interval 92.9% to 100%). No seed in this range was unreachable; other seeds were, as below.

**Reach.** Six of seeds 0–99 cannot be planned (19, 27, 51, 67, 81, 91), because the far edge of the task area is beyond a straight-down pose. The arm then holds still, the rubric labels the episode `never_lifted`, and the manifest's notes say `planning_failed`.

**Sensitivity** is in ADR-0006. On the same actions, a 0.0000001 m change at the start exceeded the tolerance on 32 of 94 seeds.

**CPU tier:** `make check` green on a clean clone at `7142fe2`, with 481 passed and 6 skipped. The skipped ones are the simulator tests, **not run** there. **Simulator tier:** 6 of 6 passed at `5a80e67`.

## 5. Failure analysis
- **`wrong-place` seed 143 is a real success, not a mislabel.** The controller released 0.03 m off target, but as the jaws opened the cube moved 0.012 m and settled 0.015 m from the target, inside the 0.015625 m radius, as the transitions show. A family's name states its intent, and only the rubric states the outcome. WO-002 must count outcomes from the rubric.
- **The release moves the cube.** That jump is why the nominal plan ends a few millimetres off target, 0.0062 m on seed 12, and it is the natural source of near-threshold outcomes.
- **Recording straight after `reset` broke replay.** An early probe with superseded controller settings had 22 of 100 episodes over tolerance on seeds 100–124. The figure to rely on is ADR-0006's table. Seed 12's first replay passed at 0.0003 by luck: a third of seeds fail that way.
- **Independent review** (commit `622fa39`) found no way for ET-M0-3 to pass without real reproducibility. It raised these, each now closed unless marked:

| Finding | Disposition |
|---|---|
| Evidence not yet in the PR | this report and its manifest |
| Restore is inexact and undisclosed | ADR-0006 |
| A family could span `train` and `dev`, breaking protocol §3 | refused; regression tests |
| Inspection accepted tampered data and unsafe paths | validates first; regression tests |
| An environment id from a file could make Gymnasium import a module | only known ids accepted; validated first |
| Planning failures looked like ordinary `never_lifted` | `planning_failed` in the manifest's notes |
| GPU script passed without proving the GPU works | torch and GPU physics and rendering must work, or exit 4 |
| Script trusted a preset ICD, lost failure reasons, had wrong exit codes, had no tests past its checks | fixed, with tests for every failure path |
| Runs had no code commit | each is a ledgered run; manifest notes name the commit |
| Lock overstated what was tested | wording fixed; `not_applicable` is its own state |
| Solver returned tilted poses after its last iteration | it now checks tilt and direction; regression tests |
| **A hand-edited split still passes validator and replay** | **open: WO-002's registry must tie seed to block to partition** |

**Three of my own errors in this work order:**
- I committed `f22dd72` with a message describing a fix it did not contain, because a patch failed and `set -e` did not stop that shell. It was never pushed. I amended it to `7142fe2`, which holds the fix.
- `tools/check_hashes.py --write-kit-manifest` walks ignored folders, so it listed local evidence in `SHA256SUMS.json`. The commit above held that too. The manifest now comes from a clean export of the git index.
- I stored a negative-test log containing the Vulkan loader's stdout, which includes a scratch path. See section 9.

## 6. Cost and latency
$0: the owner's Mac, no paid compute, no line in `ledgers/costs.jsonl`. The sweep took about 180 s for 200 episodes, each recorded and replayed 3 times, about 820 control steps per second overall, including file writing (**estimated** from elapsed time and about 146,000 steps). The MoltenVK attempt itself took about a minute of its 1-hour cap.

## 7. Sealed access
None. M0's sealed budget is 0.

## 8. Exit tests and acceptance
| Exit test | Threshold (frozen) | Result | Evidence | Pass? |
|---|---|---|---|---|
| ET-M0-1 | 100% of CPU-tier checks green | all green, 481 passed; simulator tests skipped in this tier | clean clone at `7142fe2`; CI on the merged commit | yes |
| ET-M0-2 | `contract_valid`; zero null pins in the simulator section | `contract_valid` on both; no null in `simulator` | `validate-*.json`; `config/stack-lock.resolved.json` | yes |
| ET-M0-3 | max deviation ≤ 0.001 on all 3 repeats; identical label | 0.0 on all 3, on both episodes; labels identical | `replay-*.json` | yes |
| ET-M0-4 | 5/5 negative tests rejected; 2/2 inspected outcomes agree | 5/5 on both; 2/2 agree | `negative-*.out`; `inspect-*/` | yes |
| ET-M0-5 | specs present and hashed; holdout plan names run/family grouping; frozen events for every M1 exit test | all present, hashes match the latest `frozen` events, protocol §4 names the grouping, ET-M1-1 to 5 frozen | hashes below; `tests/test_evals_frozen.py` | yes |
| ET-M0-6 | ≥ 200 episodes, ≥ 30% failures, ≥ 3 failure modes, audit passes | **not run** | WO-002 | no |

ET-M0-2 is met as written. The lock also has a `not_needed_for_m0` section with four null entries for LeRobot and VLA pins, outside the simulator section and unresolved on purpose. Three simulator entries say `not_applicable` (image digest, CUDA, NVIDIA driver), because none exists on this Mac.

Hashes: `evals/M0-exit-tests.json` `22fbc41c88e549b97076725e61af6ce38d3ee8d0f3f6bb8f7cd7ecfcd4efadda`; `evals/M0-protocol.md` `977b189bce26190a880e69877d02805ca2b1d81d4e8aa0cf09242924424a52bd`; `evals/M1-exit-tests.json` `145858ec1ff0f1d259e24756b832f2ce2ffe3497a0a769d799f5008d70388f07`.

## 9. Limits
- **ET-M0-3 shows bit-exact reproducibility on one machine and one stack, not robustness.** Small changes at the start move a run past the tolerance, and mid-episode branches do not stay within it (ADR-0006). WO-005 must measure branches for itself.
- **Another CPU or operating system: not run.** Episodes recorded here are not claimed to replay elsewhere.
- **`scripts/setup_gpu_host.sh`: not run on Linux.** Only its logic is tested, against stubs, and `config/robotics-requirements.linux.txt` has never been installed.
- **The episodes exist in one place.** The bytes are on the owner's Mac, with hashes in the tracked manifest and no second copy.
- **A stored log trips this checkout's scan.** `artifacts/sha256/be/beaab0b3d5a7dd857d0e6d15f41d5b1dab02f37a65c6189e0f97bb88a2fd5cde`, the negative-test log, holds a scratch path from the loader's stdout. It is git-ignored and was never pushed, and it holds no secret. `make check` and `pytest` therefore fail on `test_repository_has_no_secrets_or_machine_paths` in this one checkout, and pass in a clean clone and in CI, which is where this work was verified. `AGENTS.md §6.1` forbids deleting it, so it stays until the owner decides.
- The cube's yaw is unknown to the controller, and its behaviour on seeds never run is **not run**.

## 10. Next bounded work order
**WO-002**, the M0 dataset, closes ET-M0-6. It must:
- tie seed to block to partition in its registry, closing the review's open finding;
- give `dev` its own families, since `record.py` refuses a `train` family on a `dev` seed;
- record what `planning_failed` episodes count as;
- count outcomes from the rubric, not from family names.

Rollback: reverting this PR restores the state where no real episode exists. Recorded data stays where it is.

Owner decisions: correct `PROGRAM.md §9`, which says ManiSkill3 does not run on the Macs (measured here: its CPU physics does); correct `PROGRAM.md §12` row 7, which still says no remote is designated; decide on the blob above. None blocks WO-002.

## 11. Retro note
- A sweep found in minutes what one good episode hid. Sweep before believing a single replay.
- `set -e` does not reliably stop a multi-line command in this shell. Chain real dependencies with `&&`, especially before a commit.
- The independent review was worth its half hour: it found the partition bug and the file-driven import.
- Sizing: L, as estimated.

## Errata (append-only)
