# WO-002 | M0 dataset: scripted and perturbed episodes with successes and failures
**Phase:** M0
**Exit tests advanced:** ET-M0-6
**Size:** M
**Prerequisites:** WO-001 accepted (export, replay and independent outcome exist); `evals/M0-exit-tests.json` has the dataset thresholds frozen (episode count, failure share, failure modes).
**Authorization:** AGENTS §2.1 only (simulator time on an already-approved machine; no new spend).
**Files:** `src/world_model/data/`, `src/world_model/sim/collect.py`, `tests/`, `artifacts/manifests/m0-dataset-*.json`, `reports/WO-002-m0-dataset-successes-and-failures.md`, ignored `data/derived/m0-dataset/`.

## Objective
Collect the first dataset the predictors will learn from: enough episodes, deliberately including failures of several kinds, every one validated and the whole set split-audited — so that M1 has honest training and dev partitions and the evaluator later has failure data to learn from.

## Scope
1. **Perturbed policies.** Variants of the WO-001 baseline: noisy actions, wrong-target grasps, early release, timeouts, randomized object poses outside the nominal range. Each variant is a named `policy.origin: scripted` with its own `scene_group_id`/`session_group_id` plan.
2. **Collection driver** `src/world_model/sim/collect.py`: runs N episodes per variant into a run directory, exports each through the WO-001 adapter, records failure mode labels from the independent outcome code (not from the policy), and writes dataset manifests.
3. **Split specification applied.** Assign `train` / `dev` partitions by scene and session groups as frozen in `evals/M0-protocol.md`; create the `sealed` partition reference without touching it (sealed content is stored under an owner-controlled location; here only hashes and a manifest).
4. **Audit.** `python contracts/v1/audit_splits.py` over every manifest; the dataset registry (`src/world_model/data/registry.py`) records lineage, licenses (sim assets), group ids, and the hash of every episode.
5. **Report** with counts per variant and per failure mode, audit output, cost (simulator hours), and the dataset manifest hash.

## Out of scope
Any learned model; teleop or real data; imagined data; changes to the frozen thresholds (a shortfall is a reported failure, not a reason to lower the bar).

## Deliverables
`src/world_model/sim/collect.py`, `src/world_model/data/registry.py` with CPU tests on fixtures; dataset manifests under `artifacts/manifests/`; report.

## Verification
```bash
make check
python -m world_model.sim.collect --config evals/M0-dataset-plan.json --out data/derived/m0-dataset
python contracts/v1/audit_splits.py data/derived/m0-dataset/*/episode.json
python -m world_model.data.registry summarize artifacts/manifests/m0-dataset-v1.json
```
Expected: ≥ frozen episode count; failure share and failure-mode count at or above the frozen minimum; `audit_splits.py` passes; summary table in the report matches the manifest.

## Exit criteria
ET-M0-6 passes → phase M0 `passed` once ET-M0-1…6 are all recorded (`--phase M0 --event passed --report ...`).

## Stop conditions
Simulator instability that prevents reaching the frozen counts (report the shortfall); any need to edit frozen thresholds; any paid compute without an approval line.

## Report
`reports/WO-002-m0-dataset-successes-and-failures.md`
