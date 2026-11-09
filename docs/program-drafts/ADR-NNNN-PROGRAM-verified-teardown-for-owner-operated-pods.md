# ADR-NNNN — PROGRAM: verified teardown for owner-operated GPU pods

**Date:** 2026-11-09 · **Status:** proposed, revision 2 (after the owner's review), for `ironclad`. Draft only: this repository cannot edit `ironclad` (`AGENTS.md §1.1`), and `ironclad` assigns the number. · **Work orders:** WO-027 (design and simulation); WO-025 (held until this is validated and released) · **Program link:** `AGENTS.md §2.3, §2.4, §9.2, §9.3`; `docs/BUDGET_AND_LAUNCHER.md` acceptance items 5 to 7

**Authority:**
- **First instruction, 2026-11-09** (`approvals-20261109T022626042919Z-ee024835`): "Bring the teardown question to ironclad and propose a verified shutdown mechanism compatible with me operating the pod."
- **The owner's review, the same day** (`approvals-20261109T031542703689Z-c8b6c471`): "I'll still create the pod, and the coding agent and launcher stay read-only. Require either a verified provider deadline or a watchdog I operate outside the pod that can terminate only the approved pod. Keep the timer inside the pod as a backup. Test what happens if the timer dies, the pod restarts, or the SSH session drops. Verify that compute and any attached storage stop billing, then reconcile the actual charge."

**Labels** (`AGENTS.md §7.2`):
- **Runpod facts** are quoted from Runpod's documentation through its MCP concept store, read 2026-11-09, with the source named.
- **Simulated results** come from a fabricated provider (**mocked/fixture**). No Runpod call other than read-only catalog reads was made.

## Context
- **The rule.** `AGENTS.md §9.2` keeps paid execution blocked until the launcher's provider-teardown tests pass.
- **ironclad today.** `ironclad` 1.2.0 refuses every paid launch (`REAL_PROVIDER_LIFECYCLE_VERIFIED = False`). Its `Provider` protocol assumes the launcher creates and terminates the machine.
- **The owner's constraint is the opposite:**
  - the owner creates the pod;
  - the coding agent and the launcher are read-only;
  - the hard bound is either a verified provider deadline or a watchdog the owner operates outside the pod, restricted to the approved pod;
  - an in-pod timer is a backup only.

| # | Runpod fact | Source |
|---|---|---|
| F1 | REST v2 has no field that stops a pod after a set time. | docs.runpod.io/pods/manage-pods; REST v2 spec |
| F2 | runpodctl's `--stop-after` and `--terminate-after` "never worked": the backend never enforced them, and v2.12.0 removed them. | Runpod's official plugin, `pod-workflows.md` at commit 97221eb |
| F3 | A pod ships `runpodctl` and a pod-scoped API key, and can stop itself with `runpodctl pod stop $RUNPOD_POD_ID`. | docs.runpod.io/pods/manage-pods |
| F4 | Pod states: `RUNNING`, `EXITED` (stopped; compute released), `TERMINATED` (deleted; gone from the pod list). Terminate cannot be undone. | REST v2 spec |
| F5 | Pods are billed per second for compute, container disk and volume disk. A stopped pod pays nothing for container disk, but its volume disk is billed at a higher rate. Only termination ends every pod charge. | docs.runpod.io/pods/pricing, /pods/overview |
| F6 | A network volume is billed per GB from creation until deletion, attached or not. | docs.runpod.io (network volume billing) |
| F7 | Billing history is per pod per time bucket (hour at the finest), with GPU, CPU and disk amounts. | REST v2 `GET /v2/billing/pods` |
| F8 | API keys are All, Restricted (per API: None, Read Only or Read/Write; per Serverless endpoint) or Read Only. A key cannot be restricted to one pod. | docs.runpod.io/get-started/api-keys |
| F9 | Environment variables set at creation reach the container's main process (PID 1), not SSH login shells. | live probe in Runpod's plugin, 2026-09-28 |

## Decision (proposed)

### 1. Who holds what
| Party | Key | May |
|---|---|---|
| Owner | the console, and the watchdog's key | create, stop and terminate pods |
| Owner watchdog (outside the pod) | a **Restricted** key with Pods Read/Write, stored only where the watchdog runs | terminate **the approved pod**, and nothing else (item 3) |
| In-pod backup timer | the pod-scoped key Runpod puts in the pod (F3) | stop the pod it runs in; terminating is untested |
| Coding agent; launcher and verifier | a **Read Only** key (F8) | read pods, billing and network volumes; never mutate (a mutation returns 403) |

### 2. The hard bound: a provider deadline, or the owner's watchdog
- **A verified provider deadline would qualify** if it existed, after the same tests. On Runpod pods it does not (F1, F2), so the hard bound is the owner's watchdog.
- **Where the watchdog runs:** anywhere the owner operates that is outside the pod, stays awake through the run, and keeps its key out of the agent's reach.
  - **Proposed:** a scheduled Cloudflare Worker, with the key as a Worker secret. The owner already uses Cloudflare, and a Worker does not sleep with a laptop.
  - **Alternative:** a launchd job under a separate macOS user, whose keychain the agent's user cannot read.
  - **Not acceptable:** a process under the agent's own user on the Mac. The agent could read its key, and a sleeping laptop silences it. The simulated "watchdog asleep" case overran by 60 minutes.

### 3. "Can terminate only the approved pod"
F8 means no Runpod key can be limited to one pod. So the restriction lives in the watchdog's construction, and the residual risk is the key itself.
- **One pod, fixed at construction.** The approved pod id is read once from the owner's approval and checked against a pod-id pattern. No method takes a pod id: the poll is `tick(api)`, and a test pins that signature. Terminate is called only with the approved id.
- **Terminate only.** The watchdog never stops. A stop leaves volume disk billing (F5), and starting is not in its code.
- **Idempotent, and it retries.** Terminating a pod that is already gone is a no-op. A call that gets no answer is retried at the next poll.
- **Residual risk:** whoever controls the watchdog's host and key could act on other pods by changing its code. The agent has neither. The key is the owner's, as the console is.

### 4. The backup timer inside the pod
- **How it starts.** The owner's start command launches, as a child of PID 1 (F9):
  `sleep $(( VISHWAROOP_DEADLINE_UTC_EPOCH - $(date +%s) )) && runpodctl pod stop $RUNPOD_POD_ID`
- **Absolute, not relative.** It sleeps to an **absolute** deadline taken from the environment, so a container restart re-arms it to the same instant. In the simulation, a timer relative to container start, restarted at 3 hours with no watchdog, overran by 180 minutes.
- **Stop, not terminate.** The pod-scoped key may only be able to stop (F3; terminate is untested). With the required container-only disk, a stopped pod should bill nothing (F5). That is checked in the paid test, not assumed.

### 5. What the owner creates, checked before the agent runs anything
- **Disks:** container disk only, with no volume disk and no network volume (F5, F6). An account that already has network volumes is refused too, because they bill regardless (F6). The verifier's preflight refuses otherwise.
- **The deadline:** `VISHWAROOP_DEADLINE_UTC_EPOCH` in the pod's environment, no later than the approved deadline. The backup timer is in the start command.
- **The watchdog:** configured with the pod id and the same deadline, and already polling. Its first status line is visible to the verifier.

### 6. The read-only verifier (launcher side)
- **Preflight:** the refusals in item 5.
- **Alarms** to the owner, without acting:
  - the pod is still `RUNNING` or `EXITED` past the deadline plus grace (proposed 10 minutes);
  - the watchdog has been silent for more than 5 minutes;
  - billing is above the reservation.
- **Teardown counts as verified only when all of these hold:**
  - (a) the pod is gone on two reads at least one poll apart;
  - (b) the pod's billing is unchanged across a settle window at least as long as the provider's billing lag (proposed 2 hours until the paid test measures it);
  - (c) no network volume existed at preflight or exists now;
  - (d) the billed total lies within the expected range, and the end of compute is pinned to within three polls by an observation.
- **Where the evidence for (d) comes from.** The pod was seen `RUNNING`, then seen stopped or gone. Two sources count:
  - the verifier's own reads;
  - the watchdog's per-poll status log, which the verifier can read but not write.

  With the second source, a lost SSH session or launcher does not loosen the reconciliation.
- **Persistence.** The verifier's state is plain JSON in its ledger. A new process resumes it after a dropped session.
- **Alarm delivery.** Verifier alarms reach the owner only while a verifier runs. So the watchdog also alarms the owner on its own repeated terminate failures, through the owner's channel.

### 7. Reconciliation
- **Expected charge:** the GPU rate plus the container-disk rate, over the observed running window. It is bounded:
  - below, by the last sighting of the pod running;
  - above, by the first sighting of it stopped or gone, plus one poll.
- **The record.** The billed total, read per pod per hour bucket, is recorded as `reconciled` in `ledgers/costs.jsonl` with the expected range.
- **Two failure cases:**
  - a charge outside the range is not verified, and is reported;
  - a total that is stable but unreconciled means billing has not posted yet. It keeps the run open.

### 8. Tests before any paid use
- **Simulated: done in WO-027** (`reports/WO-027-teardown-design-and-simulation.md`). Sixteen scenarios, all as designed, including:
  - timer death, restart, SSH loss and combinations of them;
  - both bounds gone;
  - terminate timeouts;
  - billing lag and hourly posting;
  - attached storage;
  - over-billing.
- **Real: a small paid teardown test** (proposed in the report, not yet requested). It measures what the simulation assumes:
  - the stopped pod's charge;
  - whether the pod-scoped key can terminate;
  - billing lag and posting;
  - the end-to-end reconciliation.
- **On a pass:** `ironclad` adds an owner-operated mode with its own verified flag, in a release. `REAL_PROVIDER_LIFECYCLE_VERIFIED` for launcher-created pods stays false.

## Alternatives considered
| Option | Why not |
|---|---|
| The launcher creates and terminates pods | The owner creates the pod; the agent and launcher stay read-only |
| A provider deadline | Runpod has none for pods (F1); the runpodctl flags were never enforced (F2) |
| The in-pod timer as the hard bound | Anything as root in the container can kill it; a relative timer moves on restart (simulated overrun: 180 min) |
| A watchdog on the agent's own user account | The agent could read its key; a sleeping laptop silences it (simulated overrun: 60 min) |
| A stop instead of a terminate | A volume disk keeps billing (F5); verification needs the pod gone |

## Consequences
- **Paid runs** can proceed with the owner operating every machine. Bounding is the owner's watchdog, backed by the in-pod timer. The evidence is read-only.
- **What the owner sets up and keeps:**
  - a Worker (or a separate user account);
  - a Restricted key for it;
  - a Read Only key for the verifier.

  Both keys stay out of every repository (`AGENTS.md §10.1`).
- **If the watchdog and the backup timer both fail,** nothing stops the pod. The verifier alarms within the grace period plus one poll, but only the owner can stop it (simulated: alarm at 11 minutes past the deadline).

## Reversibility
- The owner-operated mode is additive and can be removed in a later release.
- A pod running under it is always the owner's to stop.

## Open questions for the owner
1. **Watchdog host:** Cloudflare Worker (proposed) or a separate macOS user?
2. **Alarm channel** for the watchdog's own failures: email, push, or both?
3. **The paid teardown test** in the WO-027 report: approve it, change it, or decline.
