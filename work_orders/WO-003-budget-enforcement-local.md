# WO-003 | Supervised resource and spend enforcement (local, no paid execution)
**Phase:** M0
**Exit tests advanced:** none directly (enables every later paid run; required before any GPU rental is approved)
**Size:** M
**Prerequisites:** none (pure local engineering). Can run in parallel with WO-001 in its own worktree; file ownership below does not overlap.
**Authorization:** AGENTS §2.1 only. Real cloud launch, payment, credentials and provider writes are out of scope and remain §2.3 gates.
**Files:** `tools/launcher/`, `tests/test_launcher.py`, `config/budget.schema.json`, `docs/BUDGET_AND_LAUNCHER.md` (append an "Implemented" section), `reports/WO-003-budget-enforcement-local.md`.

## Objective
Implement the enforcing side of `docs/BUDGET_AND_LAUNCHER.md` without enabling paid execution: approval validation bound to run id and hashes, atomic reservation in the cost ledger, local process supervision with wall and step limits, a fake-provider lifecycle adapter, and failure-injection tests — so that when the owner approves a first paid pilot, the controls already exist and are tested.

## Scope
1. `tools/launcher/approval.py`: parse `ledgers/approvals.jsonl`; an approval is valid only if it binds `run_id`, `command_sha256`, `config_sha256`, `cost_ceiling_usd`, `resource_count`, `expires_at`, and is not expired. A free-form flag never substitutes.
2. `tools/launcher/reserve.py`: project-wide lock file; atomic append of `planned` and `reserved` events; refuse when the sum of live reservations would exceed `approved_project_cap_usd`; the cap cannot be raised from the CLI (test it).
3. `tools/launcher/supervise.py`: run a child without shell interpolation; enforce a wall timeout; pass `--max-steps` to the trainer and watch a progress file to detect ignored step limits; terminate children on parent exit; append `running`, `completed|failed|interrupted|cancelled` events.
4. `tools/launcher/provider_fake.py`: a fake provider whose "instance" can stay billable after the child dies; teardown verification and reconciliation events; this is the interface a real provider adapter must implement later.
5. Failure-injection tests: trainer crash, stale progress, SIGTERM, parent loss, API timeout with retry idempotency, duplicate launch, concurrent reservations, stale quote, overspend attempt, resource left billable after child exit.
6. `tools/budget_preflight.py` stays the estimator; the launcher calls it first.

## Out of scope
Any real provider API, secrets, network writes, actual spend, changes to `config/budget.json` caps, GPU work.

## Verification
```bash
make check
python -m pytest tests/test_launcher.py -q
python tools/launcher/supervise.py --dry-run --plan config/cpu-smoke-plan.json --budget config/budget.json   # must refuse: no approval
```
Expected: all failure-injection tests pass; a run without a matching approval is refused; concurrent reservations never exceed the cap; the fake provider's leftover-instance case triggers teardown and a reconciliation event.

## Exit criteria
Tests green and the report lists the remaining gap: a real provider adapter with a $1-class owner-approved pilot (its own future WO). `config/budget.json` is unchanged (still $0).

## Stop conditions
Any need for credentials, network writes or real resources; any temptation to make the preflight "just launch it".

## Report
`reports/WO-003-budget-enforcement-local.md`
