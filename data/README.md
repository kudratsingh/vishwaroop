# data/

Operational data. **Append-only; never delete or overwrite** (`AGENTS.md §6`, `docs/DATA_POLICY.md`).

- `raw/` — raw sensor/controller/simulator logs exactly as produced (ignored by git; manifests tracked under `artifacts/manifests/`).
- `derived/` — training-ready exports with transformation version and source hashes (ignored by git).
- `imports/<export id>/` — read-only copies of completed exports from other projects, recorded in `ledgers/imports.jsonl`.
- Episode exports follow `contracts/v1` and must pass `contracts/v1/validate.py` before any manifest references them.
