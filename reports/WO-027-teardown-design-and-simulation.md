# WO-027 — Verified teardown for owner-operated pods: design and simulated results

**Status:** design revised; simulation passed as designed (**mocked/fixture**); real provider **not run** · **Date:** 2026-11-09 · **Author:** claude-code-vishwaroop · **Work order:** WO-027 · **Phase:** M2a (tooling; blocks WO-025's rental) · **Protocol version:** none
**Program link:** `AGENTS.md §9.2, §9.3` → the owner-operated teardown proposal for `ironclad`

> Words with fixed meanings in this report: **measured**, **estimated**, **mocked/fixture**, **not run**. Every dollar figure in §4 is from a fabricated provider with assumed rates; it is not a quote or a charge.

## 1. Claim and scope
- **What was shown.** Against a fabricated provider that models Runpod's documented billing and pod behaviour, the revised design kept the pod bounded and verified teardown in every scenario where at least one bound was alive. It refused or failed verification where it should, and raised the owner alarm where both bounds were gone.
- **What it does not show:**
  - that Runpod behaves as modelled: stopped-pod billing, pod-scoped terminate, billing lag and posting;
  - that the owner's watchdog host stays up.

  The paid test in §10 measures the first. The second is an operating choice.

## 2. Frozen method
No exit test. The scenarios and the pass properties were written before the results were read, and the tests (`tests/test_teardown.py`) pin them. Owner's words: `approvals-20261109T031542703689Z-c8b6c471` (quoted in the work order).

## 3. Reproduction
- `python -m vishwaroop.teardown.simulate`: ledgered run `runs/20261109T032235Z_0abd0b0c` (`teardown_simulation.json`), code commit `65bdc61`, clean.
- `make check`: 18 teardown tests.

The setup:
- **Provider:** `src/vishwaroop/teardown/provider.py` (per-second accrual, 10 s steps).
- **Watchdog:** `watchdog.py`, polling every 60 s.
- **Verifier:** `verify.py`, polling every 60 s.
- **Timeline:** the deadline is 4 h after creation, the run ends at deadline + 6 h, the grace period is 10 min, and the settle window is 2 h unless stated.
- **Rates assumed:** $1.19/h GPU, and $0.10 per GB-month for container disk.
- **The pod:** 100 GB container disk.

## 4. Results (all **mocked/fixture**)
| Scenario | Pod at end | Compute ended vs deadline (min) | Standing $/h after | Billed $ | Expected $ range | Teardown verified (min after deadline) | First overrun alarm (min) | Notes |
|---|---|---|---|---|---|---|---|---|
| baseline | terminated | 0 | 0 | 4.81 | 4.79–4.83 | yes, 120 | — | — |
| owner ends early (2 h) | terminated | −120 | 0 | 2.41 | 2.39–2.43 | yes, 0 (2 h after the owner's terminate) | — | — |
| **in-pod timer dies** at 10 min | terminated | 0 | 0 | 4.81 | 4.81–4.85 | yes, 120 | — | watchdog bound holds |
| **pod restarts** at 3 h | terminated | 0 | 0 | 4.81 | 4.79–4.83 | yes, 120 | — | — |
| restart, **relative** timer, no watchdog | stopped | **+180** | 0 | 8.43 | 8.41–8.45 | no | 11 | relative timer re-armed on restart |
| restart, **absolute** timer, no watchdog | stopped | 0 | 0 | 4.81 | 4.79–4.83 | no (stopped, not terminated) | 11 | bounded; owner must terminate |
| **SSH session lost** 1 h to 6 h | terminated | 0 | 0 | 4.81 | 4.79–4.83 | yes, 240 | — | verifier resumed from saved state; watchdog log pinned the end |
| SSH lost + timer dies + restart | terminated | 0 | 0 | 4.81 | 4.79–4.83 | yes, 240 | — | — |
| watchdog down **and** timer dead | **running** | — | 1.20 | 12.02 | — | no | 11 | alarms: watchdog silent, past deadline, above reservation |
| watchdog asleep 3 h to 5 h, timer dead | terminated | **+60** | 0 | 6.02 | 6.02–6.06 | yes, 180 | 11 | verified, but the deadline was missed |
| first 5 terminate calls time out | terminated | +0.7 | 0 | 4.83 | 4.81–4.85 | yes, 121 | — | retries |
| billing lags 90 min | terminated | 0 | 0 | 4.81 | 4.79–4.83 | yes, 210 | — | waits for the lag plus the settle window |
| hourly posting, 30 min settle window | terminated | 0 | 0 | 4.81 | 4.79–4.83 | yes, 90 | — | a stable but unreconciled total was seen and **not** accepted |
| network volume attached | terminated | 0 | 0.0048 | 4.81 | 4.79–4.83 | no | — | preflight refused; volume still bills |
| volume disk 20 GB, stop only | stopped | 0 | 0.0055 | 4.86 | 4.79–4.83 | no | 11 | preflight refused; stopped disk bills |
| provider over-bills 15 min | terminated | 0 | 0 | 5.11 | 4.79–4.83 | no | — | reconciliation failed |

In every scenario:
- the read-only key's terminate was refused (403);
- the owner's other pod was never touched.

## 5. What the results mean for the design
1. **Answers to the owner's three faults:**
   - **Timer death:** harmless while the watchdog is up.
   - **A restart:** harmless with the watchdog. Without it, harmless only with an absolute timer. That is why the backup timer must read an absolute deadline.
   - **A lost SSH session:** costs nothing. The watchdog keeps bounding, and the verifier resumes. Its reconciliation stays tight only because it also reads the watchdog's per-poll status log. Without that log, the simulated window was $1.18 to $7.24, which proves little.
2. **Watchdog placement matters.** A watchdog that sleeps (a laptop) missed the deadline by its sleep time. The design asks for a host that stays up and keeps its key from the agent.
3. **Only termination ends every charge.** A stopped pod with a volume disk, or any network volume, keeps billing. Preflight refuses both, and verification requires the pod gone.
4. **Billing must settle and reconcile.** With hourly posting, a short settle window saw a stable total that was not the final charge. Reconciliation caught it. So a settle window alone is not enough, and the paid test must measure the real lag.
5. **The residual case: both bounds gone.** The verifier alarms 11 minutes after the deadline, but cannot act. Only the owner can. The watchdog therefore also needs its own alarm channel for its own failures.

## 6. Cost and latency
$0. The simulation runs in about 1 second of CPU.

## 7. Sealed access
None.

## 8. Acceptance gate by gate
| WO-027 exit criterion | State |
|---|---|
| Design revised to the owner's requirements | met (`docs/program-drafts/ADR-NNNN-PROGRAM-verified-teardown-for-owner-operated-pods.md`, revision 2) |
| Timer death, restart and SSH loss simulated | met (**mocked/fixture**, §4) |
| Compute and attached storage shown to stop billing; charge reconciled | met in simulation; **not run** on Runpod |
| Results to the owner before any paid-test request | this report |

## 9. Limits
- **The fabricated provider models documented behaviour, not measured behaviour.** These are assumed, not known:
  - a stopped container-only pod bills $0;
  - the pod-scoped key cannot terminate;
  - billing lags or posts hourly.
- **The disk rate** ($0.10 per GB-month) is a simulation parameter.
- **Not modelled:**
  - host failure, during which Runpod says storage is not billed;
  - spot interruption;
  - a provider API outage longer than the run;
  - a hostile process killing the watchdog's host.
- **Real-provider code.** The watchdog and verifier are prototypes with a fake API. The real Runpod client calls (`GET /v2/pods/{id}`, `DELETE /v2/pods/{id}`, `GET /v2/billing/pods`) are not written, and are the next step if the paid test is approved.

## 10. Proposed paid teardown test (**not requested yet**; for the owner's decision)
- **Card:** the cheapest secure on-demand card in stock: RTX 2000 Ada at $0.24/h, or RTX A4000 at $0.25/h. Both were LOW stock in EUR-IS-1 at Runpod's `get-gpu-type` read on 2026-11-09, about 03:25 UTC.
- **Disks:** container-only, 20 GB; no volume disk and no network volume.
- **Who does what:** the owner creates both pods and runs the watchdog. The agent holds a Read Only key only.

| Pod | Sequence | Measures |
|---|---|---|
| A | deadline 20 min. Agent kills the in-pod timer at 5 min (a process in the container, not a stop). Owner restarts the pod at 8 min. Agent drops its SSH session at 10 min. Watchdog terminates at 20 min. | timer death, restart and SSH loss on real hardware; watchdog terminate; verifier resume; billing lag and posting; reconciliation |
| B | deadline 10 min, no watchdog for this pod. The absolute in-pod timer stops it. The agent then reads its billing for 30 min. Owner tests the pod-scoped key's terminate from inside the pod before the stop, then terminates B. | whether a stopped container-only pod bills $0; whether the pod-scoped key can terminate |

- **Cost (estimated):**
  - compute: about 25 min (A) and 15 min (B) at $0.25/h, about $0.17;
  - billing reads afterwards cost nothing.
- **Proposed ceiling:** $1. Stop if the projection passes it.
- **What the owner sets up first:**
  - the watchdog, on the host the owner chooses, with a Restricted key;
  - a Read Only key for the agent, kept outside the repository.
- **The code needed first ($0):** the real Runpod client for the watchdog and the verifier, tested against recorded responses.

## 11. Retro note
Reconciliation that rests only on the verifier's own observations fails whenever the verifier is absent. Put the evidence where the bound is: the watchdog's status log.
