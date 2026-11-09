# WO-026 | Storage: inventory the vishwaroop R2 backup and restore one known object to scratch
**Phase:** M2a (data safety; no exit test)
**Exit tests advanced:** none
**Size:** S
**Prerequisites:** (1) the owner's dedicated read-only profile name, endpoint, and bucket or project prefix; (2) the owner's written confirmation that the objects are in Standard storage and that this month's free tier has headroom. **No R2 request of any kind, listing included, before both.**
**Authorization:** owner, 2026-11-09 (`approvals-20261109T022626042919Z-ee024835`): "R2. I'll provide a dedicated read-only profile name, endpoint, and bucket or project prefix separately. Wait for me to confirm Standard storage and free-tier headroom before listing or restoring. Cloudflare rounds billable usage up, so the per-request estimate alone doesn't establish the cost." Earlier, 2026-11-08 (`approvals-20261109T010005936999Z-5e60e401`): "R2 — I'll arrange read-only access scoped to the vishwaroop backup. Use that scope to check the backup inventory and restore one known object to scratch, then verify its SHA-256. Check whether the restore would incur charges first." The earlier item 5 (`approvals-20261108T132556755986Z-2add2fa0`) still requires any drive purchase or data move to come back as a specific proposal.
**Files:**
- `work_orders/`
- `reports/WO-026-r2-backup-check.md`
- scratch outside the repository: the agent's session scratch directory, never `data/`

## Objective
Show whether a separate copy of this repository's episode data exists in R2 and can be restored byte for byte. Today `docs/DATA_AND_SNAPSHOTS.md §7` records one copy: about 8.5 GB under `data/imports` and 1.0 GB under `data/derived`.

## How the credentials arrive (owner)
- **The token:** a Cloudflare R2 API token with **Object Read only**, scoped to the vishwaroop backup bucket.
- **Where it lives:** an AWS CLI profile outside the repository, e.g. `~/.aws/credentials` under `[vishwaroop-r2-ro]`.
- **What the owner tells the agent:** the profile name, the account endpoint (`https://<account id>.r2.cloudflarestorage.com`) and the bucket name.
- **What the agent never does:** read the credentials file, print the keys, or write them anywhere (`AGENTS.md §10.1`).

## Charge check, before any request (from Cloudflare's R2 pricing page, read 2026-11-09)
| Item | Price | Free each month |
|---|---|---|
| `ListObjects` (Class A) | $4.50 per million (Standard); $9.00 (Infrequent Access) | 1 million Class A |
| `HeadObject`, `GetObject` (Class B) | $0.36 per million (Standard); $0.90 (Infrequent Access) | 10 million Class B |
| Egress | none, for any storage class | — |
| Retrieval from Infrequent Access | $0.01 per GB | the free tier does not apply to Infrequent Access |

**Rounding.** Cloudflare rounds usage up to the next billing unit. Its examples: "If you have performed one million and one operations, you will be billed for two million operations"; "If you have used 1.1 GB-month, you will be billed for 2 GB-month"; Infrequent Access retrieval of 1.1 GB is billed as 2 GB.

So a per-request estimate does not establish the cost. Once an account is past its free tier, a single further `ListObjects` is billed as a whole million Class A operations ($4.50 Standard; $9.00 Infrequent Access). A single Infrequent Access retrieval is billed as at least 1 GB ($0.01). The earlier draft's "under $0.001" worst case was wrong for that reason and is withdrawn.

**What establishes the cost:** the owner's confirmation, from the Cloudflare dashboard, that:
- (a) the objects to be listed and restored are in **Standard** storage;
- (b) this month's Class A and Class B usage leaves headroom under the free tier (1 million and 10 million) for the planned requests.

With both, the planned requests cost $0. The agent cannot check either with an Object-Read token. The planned requests, estimated:
- about 1 `ListObjectsV2` per 1,000 objects under the bucket or prefix the owner names;
- 1 `HeadObject` and 1 `GetObject` for the restore, on an object of a few MB or less.

`HeadObject` also reads the storage class. If it reports anything other than Standard, the agent stops before `GetObject` and reports it.

## Scope
1. **Inventory (read-only), only after both prerequisites:** `aws s3api list-objects-v2 --profile <profile> --endpoint-url <endpoint> --bucket <bucket> [--prefix <prefix>]`, paginated.
   - Recorded: key, size, ETag and storage class, plus the counts and total size.
   - It is compared with the local `data/imports/*/MANIFEST.json` files and `data/derived/` (names and sizes). Missing, extra and size-mismatched objects are listed.
2. **The known object:** the smallest object whose local copy is listed, with its sha256 and size, in an import manifest under `data/imports/*/MANIFEST.json` (written at import time and read-only since). Its hash is the one recorded then, not one computed now.
3. **Restore:** `HeadObject` (storage class and size), then `GetObject` into the session scratch directory. Never `data/`, and nothing overwritten.
4. **Verify:** compute the restored file's sha256 and compare it with the manifest's value. Pass only on an exact match.
5. **Report:**
   - the inventory summary and the comparison;
   - the request count;
   - the charge reasoning;
   - the verification result;
   - what a full second copy would still need, as a specific proposal for the owner if anything is missing.

## Out of scope
- Any R2 write, delete or copy; any bucket setting.
- Restoring into `data/`.
- Moving or deleting local data.
- Buying a drive.
- Reading another project's R2 configuration (`AGENTS.md §1.1`).

## Verification
The report quotes the inventory's counts and total, the object key, its size and storage class, the manifest hash and the restored hash. `make check` passes.

## Exit criteria
Done when the report states either a byte-identical restore of the known object, or exactly why the restore was not done (no credentials, Infrequent Access fee, missing object, hash mismatch).

## Stop conditions
- Any step that would write to R2 or to `data/`.
- No owner confirmation of Standard storage and free-tier headroom: no request at all.
- An object not in Standard storage: stop before `GetObject` and report it.
- A credential error or an access-denied: report it as out of scope, without retrying under other credentials.
- Any request count beyond the plan by more than ten times.

## Report
`reports/WO-026-r2-backup-check.md`

## Progress (append-only)
