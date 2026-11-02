# WO-016 | Retest ET-M1-5 with a calibration split that includes perturbed chunks
**Phase:** M1
**Exit tests advanced:** ET-M1-5
**Size:** S
**Prerequisites:** WO-005 merged (PR #19); owner decision, 2026-11-02.
**Authorization:** AGENTS §2.1 only. The owner's Mac, $0.
**Files:** `evals/M1-et5-*.json`, `src/vishwaroop/sim/branches.py`, `src/vishwaroop/scoring/`, `tests/`, `artifacts/manifests/`, `work_orders/`, `docs/CONTEXT_AND_DECISIONS.md`, `docs/PHASES.md`, `START_HERE.md`, `reports/WO-016-m1-et5-retest.md`, `reports/WO-005-m1-planner-and-chunk-scorer.md` (errata only), ignored `runs/` and `data/derived/`.

## Objective
Owner, 2026-11-02, on WO-005:

> ET-M1-5: option (b). New short WO: calibration split including perturbed chunks, frozen before scoring, fresh states. The 20% abstention cap stays. If it fails, close M1 with the negative recorded (option a).

WO-005's scorer failed only on abstention (37.7% against the 20% cap): its scales came from scripted windows, which hold no perturbed chunk. This work order changes only that, and scores once on fresh states.

The same instruction asks for three records, which this work order also makes:
- **M1's primary result.** The learned model matched the nominal model on planning success and on constraint prediction. It goes in this report and in `docs/CONTEXT_AND_DECISIONS.md`.
- **A prerequisite before M4's shadow mode.** The planner takes about 100 ms against a 50 ms control period.
- **WO-005's acceptance** once this is done, whatever the result.

## Scope
Every rule is frozen in `evals/M1-et5-retest.json` before the data exists.
1. Collect 210 fresh dev-family episodes, `evals/M1-et5-eval-plan.json`, block 9 seeds 9300 to 9369.
2. Branch the calibration split and the fresh episodes: every episode with at least 25 steps, one state each, the same four chunks and protocol as WO-005.
3. Fit the scales and the abstention threshold on the calibration branches only, then score ET-M1-5 once on the fresh branches.

## Out of scope
Any change to the model, chunks, violation definition, threshold or cap; M2a; the real-time work.

## Verification
`make check`; then the collection and registry build as in WO-005, `python -m vishwaroop.sim.branches --set calibration`, `--set evaluation`, and `python -m vishwaroop.scoring.score_et5_retest`. Expected: a pass, a fail or "not decidable" under the frozen rule, scored once. Negative tests: a second scoring, a changed frozen file, and calibration taken from anything but the calibration branches.

## Exit criteria
Done when the report gives ET-M1-5 under the frozen rule, and M1's status follows: passed if ET-M1-5 passes, or closed with the negative recorded if it does not. It closes an exit test, so `AGENTS.md §13.8` asks for a full review. From M1 that is one review plus one recheck.

## Stop conditions
Paid compute; any change to a frozen rule after a result; scoring more than once.

## Report
`reports/WO-016-m1-et5-retest.md`
