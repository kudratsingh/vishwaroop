# WO-022 | ET-M3-6's physics side on the Mac: datasets recorded, five arms trained, nothing scored

**Date:** 2026-11-08 · **Result:** done as scoped (**measured**, simulation and Mac MPS training, $0) · **ET-M3-6:** advanced, not closed

## Summary
Everything in ET-M3-6 that comes from physics now exists:
- the protocol §4 reproducibility gate;
- the evaluation family `m3-eval-missed-grasp`;
- the F2 and F1s recordings;
- the base, F_star and F1 sets;
- the five arms F0, F_star, F1, F1s and F2, each trained on seeds 0, 1 and 2, with sha256-hashed checkpoints.

**No arm has been scored.** By the owner's instruction (`approvals-20261108T081923998845Z-b8daa5a7`), block 16 and the no-harm set stay unscored until F3's protocol is frozen. The scoring command refuses while `F3_PROTOCOL` is unset and no scoring approval is listed.

ET-M3-6 passes or fails on F3, which needs a generator, a GPU, and a filter whose step 4 is ET-M3-1's check. ET-M3-1 is on hold, so ET-M3-6 cannot close in this work order.

## Owner decisions applied
All recorded in `approvals-20261108T081923998845Z-b8daa5a7`:

| Detail | Decision | In the code |
|---|---|---|
| 1. `insufficient_evidence` at the gate | **Vetoed.** The refusal stays, and exclusions are listed by reason. Definite failures, planning failures included, are kept when they pass replay. | `synth/m3_gate.py`; each result has `skipped_by_reason` |
| 2. Skipped F2 scenes | Approved. The operator alternation and the lateral-miss sign count advance over kept episodes only. | `et_m3_6_record.f2_choice` |
| 3. F1s when a nominal demo fails replay | Approved. The scene is skipped and listed, and F1s reports its scene overlap with F2 and its window counts separately. | `et_m3_6_record.f1s_overlap` |
| GPU stop wording | Clarified: rented, remote or CUDA GPU only. Local MPS at $0 is in scope. | WO-022 Stop conditions |
| Checkpoints | Saved and sha256-hashed. | `et_m3_6_train.checkpoint_record` |

## Code and review
The code was reviewed and rechecked as `AGENTS.md` §13.8 requires.

- **Review** (three lenses: fidelity, correctness, one-shot safety): 17 findings, 4 of them blockers, all fixed in `2d56c8d`. The blockers were:
  - a substring approval match that would have unlocked scoring from the owner's no-scoring record;
  - detail 1 still applied after the owner's veto;
  - a resume that skipped the snapshot check.
- **Recheck:** no blockers.
  - Its recording-side nits were fixed before recording (PR #49): the gated `episode.json` sha256 is pinned, and F1s must write where F2 wrote.
  - Its training-side nits were fixed before training (PR #51): `audit_splits` runs before every training run; seeds of an arm must have the same data and normalization; a test covers the checkpoint hash.
- **Where the code lives:**
  - `src/vishwaroop/synth/`: `m3_gate`, `m3_record`, `et_m3_6_record`, `et_m3_6_guard`;
  - `src/vishwaroop/models/`: `et_m3_6_data`, `et_m3_6_train`, `et_m3_6_rule`, `et_m3_6_score`;
  - tests: `tests/test_synth_m3_record.py`, `tests/test_synth_et_m3_6_guard.py`, `tests/test_synth_et_m3_6_data.py`, `tests/test_et_m3_6_train.py`, `tests/test_et_m3_6_rule.py`.

## Recordings
All were measured in simulation at clean commits, each run once.

| Set | Run | Commit | Seeds | Kept / skipped | Windows |
|---|---|---|---|---|---|
| `m3-eval-missed-grasp` (block 16) | `20261108T085827Z_7c4da015` | `8936f33` | 16000–16059 | 60 / 0 | not read (stays unread until scoring) |
| F2 (block 11) | `20261108T090103Z_293f1e74` | `a7ae8a9` | 11000–11028 | 29 / 0 | 4,167, of which 4,161 = W* used |
| F1s (block 11, F2's scenes) | `20261108T090335Z_9c50a729` | `beec8cc` | 11000–11026 | 27 / 0 | 4,161 = W* |

- **Evaluation family:** recorded before any arm was trained, from `m0-scripted-missed-grasp`'s PlanSettings exactly. Its labels, lengths and metrics were not read.
- **F2:** 15 `m3-synth-lateral-miss` and 14 `m3-synth-close-high` episodes. Rubric labels: 26 `never_lifted` and 3 `success`. Five episodes are planning failures, kept under the owner's decision. The last episode's 6 surplus windows are cut from its end.
- **F1s against F2:** 27 of F2's 29 scenes were used and none was skipped. 11027 and 11028 were not reached, because W* was met first, giving a scene overlap of 0.931. F1s's windows were 4,161 total and used, against F2's 4,167 total and 4,161 used. Rubric labels: 24 `success` and 3 `never_lifted`.
- **Reproducibility gate:** no scene failed it in any of the three sets, so no exclusion of any kind arose, `insufficient_evidence` included.
- **Split audit:** `audit_splits`, with scene groups as a holdout axis, passed over 436 episodes: the 320 of the M0 dataset plus 60 evaluation, 29 F2 and 27 F1s.

## Training
All runs were measured on the Mac's MPS. Each has 30 epochs, `carry-contact-beta-fall` with every hyperparameter as in `runs/20261102T041509Z_93dd348c`, and normalization from the 207-episode base only (`stats_sha256` `d153c2ce…`, identical in all 15 runs).

| Arm | Added windows | Total windows | Added-window digest | Runs (seeds 0, 1, 2) |
|---|---|---|---|---|
| F0 | 0 | 31,031 | — | `20261108T090800Z_53749cae`, `20261108T091052Z_4f6b8366`, `20261108T091347Z_a1527eba` |
| F_star | 4,161 (27 episodes) | 35,192 | `c750293c…` | `20261108T091651Z_d5c19360`, `20261108T092006Z_c1421822`, `20261108T092317Z_0377bdec` |
| F1 | 4,161 (frozen augmentation) | 35,192 | `aad369a7…` | `20261108T092624Z_802eaf36`, `20261108T092946Z_5e35bbaa`, `20261108T093258Z_ac50e18f` |
| F1s | 4,161 (27 episodes) | 35,192 | `f46319a3…` | `20261108T093607Z_eb1e4ace`, `20261108T093922Z_c0dd97a6`, `20261108T094235Z_5cb9e0eb` |
| F2 | 4,161 (29 episodes) | 35,192 | `5c83c2bf…` | `20261108T094547Z_2a3d4c89`, `20261108T094858Z_ec9634dd`, `20261108T095210Z_6cc0995d` |

- Each run's result JSON records its checkpoint path and sha256, and all 15 re-hash to the recorded value. Each checkpoint is 5.6 MB.
- Every arm's three seeds share one added-window digest, as `check_same_data` enforces. F1's windows are "drawn once and shared by all seeds".
- Median epoch time was 4.4 to 5.2 s, about 2.5 minutes per run. The exception is F2 seed 2, at 26.2 s per epoch (758 s), probably contention on the Mac: its data and normalization digests match seeds 0 and 1, and it did not resume.
- Training losses are in each result. They are training-set values, not ET-M3-6 metrics. Nothing was computed on block 16 or on the 23 no-harm episodes.

## Seeds
- **Used:** 16000–16059 (evaluation), 11000–11028 (F2 and F1s).
- **Not used:**
  - block 10;
  - the seeds held for ET-M3-1 (`ET_M3_1_HELD_SEEDS`);
  - blocks 18 and 19;
  - 16060–16099, which the evaluation rule allowed but did not need.

## What remains for ET-M3-6
F3 is the only arm that can pass the test. It needs:
- a generator (Pipeline A, M2a's observation model, or Pipeline B);
- GPU compute, which needs a separate owner approval or the workstation;
- F3's protocol, frozen with ET-M3-2's, which must state that F0, F_star, F1, F1s and F2 were trained but **not scored** when it was frozen;
- a filter whose step 4 is ET-M3-1's scene-consistency check, which is on hold.

After that, the scoring command needs `F3_PROTOCOL` set and an owner scoring approval listed, both in a reviewed commit.

## Environment notes
- The Mac's data volume was at 99% after training, with 6.0 GiB free. This work order added about 0.3 GB to `runs/` and `data/derived/`. The rest of the drop from about 10 GiB happened elsewhere on the machine during these runs.
- Two untracked paths are excluded in this checkout's local `.git/info/exclude`, so the clean-tree check was not tripped by files that are not code:
  - the workflow worktrees under `.claude/`;
  - another session's untracked `reports/REVIEW-2026-11-08-program-architecture-compute.md`.

  Neither is part of the run's code.
