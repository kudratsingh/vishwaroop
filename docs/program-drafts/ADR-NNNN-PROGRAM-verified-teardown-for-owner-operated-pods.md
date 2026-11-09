# ADR-NNNN — PROGRAM: verified teardown for owner-operated GPU pods

**Date:** 2026-11-09 · **Status:** proposed, for `ironclad` (draft only; this repository cannot edit `ironclad`, `AGENTS.md §1.1`). `ironclad` assigns the number. · **Work order:** WO-025 (held) · **Program link:** `AGENTS.md §2.3, §2.4, §9.2, §9.3`; `docs/BUDGET_AND_LAUNCHER.md` acceptance items 5 to 7

**Authority.** Owner, 2026-11-09 (`approvals-20261109T022626042919Z-ee024835`): "Hold the rental. Bring the teardown question to ironclad and propose a verified shutdown mechanism compatible with me operating the pod." Drafting only. Adoption goes through an `ironclad` release (ADR-0004 decision 3).

**Labels** (`AGENTS.md §7.2`):
- **Runpod facts** are quoted from Runpod's documentation through its MCP server's `lookup-concept` and `search-docs`, read 2026-11-09, with the source named.
- **Nothing here was run.**
- Every number is a *proposed default*.

## Context
- **The rule.** `AGENTS.md §9.2` keeps paid execution blocked until the enforcing launcher's provider-teardown tests pass.
- **Where ironclad 1.2.0 stands:**
  - `ironclad.launcher.provider.REAL_PROVIDER_LIFECYCLE_VERIFIED = False`.
  - `ironclad-launch` refuses any provider other than the fake one.
  - `ironclad-budget-preflight` refuses every paid plan.
- **Why the existing design doesn't fit.** The launcher's `Provider` protocol (`create`, `instance_for`, `state`, `terminate`, `billed_usd`) assumes the launcher creates and terminates the machine. The owner's standing rule is the opposite: "I run the machine; you never start or stop it."
- **The question:** how can teardown be verified, and a paid run bounded, while the owner remains the only party who creates, stops and terminates the pod?

Runpod facts this design rests on (all from https://docs.runpod.io/pods/manage-pods and https://docs.runpod.io/get-started/api-keys, via the Runpod MCP concept store, read 2026-11-09):

| # | Fact |
|---|---|
| F1 | REST v2 has no field that stops a pod after a set time. |
| F2 | runpodctl's `--stop-after` and `--terminate-after` "never worked": the backend never enforced them, and runpodctl v2.12.0 removed them. |
| F3 | A pod ships `runpodctl` and a pod-scoped API key, and can stop itself: `runpodctl pod stop $RUNPOD_POD_ID`, scheduled with `sleep 2h; runpodctl pod stop $RUNPOD_POD_ID &`. |
| F4 | Pod states are `PROVISIONING`, `STARTING`, `RUNNING`, `EXITED` (stopped; compute released, volume disk kept), `ERROR` and `TERMINATED` (permanently deleted). |
| F5 | `cost` reads 0.0 when a pod is `EXITED`, but a stopped pod is still billed for its volume disk. The container disk is cleared on stop. |
| F6 | API keys are created with All, Restricted or Read Only access. A Restricted key sets access per API: None, Read Only or Read/Write. |
| F7 | Environment variables set at creation reach the container's main process (PID 1), not SSH login shells. |

## Decision (proposed)
Add an **owner-operated** provider mode to the launcher. In this mode:
- the launcher never creates, stops or terminates anything;
- it **attaches** to a pod the owner created, **bounds** it with a stop timer the owner set at creation, and **verifies** the shutdown and the bill with a read-only key.

1. **Attach, never create.** A new `OwnerOperatedRunpodProvider`:
   - `create` and `terminate` raise `ProviderRejectedError` ("the owner operates this machine").
   - `instance_for` returns the pod id from the owner's paid-run approval line.
   - `state` and `billed_usd` read the pod and its billing with a **Read Only** Runpod key (F6), never one that can mutate.
   - The approval line gains `provider: "runpod-owner-operated"`, `instance_id`, `stop_deadline_utc` and `disk_policy` (item 4).
2. **The hard bound is the owner's own timer, set at creation (F1 to F3).**
   - The owner creates the pod with a start command (or template) that runs, as PID 1's background child (F7):
     `sleep $STOP_AFTER_S && runpodctl pod stop $RUNPOD_POD_ID`.
     `STOP_AFTER_S` is set from the approved wall-clock limit (WO-025: 4 hours).
   - It is the owner's timer on the owner's pod. The agent never issues a stop.
   - If F3's pod-scoped key may also terminate (`runpodctl pod remove $RUNPOD_POD_ID`), the owner may choose terminate instead. Whether it may is **unverified** and is one of the pilot's checks (item 6).
3. **Watched from outside, read-only.** The launcher's guardian polls `state` and `billed_usd` every `poll_seconds`, from the machine that runs the launcher, not from the pod:
   - **`RUNNING` past `stop_deadline_utc` plus a grace period** (proposed 10 minutes): an `alarm` line in `ledgers/costs.jsonl`, and a notification to the owner. The money stays held against the caps. This catches a timer that died with its container (a restart, a killed PID 1).
   - **Billing:** a spend above the reservation raises the same `alarm`. On this route the launcher cannot stop the pod itself, so the owner must act.
4. **Teardown counts as verified only when:**
   - (a) the pod reads `TERMINATED`, or is absent from the pod list, on two reads at least `poll_seconds` apart; **or** `EXITED` with `disk_policy: "container-only"`, meaning it was created with no volume disk and no network volume (F5: the container disk is cleared on stop, so no data is kept; the standing charge after stop is checked in the pilot, not assumed);
   - (b) `billed_usd` stops increasing across two billing reads at least one billing interval apart;
   - (c) a `reconciled` line records the billed amount against the reservation.

   Process exit is not pod shutdown (`AGENTS.md §9.3`). Until (a) to (c) hold, the run stays open and its money stays held.
5. **Reservation.** The conditional reservation is the quoted rate × (`STOP_AFTER_S` + grace) + fixed costs + margin, checked against the run cap and the project cap before the agent runs anything. The quote must be under an hour old (`quote_max_age_seconds`), as today.
6. **Tests before paid use.**
   - **Fake-provider tests:** attach mode refuses `create` and `terminate`; a pod running past its deadline raises `alarm`; an `EXITED` pod with a volume disk is not verified; billing that keeps growing is not verified; the reconciliation arithmetic.
   - **Then one real $1-class pilot, owner-operated:**
     - the owner creates the cheapest graphics-class pod with a 10-minute timer (2);
     - the launcher observes the self-stop and verifies (a) to (c) on a container-only pod;
     - the owner checks whether the pod-scoped key can also terminate;
     - the owner terminates the pod, and the launcher verifies `TERMINATED`.
   - **On a pass**, `ironclad` sets a verified flag **for this provider mode only** (`OWNER_OPERATED_RUNPOD_LIFECYCLE_VERIFIED`), in a release. `REAL_PROVIDER_LIFECYCLE_VERIFIED` for launcher-created pods stays false.
7. **What the agent may do on this route:** run commands over SSH inside the approved run, and read the pod's state and billing with the Read Only key. It never holds a key that can start, stop or terminate.

## Alternatives considered
| Option | Why not |
|---|---|
| Launcher creates and terminates the pod (the existing protocol) | Conflicts with the owner's rule that only the owner starts and stops machines |
| A server-side stop timer on the pod | Runpod has none in REST v2 (F1), and the runpodctl flags were never enforced (F2) |
| Rely on the owner to stop the pod by hand, with no verification | Leaves `§9.3`'s "verify provider resource state after teardown" to memory; no alarm if the owner is away |
| An external watchdog that stops the pod with a write key | The agent's tooling would then stop machines, the same conflict as the first row |
| The in-pod timer alone, without outside watching | A container restart or a killed PID 1 silently removes the bound; item 3's outside watch catches that |

## Consequences
- **What becomes possible:** paid runs become possible without the launcher ever controlling the machine. The bound is the owner's timer plus the owner's own action on an alarm, and the evidence is the read-only verification.
- **The remaining trust gap:** a timer inside the container can be killed by anything running as root in it, the agent included. The launcher stays "a control against mistakes and runaway runs, not against a hostile command" (`docs/BUDGET_AND_LAUNCHER.md`). The outside watch makes such a failure visible; it cannot undo it.
- **A new secret:** a Read Only Runpod key the owner creates, kept outside every repository (`AGENTS.md §10.1`).
- **WO-025 waits for:** this ADR's release and the $1-class pilot, or the owner's explicit decision otherwise.

## Reversibility
- The new provider mode and flag can be removed in a later release. Nothing in a project depends on them until a project pins that release.
- A pod already running under this mode is still the owner's to stop.

## Open questions for the owner and `ironclad`
1. **Stop or terminate:** may the owner's timer terminate rather than stop, if the pilot shows the pod-scoped key can?
2. **Who runs the outside watch?** Proposed: the Mac that runs the agent session.
   - The watch should keep going if the agent's session ends. That needs a small long-lived process that the owner starts, or a scheduled check.
3. **Grace period and poll interval:** 10 minutes and 60 seconds are proposed.
