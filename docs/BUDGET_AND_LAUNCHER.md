<!-- ironclad-policy v1.1.0 -->
# BUDGET_AND_LAUNCHER.md — spend control

**Approved spend for this repository today: $0** (`config/budget.json`). Planning ranges in `PROGRAM.md §9` and in the owner's purchase plan are not approvals or quotes. An agent cannot approve its own spending by editing a file or passing a flag (`AGENTS.md §2.3, §9`).

## What exists now
`ironclad-budget-preflight` is a runnable **cost estimator and refusal check**. It never launches anything, never reserves funds, never stops a rental. Its tests (in the shared suite `ironclad.testing.suites.test_tools`) prove the arithmetic and the refusals, nothing more.

`ironclad-launch` and `ironclad.launcher` are the enforcing launcher (below). **Paid launches stay refused**: the lifecycle has passed only against a fabricated provider.

## Estimating a run (from a measured pilot)
Inputs: GPU count, quoted hourly rate with its timestamp, planned steps, **measured** seconds per step from a short pilot, setup/evaluation/transfer/shutdown time, storage/egress/taxes, and an explicit uncertainty margin.

- Expected runtime = steps × measured seconds/step + overhead. Bound it with a separate hard wall timeout.
- Reserve the **conditional** bound (rate × hard wall + fixed costs, with margin) against both the run cap and the remaining project cap before starting.
- GPU price × steps alone is dimensionally wrong. Unknown rate, timing, overhead, or shutdown behaviour fails closed.
- Stopping the trainer does not stop the rental. The bound is conditional on verified provider teardown.

## The enforcing launcher
`ironclad-launch --run-id ID --plan P --progress F --stale-seconds S -- CMD ARG...` supervises one `local_unmetered` run: no shell, wall timeout, progress watchdog, and ledger lines in `ledgers/costs.jsonl`. The trainer appends JSON lines with an integer `step` to the progress file. Exit status: 0 completed, 1 interrupted, 2 refused, 3 alarm. An `alarm` line means a person must look: a resource possibly still billing keeps its money held against the caps.

A run stops as soon as its billing reaches its own reservation, so runs in parallel cannot together pass the project cap by more than a billing poll.

**A paid approval is one line in `ledgers/approvals.jsonl`,** written from the owner's own words, binding all of:
```json
{"gate": "paid-run", "run_id": "...", "command_sha256": "...", "config_sha256": "...", "plan_sha256": "...", "ceiling_usd": 1.0, "resource_count": 1, "expires_at": "2026-11-01T00:00:00Z", "quote": "the owner's words"}
```
The run's latest approval is the one that counts, so the owner can narrow one by adding another. A paid plan also needs `quote_ts`, the time of its rate quote; an old quote fails closed (`quote_max_age_seconds` in the budget file, default 3600).

Acceptance, and where it stands:
1. An owner approval binds run id, command/config hashes, exact cost ceiling, resource count, and expiry (`ledgers/approvals.jsonl`). **Done.**
2. Project-wide lock; atomic reservation in `ledgers/costs.jsonl`; concurrent reservations never exceed the cap; the cap cannot be raised from the CLI. **Done.**
3. Runs without shell interpolation; supervisor wall timeout; trainer-side `max_steps` plus a progress watchdog that detects ignored step limits; the parent terminates children it started. **Done.** Passing `max_steps` to the trainer is the caller's job.
4. Ledger events: planned, reserved, running, cancelled, interrupted, completed, reconciled, plus `alarm`. Failed runs stay. **Done.**
5. Provider teardown by instance TTL or an independent watchdog; process kill is **not** pod shutdown; provider state is verified after teardown and actual billing is reconciled. **Done against the fabricated provider.**
6. Failure injection tests: trainer crash, stale progress, SIGTERM, parent loss, API timeout, retry idempotency, duplicate launch, concurrency, stale quote, overspend, resource left billable after child exit. **Done against the fabricated provider.**
7. Until cloud-lifecycle tests pass against a fake provider and then a real one with a $1-class pilot approved by the owner, paid launches stay prohibited regardless of local timeout tests. **Fake provider done; real provider not run. Paid launches are refused** by a constant in the released package, which no configuration file can change.

**What the launcher cannot do, by design or for now.**
- A trainer runs as the same user in the same directory. It can edit ledgers, approvals and the budget, and kill the guardian. The launcher is a control against mistakes and runaway runs, not against a hostile command.
- A trainer can escape with `setsid` and a double fork. Progress is self-reported, so only the wall timeout and the provider's TTL are hard bounds. Trainer stdout has no size cap.
- `local_unmetered` is the plan's declaration: the launcher cannot tell whether a local command itself spends money. The command hash covers the argument vector, not script contents or the environment, and nothing ties the bound config file to the command line.
- The ledger and the lock belong to one checkout: two clones hold two sets of reservations, and deleting a ledger resets its totals.
- A TTL and idempotency are promises the provider must keep; WO-009 tests them for real. Billing read right after teardown may not be final, which is why an invoice must still be reconciled.
- A reused PID, a zombie launcher or a changed hostname reads as a live launcher, so that run stays open with its money held, and an `alarm` is raised once it outlives its window. Recovery runs at the next paid launch, or through `ironclad.launcher.launch.recover`. A long-lived process cannot recover a run it started itself.
- A provider reporting `absent` is taken as gone, and a create landing after its window has been released is bounded only by its own TTL. WO-009 tests both for real.
- Between starting a command and handing its group id to the guardian there is a tiny window in which a lost launcher leaves the command running; the TTL still bounds the cost.
- A provider call has a timeout, so a hung provider can delay a stop by that long. POSIX only.

## Accounting (what to report)
- World Model: cost per evaluated checkpoint (M2), physical validation cost separately; total generation + filter + training cost per **accepted** trajectory (M3), with rejected generations counted.
- Omni Drone: itemized delivered BOM; reference setup; spares; batteries; compliance; compute; cost per flight hour and per mission attempt.
- Never remove failed runs from the ledger. An hourly estimate is not the invoice; reconcile.

## Electricity (owner's workstation, when it exists)
About $0.30/kWh in Los Angeles (approximate): ~$50/month for one-card training 6 h/day; ~$75/month for 24/7 inference; dual-GPU training ~$72/month at 6 h/day. Put the measured figure in `config/budget.json.notes` once a meter reading exists.
