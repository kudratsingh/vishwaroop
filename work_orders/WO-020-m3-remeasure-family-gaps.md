# WO-020 | M3: re-measure the family-holdout gaps under plain A, and pick M3's target family
**Phase:** M3
**Exit tests advanced:** none (it feeds the proposed held-out-family test, not yet an exit test)
**Size:** XS
**Prerequisites:** M1 passed; the owner's acceptance of M3's defaults D1 to D8 (2026-11-06, `ledgers/approvals.jsonl`).
**Authorization:** AGENTS §2.1 only. The Mac, $0. CI only (`AGENTS.md §13.8`): it closes no exit test.
**Files:** `evals/M3-remeasure.json`, `src/vishwaroop/models/m3_remeasure.py`, `tests/`, `work_orders/`, `docs/M3-design-draft.md`, `reports/WO-020-m3-remeasure-family-gaps.md`, ignored `runs/`.

## Objective
The owner, 2026-11-06: "Start with the Mac work orders, beginning with re-measuring the −237% missed-grasp gap under the current model." And: "Freeze the M3 remeasurement protocol before its first run."

## Scope
Apply plain A at inference to WO-004's seven family-holdout ensembles, under `evals/M3-remeasure.json`, frozen before the first run. Check every reduction against WO-005 stage 0's numbers, apply the frozen target rule, and report where the target family's remaining error sits.

**Already seen, and stated in the freeze.** WO-005's stage 0 had measured this. Under plain A, `missed-grasp`'s cube is −0.5% (from −237.1%), its joints stay at −62.9%, and the rule's outcome is known. This run makes the target choice auditable. It is not blind.

## Out of scope
Operators, generators, retraining, any GPU work (D4).

## Verification
`make check`; `python -m vishwaroop.models.m3_remeasure`, at a clean commit. Expected: the reproduction check passes on all 420 values, and the target is chosen by the rule.

## Exit criteria
Done when the report gives the target family, its deciding value and where the remaining error sits.

## Stop conditions
The reproduction check fails; any need for dev or GPU data.

## Report
`reports/WO-020-m3-remeasure-family-gaps.md`
