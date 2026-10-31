# artifacts/

- `sha256/<first two hex>/<sha256>` — content-addressed bytes (ignored by git; written by `core.artifacts.ArtifactStore.put`, which refuses to replace differing bytes and has no delete).
- `manifests/<name>.json` — tracked manifests: producer, inputs, code commit, environment lock, license, size, created_at, `moved_to` if archived.

Nothing here is deleted. Archival moves bytes and leaves the manifest (`docs/DATA_POLICY.md §1, §3`).
