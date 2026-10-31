# BUDGET_AND_LAUNCHER.md — spend control

**Approved spend for this repository today: $0** (`config/budget.json`). Planning ranges in `PROGRAM.md §9` and in the owner's purchase plan are not approvals or quotes. An agent cannot approve its own spending by editing a file or passing a flag (`AGENTS.md §2.3, §9`).

## What exists now
`tools/budget_preflight.py` is a runnable **cost estimator and refusal check**. It never launches anything, never reserves funds, never stops a rental. Its tests (`tests/test_budget_preflight.py`) prove the arithmetic and the refusals, nothing more.

## Estimating a run (from a measured pilot)
Inputs: GPU count, quoted hourly rate with its timestamp, planned steps, **measured** seconds per step from a short pilot, setup/evaluation/transfer/shutdown time, storage/egress/taxes, and an explicit uncertainty margin.

- Expected runtime = steps × measured seconds/step + overhead. Bound it with a separate hard wall timeout.
- Reserve the **conditional** bound (rate × hard wall + fixed costs, with margin) against both the run cap and the remaining project cap before starting.
- GPU price × steps alone is dimensionally wrong. Unknown rate, timing, overhead, or shutdown behaviour fails closed.
- Stopping the trainer does not stop the rental. The bound is conditional on verified provider teardown.

## The enforcing launcher (future work order; not implemented)
Acceptance for the launcher WO:
1. An owner approval binds run id, command/config hashes, exact cost ceiling, resource count, and expiry (`ledgers/approvals.jsonl`).
2. Project-wide lock; atomic reservation in `ledgers/costs.jsonl`; concurrent reservations never exceed the cap; the cap cannot be raised from the CLI.
3. Runs without shell interpolation; supervisor wall timeout; trainer-side `max_steps` plus a progress watchdog that detects ignored step limits; the parent terminates children it started.
4. Ledger events: planned, reserved, running, cancelled, interrupted, completed, reconciled. Failed runs stay.
5. Provider teardown by instance TTL or an independent watchdog; process kill is **not** pod shutdown; provider state is verified after teardown and actual billing is reconciled.
6. Failure injection tests: trainer crash, stale progress, SIGTERM, parent loss, API timeout, retry idempotency, duplicate launch, concurrency, stale quote, overspend, resource left billable after child exit.
7. Until cloud-lifecycle tests pass against a fake provider and then a real one with a $1-class pilot approved by the owner, paid launches stay prohibited regardless of local timeout tests.

## Accounting (what to report)
- World Model: cost per evaluated checkpoint (M2), physical validation cost separately; total generation + filter + training cost per **accepted** trajectory (M3), with rejected generations counted.
- Omni Drone: itemized delivered BOM; reference setup; spares; batteries; compliance; compute; cost per flight hour and per mission attempt.
- Never remove failed runs from the ledger. An hourly estimate is not the invoice; reconcile.

## Electricity (owner's workstation, when it exists)
About $0.30/kWh in Los Angeles (approximate): ~$50/month for one-card training 6 h/day; ~$75/month for 24/7 inference; dual-GPU training ~$72/month at 6 h/day. Put the measured figure in `config/budget.json.notes` once a meter reading exists.
