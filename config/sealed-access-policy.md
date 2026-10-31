# Sealed-access policy

One line per opening in `ledgers/sealed_access.jsonl`, validated against `config/sealed-access.schema.json`:
`record_id, ts, suite_id, milestone_id, protocol_version, frozen_candidate_hashes, analysis_code_sha256, approver, approval_ref, opened_at, released_outputs, reason, prior_openings, resulting_status, replacement_suite_id`.

- One opening per named suite per milestone report is a ceiling, not a license to reuse revealed data as fresh evidence.
- `approval_ref` points at the owner's dated approval in `ledgers/approvals.jsonl`; an opening without it is a stop condition.
- After an opening, `resulting_status` is `regression`; a new confirmation suite gets a new `suite_id` recorded in `replacement_suite_id`.
- No access-control service is included. Keep the sealed data itself outside agent training access (owner decision pending: `docs/CONTEXT_AND_DECISIONS.md §5`).
