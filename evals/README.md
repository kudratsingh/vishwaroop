# evals/

Frozen evaluation specifications: task definitions, groups and shift axes, metrics, **numeric thresholds**, sample-size and stopping rules — written **before** the phase they govern starts and hashed in the phase's exit-test record (`AGENTS.md §5.2`).

File naming: `<phase>-exit-tests.json` (machine-readable thresholds mirrored in `config/phases.json`) and `<phase>-protocol.md` (the narrative). Sealed data itself is never stored here; publish hashes and controlled manifests only.

No real evaluation suite is included in this starter.
