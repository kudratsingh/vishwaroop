# WO-022 | M3: ET-M3-6's physics side on the Mac — reproducibility gate, evaluation family, arms F0, F_star, F1, F1s and F2
**Phase:** M3
**Exit tests advanced:** ET-M3-6
**Size:** M
**Prerequisites:** ET-M3-6 frozen (`evals/M3-exit-tests.json`; its `frozen` event in `work_orders/STATUS.jsonl`); WO-020 accepted (target family `m0-scripted-missed-grasp`); WO-021 hands this work to "the next work order" (its Scope and Out of scope). None of it depends on ET-M3-1, which is on hold (`approvals-20261108T074331649665Z-d15195a4`).
**Authorization:** AGENTS §2.1 only. The Mac at $0: physics on the CPU, training on MPS, as `docs/M3-design-draft.md` §5 lists and the owner accepted with D1 to D8 (`approvals-20261107T065704456185Z-01953940`). Owner, 2026-11-07: prioritize SO-101 work that can proceed independently of ET-M3-1. Not authorized: M3 GPU work, renting for M3.
**Files:** `src/vishwaroop/synth/`, `src/vishwaroop/models/` (read; new M3 entry points only), `tests/`, `work_orders/`, `reports/WO-022-m3-et-m3-6-physics-arms.md`, and the ignored `runs/` and `data/derived/`.

## Objective
Build and run everything in ET-M3-6 that comes from physics:
- the protocol §4 reproducibility gate;
- the evaluation family `m3-eval-missed-grasp`, on block 16;
- the base, F_star, F1, F2 and F1s training sets;
- the five arms trained on seeds 0, 1 and 2;
- the frozen scoring code.

F3 needs a generator (Pipeline A or B), a GPU and a filter whose step 4 is ET-M3-1's check. It is out of scope, so this work order advances ET-M3-6 but cannot close it.

## Scope
1. **M3 recorder.**
   - A write-once snapshot (`evals/M3-protocol.md` §3), then a recorded episode through `sim/export.record_episode`.
   - Every seed is checked by `synth.protocol.partition_for_seed`, `check_family_seed` and `check_not_held` before anything is simulated.
   - Block 10 is not used.
2. **Reproducibility gate** (protocol §4): 3 replays from the saved initial state, the frozen 0.001 tolerance (`evals/M0-exit-tests.json`), and the same outcome label on every repeat. The gate checks the hashes of the frozen M3 files itself and does not rely on ET-M3-1's ledger state.
3. **Evaluation family.**
   - Block 16 seeds, ascending from 16000, with exactly `m0-scripted-missed-grasp`'s PlanSettings.
   - Recording stops when 60 episodes pass the gate, using seeds 16000 to 16099 at most. Skipped seeds are listed.
   - It is recorded once, before any arm is trained. Nobody looks at its trajectories or metrics before scoring.
4. **F2 and F1s, on block 11.**
   - F2: operator episodes from 11000 upward by the frozen rule, until the windows reach W* = 4,161.
   - F1s: the nominal demos of F2's scenes, in F2's order, truncated to W*.
5. **Data assembly.**
   - The 207-episode base, which must give 31,031 windows. Any other count stops the run before training.
   - Normalization statistics from the base only.
   - Every arm's added windows come after the base windows.
   - F_star: 27 episodes giving 4,161 windows.
   - F1's fixed augmentation: `default_rng(1)`, in the frozen order.
   - The loader refuses imagined records and records carrying `generator_model_artifact`. This is groundwork for ET-M3-5 and claims nothing about it.
6. **Training.** F0, F_star, F1, F1s and F2, each on seeds 0, 1 and 2, with every hyperparameter as in `runs/20261102T041509Z_93dd348c`. Each arm is trained once per seed and resumes after an interruption (`AGENTS.md` §13.9).
7. **Scoring code.**
   - The helps rule, W with its 0.02 margin, the gap fraction and the report tables, exactly as frozen.
   - Tested on fixtures.
   - Applied to block 16 only when the owner says so (see Stop conditions).

## Agent details, sent to the owner before any block-11 or block-16 seed is simulated
The frozen text leaves these open. The owner may veto the agent-set ET-M3-6 details before any operator datum exists (`evals/M3-exit-tests.json`, `decided_by`).
1. **Undecided labels.** `sim/replay.py` refuses a recorded `insufficient_evidence` label, but protocol §4 excludes a scene only for tolerance or a label mismatch. Proposed: follow §4. An episode whose undecided label repeats identically on all 3 replays, within tolerance, passes the gate. Planning failures are kept, as the evaluation family's text says.
2. **Skipped F2 scenes.** Proposed: a skipped scene adds no episode. The lateral-miss/close-high alternation and the lateral-miss sign count advance over kept episodes only. Each episode's parameters still come from `random.Random(seed)` of its own seed.
3. **F1s when a nominal demo fails the gate.** Proposed: that scene is skipped for F1s and listed, and F1s continues with the next F2 scene. If F2's scenes run out before W*, F1s is reported as unmatched. F1s is reported only and is not in the threshold.

## Out of scope
- F3, any generator or IDM, any GPU or paid resource.
- ET-M3-1 and its held seeds.
- ET-M3-2, ET-M3-3, ET-M3-4 and ET-M3-5.

## Verification
- `make check` and `make synth-test`.
- Negative tests:
  - a held seed, a block-10 seed, a block-18 seed, and a dev seed in a training set are refused;
  - a base count other than 31,031 stops the run;
  - a second recording of the evaluation family is refused;
  - a second training of an arm on the same seed is refused;
  - an imagined record is refused by the loader;
  - the gate rejects a replay past the tolerance and a label that changes between repeats.
- Recordings and training run at clean commits through `ledgered_run`.

## Exit criteria
- Done when F0, F_star, F1, F1s and F2 are trained on all three seeds and their data and manifests are recorded. Scoring follows if the owner says so.
- This WO advances ET-M3-6 and does not close it.
- Before the first block-16 or block-11 recording, the code gets one independent review plus one recheck (`AGENTS.md` §13.8), because the evaluation family is one-shot.

## Stop conditions
- The base count differs from 207 episodes or 31,031 windows.
- Fewer than 60 of seeds 16000 to 16099 pass the gate.
- Block 11 runs out before F2 reaches W*.
- Any need for a held seed, for block 10, or for blocks 18 to 19.
- Any GPU or paid work.
- **Scoring on block 16 waits for the owner.** The rule allows physics arms to be scored before F3, since F3's protocol must state which arms' results were known when it was frozen. But once scored, those results are known to whoever designs F3.

## Report
`reports/WO-022-m3-et-m3-6-physics-arms.md`

## Progress (append-only)
