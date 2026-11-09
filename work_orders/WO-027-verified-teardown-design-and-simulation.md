# WO-027 | Verified teardown for owner-operated pods: design and simulation, before any paid test
**Phase:** M2a (tooling; no exit test). It blocks WO-025's rental.
**Exit tests advanced:** none
**Size:** M
**Prerequisites:** WO-025 (held). The owner's review of the first teardown draft.
**Authorization:**
- **Owner, 2026-11-09** (`approvals-20261109T031542703689Z-c8b6c471`): "Review the WO-025 teardown draft. I'll still create the pod, and the coding agent and launcher stay read-only. Require either a verified provider deadline or a watchdog I operate outside the pod that can terminate only the approved pod. Keep the timer inside the pod as a backup. Test what happens if the timer dies, the pod restarts, or the SSH session drops. Verify that compute and any attached storage stop billing, then reconcile the actual charge. Bring me the design and simulated test results before requesting approval for a small paid teardown test. Keep WO-025 on hold until teardown is validated and released."
- **Cost:** $0. Nothing paid.

**Files:**
- `src/vishwaroop/teardown/`, `tests/test_teardown.py`
- `docs/program-drafts/ADR-NNNN-PROGRAM-verified-teardown-for-owner-operated-pods.md`
- `work_orders/`, `reports/WO-027-teardown-design-and-simulation.md`
- the ignored `runs/`

## Objective
Design teardown so that:
- the owner creates the pod;
- the agent and the launcher are read-only;
- the hard bound is a verified provider deadline or an owner-operated watchdog outside the pod that can terminate only the approved pod;
- the in-pod timer is a backup.

Then show, against a fabricated provider, what happens under the faults the owner named and the others the design depends on. The code here is a prototype for adoption through `ironclad`. It is not the launcher.

## Scope
1. **Revise the program draft to these requirements.**
2. **A fabricated provider** with per-second billing, hour billing buckets (lagged, or posted hourly), key scopes, timeouts, restarts, timer death, and network volumes.
3. **The owner watchdog's logic:**
   - one approved pod id, fixed when it is built; no method takes another id;
   - an absolute deadline;
   - terminate only, never stop;
   - retries;
   - a per-poll status log.
4. **The read-only verifier:**
   - preflight refusals;
   - alarms;
   - teardown verification: the pod is gone, billing is settled, no network volume bills, and the charge reconciles against evidence from both its own reads and the watchdog's log;
   - state that survives a lost session.
5. **Sixteen scenarios**, including timer death, restart (relative and absolute timers), SSH session loss, both bounds gone, terminate timeouts, billing lag and hourly posting, attached storage, and over-billing. Tests pin each property.
6. **A report** with the design, the simulated results, their limits, and the proposed paid test, which is not requested yet.

## Out of scope
- Any request to Runpod's API, including reads.
- Any paid test, rental or key creation.
- Editing `ironclad`.
- Releasing WO-025's hold.

## Verification
- `make check`.
- `python -m vishwaroop.teardown.simulate` in a ledgered run; its JSON is the evidence.

## Exit criteria
Done when the owner has the revised design and the simulated results. The paid teardown test is a separate request.

## Stop conditions
- Any step that needs a real provider call or a key.
- A scenario showing that the design cannot bound the run without the agent holding a write key.

## Report
`reports/WO-027-teardown-design-and-simulation.md`

## Progress (append-only)
