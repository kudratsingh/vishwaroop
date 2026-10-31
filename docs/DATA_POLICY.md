# DATA_POLICY.md — records, retention, provenance, imports, privacy

Rule summary in `AGENTS.md §6`. This file is the operating detail.

## 1. Append-only, never delete, never overwrite

**The rule.** Data, runs, logs, ledgers, reports, artifacts and accepted work orders are written once. Nothing in these locations is deleted, truncated, renamed over, or edited in place. Corrections are new records that point at what they correct.

**Why.** A deleted failed run is a lost negative result; an edited log is an unverifiable one; an overwritten checkpoint is an unreproducible experiment. The owner's rule is absolute: *never delete any data/runs/logs; never overwrite; always append or create a new record.*

**How it is enforced.**

| Mechanism | What it protects | Where |
|---|---|---|
| `tools/check_immutable.py` in CI on every PR | tracked files under `data/`, `runs/`, `ledgers/`, `reports/`, `artifacts/`, accepted `work_orders/WO-*.md` — any `M`/`D`/`R` in `git diff --name-status` fails the PR (allow-list: derived files `docs/STATUS_BOARD.md`, `reports/INDEX.md`) | CPU tier |
| `core.ledger.append_record` | opens ledgers with `O_APPEND`, writes one JSON line, fsyncs; no truncation path exists | `src/<pkg>/core/ledger.py` |
| `core.artifacts.ArtifactStore.put` | content-addressed by sha256; refuses to replace a path whose bytes differ; `delete` does not exist | `src/<pkg>/core/artifacts.py` |
| `core.runs.new_run_dir` | creates `runs/<UTC timestamp>_<id>/` with exclusive create; refuses if it exists; never reuses ids | `src/<pkg>/core/runs.py` |
| `contracts/v1/writer.py` | writes an episode directory atomically and refuses to overwrite an existing episode | contract release |
| Discipline for ignored paths | the same rule applies to untracked `data/` and `runs/` content; agents never run deletion commands there | `AGENTS.md §1.3, §6.1` |

**Corrections.** A wrong label, a bad calibration, a mis-stated result: append a correction record (`ledgers/corrections.jsonl`) with `corrects: <record id or path>`, `reason`, `actor`, `ts`, and the corrected content or a pointer to a new artifact. Reports get an **Errata** section appended at the end, dated. The original stays.

**Archival (owner only).** Old large artifacts may be moved to cheaper storage. The manifest, hashes and a `moved_to` note stay in place. The repository never loses the ability to say what existed.

## 2. Run directories

Every run (training, evaluation, replay, generation, flight, bench session) gets `runs/<YYYYMMDDTHHMMSSZ>_<8-char id>/` containing at minimum:

```
config.snapshot.json     exact configuration used
env.lock.json            versions, container digest, hardware
git.json                 commit, dirty flag, branch
seeds.json
metrics.jsonl            append-only metrics stream
events.jsonl             append-only structured log
manifest.json            inputs (hashes), outputs (hashes), cost line id, status
```
`ledgers/runs.jsonl` gets one line at start (`status: started`) and one at end (`status: completed|failed|interrupted`). A run that crashes keeps everything it wrote.

## 3. Artifacts and manifests

- Stored content-addressed: `artifacts/sha256/<first2>/<hash>` (ignored by git) with `artifacts/manifests/<name>.json` (committed) recording: producer, inputs, code commit, env lock, license, size, created_at, `moved_to` if archived.
- Large files never enter git. The `.gitignore` covers `data/`, `runs/`, `artifacts/sha256/`, `checkpoints/`, `raw_logs/`, video extensions, `*.safetensors`, `*.ckpt`, `*.pt`.
- Model weights: `safetensors` preferred; `torch.load` only with `weights_only=True`; hash verified before load.
- Episode exports follow `contracts/v1` and are validated (`validate.py`) before being referenced by a manifest.

## 4. Imports from other projects (read-only)

Inputs from the arm project (episodes, checkpoints, sim results) or from the drone project (flight logs) arrive only as **completed, immutable exports**:

1. The producer writes into a temporary directory, computes hashes, writes `MANIFEST.json`, then atomically renames the directory into the export root and writes a `COMPLETE` marker file last.
2. The importer (`src/<pkg>/importer.py` or the project's equivalent) refuses any export without `COMPLETE`, with a manifest hash mismatch, or with paths that escape the export root; it never writes into the export root, never acquires locks there, never polls another project's working directories.
3. Imported bytes are copied or hard-linked under an explicit read-only policy into this project's `data/imports/<export id>/` and recorded in `ledgers/imports.jsonl` with hashes and the producer's identities (run family, checkpoint, dataset, protocol version).
4. Automatic export hooks inside the producer are a **future owner-approved producer change**; neither new project adds them.

## 5. Splits, lineage, sealed data

- Partitions: `train`, `dev`, `sealed`, `regression`. Declared before training. Grouped by session and by policy run/family. Synthetic descendants inherit their parent's partition.
- `contracts/v1/audit_splits.py` runs on assembled manifests before any training or evaluation claim.
- Sealed data lives outside agent reach (owner-controlled location). Each opening is one owner-authorized event logged in `ledgers/sealed_access.jsonl` (`config/sealed-access.schema.json`), with frozen candidate hashes and analysis code hash recorded first. A revealed suite becomes `regression`; new confirmatory claims need a fresh disjoint suite.

## 6. Licenses

Record the license of every external dataset, asset, model, and code dependency in `ledgers/licenses.jsonl` before use. Training on non-commercial or model-output-restricted data is a program-level decision (the owner has excluded such data in the coding-agent project; assume the same here until told otherwise).

## 7. Privacy and footage

- Cameras are pointed at the bench and the test volume; faces, private spaces, documents, screens, and location-identifying detail are excluded by framing where possible and blurred before any sharing.
- Footage retention: raw episode video is retained like any other artifact (append-only, local/object storage). Public release of any footage is a §2.3 owner decision.
- Flight logs may contain GPS; strip or offset coordinates before any public release; keep the raw log private.

## 8. Retention summary

| Record | Where | Retained | Deleted |
|---|---|---|---|
| Ledgers (`runs`, `costs`, `approvals`, `imports`, `corrections`, `sealed_access`, `licenses`, `status`) | `ledgers/`, `work_orders/STATUS.jsonl` (git) | forever | never |
| Reports and ADRs | `reports/`, `docs/adr/` (git) | forever | never |
| Run directories | `runs/` (ignored) + manifests (git) | forever (archive allowed) | never |
| Raw sensor/flight logs | `data/raw/` (ignored) + manifests | forever (archive allowed) | never |
| Derived datasets | `data/derived/` + manifests | forever (archive allowed) | never |
| Checkpoints | `artifacts/sha256/` + manifests | forever (archive allowed) | never |
| Scratch/temp | `tmp/` inside the run dir | until the run ends | by the run itself only |
