# WO-006 | Read-only arm snapshot import and policy-holdout registry
**Phase:** M1
**Exit tests advanced:** none directly (prerequisite for ET-M1-2 VLA-chunk comparisons and all of M2)
**Size:** M (can run in parallel with WO-004 in its own worktree)
**Prerequisites:** `src/world_model/importer.py` (exists, tested on fixtures); at least one completed, owner-provided export from `vla-rl-so101` placed in a read-only location the owner names. Without an export, this WO stops at the registry design and fixture tests.
**Authorization:** AGENTS §2.1 only. Never edit, launch, or hook into the arm repository (§1.1, §2.3).
**Files:** `src/world_model/importer.py` (extend), `src/world_model/data/policies.py`, `tests/`, `ledgers/imports.jsonl`, `reports/WO-006-arm-snapshot-importer-and-policy-registry.md`.

## Objective
Register arm checkpoints and sim results as immutable, hash-verified inputs with run/family identities, and build the policy-holdout registry that quarantines designated test runs so the evaluator is never calibrated on their real outcomes.

## Scope
Export verification (`COMPLETE`, manifest hashes, path containment); write-once copy under `data/imports/`; `ledgers/imports.jsonl` entries with producer identities (run family, seed, checkpoint, training dataset, base weights, evaluation protocol); policy registry with `holdout: true|false` per run/family and a test that forbids holdout runs in any train/dev manifest; documentation of what the arm project must export (`docs/DATA_AND_SNAPSHOTS.md §4`), as a request to the owner, not an edit.

## Out of scope
Any automatic export hook in the arm repo; loading model weights (hash and register only); training.

## Verification
```bash
make check
python -m world_model.importer verify <export dir>           # refuses without COMPLETE / on hash mismatch
python -m world_model.importer register <export dir>         # copies write-once, appends ledgers/imports.jsonl
python -m pytest tests/test_importer.py tests/test_policies.py -q
```

## Stop conditions
No completed export available (finish the fixture-backed parts and report); an export with a mismatched hash (refuse, report, never "fix" it); any request that implies editing the arm project.

## Report
`reports/WO-006-arm-snapshot-importer-and-policy-registry.md`
