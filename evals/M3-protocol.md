# M3 protocol (`m3-protocol-1`)

Frozen 2026-11-06, before any M3 scene, snapshot, operator datum or generated datum exists. The owner accepted the M3 design's defaults D1 to D8 on 2026-11-06 (`ledgers/approvals.jsonl`), including D5, the seed blocks below. This file extends `evals/M0-protocol.md`, which still governs blocks 0 to 9 and the task. An independent three-lens review checked it before freezing.

## 1. Task
`PickCubeSO100-v1` on Mac CPU physics, exactly as `evals/M0-protocol.md` defines it, with the frozen rubric `m0-place-1` and replay tolerance.

## 2. Seed blocks and partitions
Blocks of 1,000 seeds; a scene's `scene_group_id` is `m3-seed-block-<n>`.

| Blocks | Partition | Use |
|---|---|---|
| 10 to 15 | train | scene sources, operator and generated data, generator, IDM and SFT training |
| 16 | dev | the held-out-family evaluation (ET-M3-6) |
| 17 | dev | the ET-M3-3 evaluation suite |
| 18 to 19 | reserved | never simulated; a future sealed suite, once the owner decides where sealed data lives |

M3 never uses blocks 0 to 9 for new data. M3 reads M0's train partition as M1 did, subject to §2a, and treats M1's dev blocks (8 and 9) as regression-only for any model trained with M3 data. A family lies wholly in one partition. Synthetic descendants inherit their parent's partition. `audit_splits.py` runs on every M3 manifest. Loaders and recorders take an M3 seed's partition from this table, refuse blocks 18 and 19, and refuse any dev-block seed (8, 9, 16, 17) in a training set.

## 2a. Leak rules
1. No operator reproduces the settings of any family in `sim/baseline.py` `VARIANTS` (missed-grasp grasp offset (−0.04, 0) along x; wrong-place place offset −0.03 along x; early-release place height 0.05; arm noise 0.01 and 0.02; dev-grasp-offset −0.012 along x; dev-place-offset −0.016 along x), nor M1's branch chunks exactly (constant arm offsets of 0.05 and 0.15 rad; the 10-step gripper inversion).
2. No generator, observation model, tokenizer or IDM whose output enters any M3 arm, and nothing used to set its filter's tolerances, is trained or tuned on `m0-scripted-missed-grasp` (or any later M3 target family), on any dev family (blocks 8, 9, 16, 17), on any `m3-eval-` family, or on frames from blocks 16 to 19. Its training manifest is listed with the arm and passes `audit_splits.py` against this rule before any candidate is generated.
3. M0's train partition may be read for M3 training only under rule 2.

## 3. Scene snapshots
For each M3 seed, before anything is generated or recorded from it:
1. `ManiSkillPickCube.reset(seed)`, then `save_state()`, then `restore_state()` of that saved state: the ADR-0006 path, so recordings and replays start the same way.
2. A write-once snapshot manifest records: the seed and block; the saved initial state's sha256; `asset_manifest()`, `configuration()` and `stack_identity()` with their sha256; the task id and version; the cube half size (0.0125 m) and colour (red); the goal position; the human render camera's pose and intrinsics, and the cube's mass and friction where the environment exposes them (otherwise a statement of what `configuration()` contains); and the initial 512 × 512 human render, with its sha256.

## 4. Reproducibility gate
Before a scene is used for a recorded episode that enters training or evaluation, that episode is replayed from the saved initial state 3 times. A scene whose replay exceeds the frozen 0.001 tolerance (`evals/M0-exit-tests.json`), or whose outcome label differs between repeats, is excluded and listed. Where a count is frozen, seeds are taken in ascending order from the stated first seed, skipping and listing every scene that fails, until the count is met. ET-M3-1's candidates are exempt: the checker replays nothing.

## 5. Identities
Family ids are `m3-<kind>-<name>`: `m3-synth-<operator>` for operator data, `m3-eval-<target>` for evaluation families. Run ids are new. A family that copies an M0 family's settings for evaluation gets a new `m3-eval-` id, and the M0 id is excluded from every training set that evaluates on it, except ET-M3-6's reference arm F_star, which exists to include it and never counts toward a pass.

## 6. What was known before this freeze
- Three renders of train seeds 7000 to 7002 (block 7), to see the scene's colours: the cube is one red component of about 600 pixels at 512 × 512, and the goal sphere is green and splits when the arm covers it. Nothing was recorded or measured from them.
- All on M0 train data: the target family's holdout results under this model (WO-005 stage 0, reproduced by WO-020: joints −62.9% at horizon 1, the error in `moved_before_grasp`, 7.1 mrad over 244 windows), which shaped the choice of operators; and WO-004's epochs rule, which chose 30 epochs partly on the `m0-scripted-missed-grasp` holdout.
- No block 10 to 19 data exists.
