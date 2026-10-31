# ledgers/

Append-only JSON Lines ledgers (one JSON object per line, opened in append mode only — `core.ledger.append_record`). Tracked in git; CI fails any PR that modifies or deletes a line (`tools/check_immutable.py`).

| File | One line per |
|---|---|
| `runs.jsonl` | run start and run end |
| `costs.jsonl` | planned / reserved / running / cancelled / interrupted / completed / reconciled spend event |
| `approvals.jsonl` | dated owner approval: scope, quoted words, expiry, record_id |
| `imports.jsonl` | completed export imported from another project, with hashes and producer identities |
| `corrections.jsonl` | correction or retraction that references what it corrects |
| `sealed_access.jsonl` | one authorized opening of a sealed suite (`config/sealed-access.schema.json`) |
| `licenses.jsonl` | license of every external dataset, asset, model or dependency before use |

Mistakes are corrected by appending, never by editing.
