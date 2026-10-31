# Shared trajectory contract v1.0.0 (kit release 2026-10-31)

One contract release consumed by three producers: the arm export adapter (future, owner-provided; `producer: arm`), Omni Drone (`producer: banshee`), and World Model & Planner (`producer: vishwaroop`). The several schemas here are parts of one release, not extra projects or live services. It is the **only** shared technical boundary between the two repositories (`AGENTS.md §11`).

## Layout
| File | Purpose |
|---|---|
| `episode.schema.json` | episode manifest: semantics, provenance, configuration, policy identity, split lineage, simulator identity, validation, outcome, data reference |
| `transition.schema.json` | JSONL records with aligned observations, action stages, timing, validity masks |
| `validation_ledger.schema.json` | one line of an **append-only** ledger that attaches post-export evidence to an episode without editing its manifest |
| `validate.py` | schema + local integrity + temporal/action/provenance checks; `--ledger` merges ledger evidence |
| `audit_splits.py` | duplicate-id, parent-lineage, declared-group leakage and policy-run checks over an assembled set |
| `writer.py` | reference exporter: builds an episode directory atomically, validates it, refuses to overwrite |
| `model-manifest.template.json` | later model-export boundary; intentionally incomplete, not deployable |
| `examples/` | three **FABRICATED** fixtures for serialization tests (arm_sim, drone_sim, imagined_arm), not experiment evidence |
| `RELEASE.json`, `SHA256SUMS.json` | release identity and byte pins |

## Run
```bash
python -m pip install -r requirements.txt
python validate.py examples/arm_sim/episode.json
# the append-only ledger merge is exercised in tests/test_contract.py (fixtures carry no statuses)
python audit_splits.py examples/arm_sim/episode.json examples/drone_sim/episode.json examples/imagined_arm/episode.json
python -m pytest tests -q
```

## Semantic rules
- Every action label has a unit and a frame; equal dimensionality never implies equal action meaning.
- Requested, filtered, transmitted, and measured-applied are separate stages; unknown stages and times are `null`. Never fabricate an applied timestamp from the send time.
- Timestamps are nanoseconds in a declared monotonic clock domain; the clock-alignment artifact preserves native timestamps and uncertainty.
- Inputs must have arrived by decision time. `reference_only` and `supervision_only` streams are never policy inputs.
- Validity masks are per stream in v1; represent partially valid vectors as separate streams or propose a contract extension. Missing input has a `null` payload and `valid: false`. Images and depth use immutable artifact references.
- Production JSONL may reference frame files or packed artifacts with adapter metadata; this validator does not implement random access inside video/container files.

## Append-only rule (new in this release)
An episode directory is **written once** (`writer.py` refuses an existing target). Evidence that arrives later — a physics replay of an imagined episode's actions, a physical assessment of a real episode — is **appended** to a validation ledger (`validation_ledger.schema.json`) and merged at read time with `validate.py --ledger`. Manifests are never edited. A replay or physical execution also produces a **new** episode (physics_sim or real) linked to its parent through `provenance.parent_episode_ids`.

## Integrity and scale
Artifact paths are relative to each episode directory, portable, content-hashed and local. The validator refuses path traversal and symlink escapes; it does not fetch remote URLs or unpickle data. Hashing may be expensive for large data; the reference CLI loads JSONL in memory and is for bounded exports. Streaming validation and chunked stores are future adapters. No deserialization of model weights.

## Provenance and validation
`real` / `physics_sim` / `imagined` describes how observations were produced and never changes. `replay_checked` requires physics-replay evidence; it does not mean a physical test. `physically_evaluated` requires real observations plus a matching physical assessment. Schema fixtures carry no validation statuses. Parent ids and split inheritance are mandatory for imagined records. Global lineage is checked on an assembled set by `audit_splits.py`; a single-file validator cannot prove global independence.

## Replay
A physics_sim record must identify its initial state and assets. Replay restores the **initial state only** (`restore_mode: initial_state_only`); forcing intermediate states is incompatible with claiming action executability. A schema pass does not prove a simulator was run; inspect the report and evidence artifacts.

## Change control
Release bytes are pinned by `SHA256SUMS.json`; `config/contract-lock.json` in each repository pins the manifest hash and `tools/check_hashes.py` verifies on every CI run. No silent per-repo edits. Additive semantics are a new minor release with tests and fixtures; breaking changes are a new major release plus adapter migration for every pinned consumer (`AGENTS.md §11.3`). Model manifests later join this same boundary; they cannot grant command authority.
