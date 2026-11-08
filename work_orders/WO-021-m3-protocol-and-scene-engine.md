# WO-021 | M3: protocol, scene engine and the scene-consistency check (ET-M3-1)
**Phase:** M3
**Exit tests advanced:** ET-M3-1
**Size:** M
**Prerequisites:** WO-020 accepted; the owner's acceptance of D1 to D8 (2026-11-06).
**Authorization:** AGENTS §2.1 only. The Mac, $0. Owner, 2026-11-06: "Continue with the M3 scene engine on the Mac at $0. Freeze the missed-grasp held-out-family test before generating operator data."
**Files:** `evals/M3-protocol.md`, `evals/M3-exit-tests.json`, `evals/M3-checker-tolerances.json`, `config/phases.json`, `docs/PHASES.md`, `src/vishwaroop/synth/`, `tests/`, `artifacts/manifests/`, `work_orders/`, `reports/WO-021-m3-protocol-and-scene-engine.md`, ignored `runs/` and `data/derived/`.

## Objective
Freeze M3's protocol and exit tests before any M3 data exists: seed blocks 10 to 19, the leak rules, ET-M3-1's details and the held-out-family test ET-M3-6 with `missed-grasp` as its target. Then build the scene engine and close ET-M3-1. The engine covers scene snapshots, the operators, the consistency checker and the mismatch injector. The reproducibility gate (protocol §4) is not needed for ET-M3-1, whose candidates are exempt, so it moves to the next work order with F2 and the evaluation family.

## Scope
1. Freeze `evals/M3-protocol.md` and `evals/M3-exit-tests.json`, with their sha256 in the status ledger, before any scene is created.
2. Build `src/vishwaroop/synth/`: M3 seed partitions; snapshots; renders; the two operators; the injector; the checker. `make synth-test` runs the tests that need numpy and scipy, which the CPU tier skips.
3. Run the tolerance pilot on block 10 seeds 10900 to 10919. Write `evals/M3-checker-tolerances.json` from it by the frozen rule, and record its sha256 in the status ledger.
4. Generate the 60 controls and 60 injections, run the checker once, and report ET-M3-1.

## Out of scope
F2's operator data for ET-M3-6, the evaluation family's recording, any training, any generator, and any GPU work (D4). Those come in the next work order.

## Verification
`make check`, then the engine's commands at clean commits. Negative tests: each injection type on fabricated frames; a refused second scoring; a seed in a reserved or dev block refused for training.

## Exit criteria
Done when ET-M3-1 is reported as passed or failed under the frozen rule. It closes an exit test, so `AGENTS.md §13.8` asks for one review plus one recheck.

## Stop conditions
A pilot that cannot fit a band inside the frozen limits (the owner is told); any need for blocks 0 to 9 or 18 to 19; any GPU or paid work.

## Report
`reports/WO-021-m3-protocol-and-scene-engine.md`

## Progress (append-only)
- **2026-11-07, the tolerance pilot stopped by its frozen rule.** Run `20261107T083058Z_83f404c3`, at clean `5ca439e`. In unmodified pilot frames the cube's visible area was 0.176 to 1.938 of the snapshot's: smallest at seed 10900, frame 90, with the gripper over it; largest at seed 10908, frame 185, placed nearer the camera. The widened band, [0.158, 2.131], is outside the frozen 0.36 < a_lo and a_hi < 2.56. No tolerances file, control or injection exists. ET-M3-1 waits for the owner's decision on `m3-protocol-2`.
- **2026-11-07, the owner chose option A; `m3-protocol-2` drafted, reviewed and rechecked before freezing.**
  - ET-M3-1 under `m3-protocol-1` is recorded as failed (`reports/WO-021-et-m3-1-protocol-1.md`).
  - `evals/M3-protocol-2.json` replaces only ET-M3-1. It keeps protocol-1's every-frame area band as a presence band, and adds a size band in size-checkable frames. Those frames are chosen by a sightline rule computed from the commanded joints only.
  - The rule's 0.035 m clearance comes from the ledgered diagnostic `20261107T112025Z_3f2d4bd9`, run on spent seeds 10900 to 10919.
  - The independent review found a blocker: with the area band limited to size-checkable frames, a removed cube went undetected after them. The presence band fixes it. The review also found that failing candidates with no size-checkable frame would sink the test on a technicality; such candidates now get no size-band check instead.
- **2026-11-07, `m3-protocol-2` frozen (PR #35) and its tolerance pilot run once.** Run `20261107T113546Z_783f6d54` at clean `ff9ff8e`, seeds 10300 to 10319, no stop condition held (**measured**, simulation).
  - Size-checkable frames: 19.1% of all frames, median 32.5 per candidate, at least 16; none without a checkable frame after frame 0.
  - In them: area ratio 1.000 throughout, cube displacement at most 1.5e-6 m, actual-joint clearance at least 0.0351 m.
  - Over every frame the area ratio ran from 0.129 to 1.190.
  - Tolerances: size band [0.9, 1.1], presence band [0.116, 1.309], merge radius 27.4 px, first-frame tolerance 0.0, goal-centroid distance 13.6 px, minimum green count 0. Their sha256 is in the status ledger before any control or injection.
- **2026-11-07, ET-M3-1 under `m3-protocol-2` scored once and failed.** Run `20261107T113835Z_1d794f74` at clean `4efb133` (**measured**, simulation); report `reports/WO-021-et-m3-1-protocol-2.md`.
  - Controls: 9 of 60 falsely rejected (limit 3). Injections: 54 of 60 credited. All 60 injected candidates failed a check; 6 were not credited because their sources failed.
  - Every failure is on the every-frame presence band, whose 20-seed tails (0.129 to 1.190, widened to [0.116, 1.309]) fresh seeds exceeded (0.069 to 1.491).
  - The new size band falsely rejected nothing.
  - A revision needs `m3-protocol-3` and the owner's decision.
- **2026-11-07, the owner approved `m3-protocol-3`; frozen before its pilot.**
  - The approval is `approvals-20261108T033530354852Z-2a9dc4d3`. `evals/M3-protocol-3.json` (sha256 `1671e059…556c`) is the reviewed draft's rule text, unchanged. Only `status`, `frozen_before` and `decided_by` differ. Its sha256 was in the status ledger before any protocol-3 seed was simulated.
  - The acceptance thresholds are unchanged. The protocol-1 and protocol-2 failures stay on record.
  - If a frozen stop condition holds, the pilot is reported to the owner and everything pauses. Nothing is generated until the owner answers.
  - **The claim stays limited to what the checker tests.** A pass shows that the checker catches:
    - a removal that persists to the final frame;
    - a duplicate;
    - a resize that starts before the arm approaches;
    - the manifest, asset and first-frame mismatches.

    It does not show presence or size judged in the frames between.
  - **For ET-M3-2 (owner's instruction, not yet acted on):** ET-M3-2's work order must explicitly audit temporary disappearances and late resizes in generated trajectories. A temporary disappearance is a cube that vanishes after the size-checkable frames and reappears before the end. A late resize starts after those frames. ET-M3-1's checker does not catch either. The frozen ET-M3-2 text in `evals/M3-exit-tests.json` is not edited. The audit is added by an amendment frozen before any ET-M3-2 data.
