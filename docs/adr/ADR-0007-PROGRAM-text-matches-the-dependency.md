<!-- ironclad-policy v1.2.0 -->
# ADR-0007 — Program text says what the dependency made true

**Date:** 2026-10-31 · **Status:** accepted (owner approval recorded in `ledgers/approvals.jsonl`) · **Work order:** WO-010 in `ironclad` · **Program link:** PROGRAM §0, §6; `ironclad`'s `AGENTS.md §13.5`

## Context
ADR-0004 made shared material a versioned dependency, and `ironclad` `v1.0.0` replaced the vendored copies and hash locks with `ironclad verify`. Three passages still described the old arrangement, and ADR-0004 itself showed a pin form `verify` refuses, because the distribution was later named `ironclad-kit` (`ironclad` on PyPI is an unrelated project). The contract README's commands and change-control paragraph were out of date too. The owner approved aligning the text on 2026-10-31: "Text alignment only, no rule changes." The owner also directed corrections of fact in `PROGRAM.md §12` row 7, which still said no remote was designated, and in `§9`, in the same release, the second because a measurement in `vishwaroop` overtook it. The evidence for `§9` is the owner's statement; the measurement lives in `vishwaroop`. Each repository's private visibility was read from GitHub on the day. The independent review then found other lines of the same documents still saying the opposite, a stop condition; on 2026-11-01 the owner approved the wording table in `ironclad`'s `reports/BLOCKER-2026-11-01-stale-policy-lines.md`, with the owner's own text for `PROGRAM.md §10` item 5.

## Decision
**No rule changes.** `§9` records facts agents must respect, so what an agent may assume about where ManiSkill3 runs does change; it authorizes no purchase or plan change. These words change, in policy version 1.2 and `PROGRAM.md` version 1.2. The policy number here is this release's; drafts elsewhere that used the same number are not adopted.

| Where | Before | After |
|---|---|---|
| `AGENTS.md §11.1` | `contracts/v1/` is the only shared boundary, byte-identical in both repositories, pinned by `config/contract-lock.json`, verified by `tools/check_hashes.py` | The contract `ironclad.contracts.v1` is the only shared boundary, consumed unchanged from the pinned `ironclad` release; shared material comes from that package, pinned by version, not vendored copies with hash locks; `ironclad verify` checks this on every CI run |
| `PROGRAM.md` header (line 4 of the canonical file; line 5 in a generated copy, after the marker) | Canonical copies, byte-identical in each repository, pinned in `config/program-lock.json` | Canonical source: the `ironclad` package at the version each repository pins; `ironclad sync-policy` writes each repository's copy; the Claude Project keeps a copy |
| ADR-0004 decision 2, and an Amendment section at its end | `ironclad @ git+…@vX.Y.Z` | `ironclad-kit @ git+…@vX.Y.Z`, or a full commit |
| `PROGRAM.md §9`, environment facts | ManiSkill3 (SAPIEN) and Isaac Lab are Linux + CUDA only and do not run on the Macs | ManiSkill3 CPU physics runs on the M3 Pro with MoltenVK (measured by `vishwaroop`, 2026-11-01); its GPU simulation and large-scale visual work still need Linux + NVIDIA; Isaac Lab is unchanged |
| `PROGRAM.md §12` row 7 | None designated; local git only; blocks pushes and PRs | Designated: `kudratsingh/banshee`, `kudratsingh/vishwaroop`, `kudratsingh/ironclad`, all private; blocks nothing |
| `AGENTS.md` line 3 | Core byte-identical across both repositories, sha256 in `VERIFICATION.md`; changed by an ADR applied to both repositories | Core generated from the pinned `ironclad` release (`ironclad sync-policy`); changed by a program-level ADR in `ironclad`, reaching each repository through a release |
| `AGENTS.md §4.4`, §5.5, §6.1, §6.8, §8.6, §9.2, §10.1, §11.4 | `tools/…`, `src/*/core/…`, `contracts/v1/…` paths; `mypy` on `tools/`; hash checks | The installed commands and modules: `ironclad verify`, `ironclad-check-immutable`, `ironclad-status`, `ironclad.core.ledger`, `.artifacts`, `.runs`, `ironclad-audit-splits`, `ironclad-budget-preflight`, `ironclad-scan-secrets`, `ironclad.contracts.v1`'s `model-manifest.template.json`; `mypy` on `src/` |
| `PROGRAM.md` line 6, line 92 | `contracts/v1/`, `contracts/v1/README.md` | The contract in `ironclad.contracts.v1`, and its README |
| `PROGRAM.md` line 17, line 20 | The same change applied to both repositories; edit the Project copy and paste it into both | Released through `ironclad`, each repository moving its pin; the Project copy refreshed from the release |
| `PROGRAM.md §6` | Byte-identical vendored `contracts/v1`, hash-pinned | `ironclad.contracts.v1` from a pinned `ironclad` release |
| `PROGRAM.md §10` item 5 | One shared technical boundary (the contract), vendored identically; everything else is per project | One shared technical boundary (the contract), plus shared tooling and policy, all from a pinned `ironclad` release; no shared runtime; everything else is per project |
| Version lines | policy 1.1; `PROGRAM.md` 1.1 | policy 1.2; `PROGRAM.md` 1.2, dated 2026-11-01, with a §14 row, as `PROGRAM.md §0` requires |
| Contract README | Runs `python validate.py` beside the files; change control cites the lock and `tools/check_hashes.py` | Installed commands; change control cites the package and `ironclad verify` |

"Pinned by version" means a pin at a tag or a full commit, the two forms `ironclad verify` accepts (ADR-0004 decision 2, `ironclad`'s `docs/DESIGN.md §9`).

**Contract change control (`ironclad`'s `AGENTS.md §13.6`).** Only the README, `RELEASE.json` and the manifest change. `schema_version` stays 1.0.0. No schema, fixture or utility byte changes, so no fixture is regenerated. **No migration is needed for existing episode data, as of 2026-10-31:** nothing about an episode's meaning or validity changes. The owner's direction is that consumers bump when convenient. `AGENTS.md §11.3` asks both repositories to adopt a contract release in the same week or record why not; this is the record of why not: no semantic change, so there is nothing to adopt together.

## Not changed
- The dated `PROGRAM.md §11` row of 2026-10-31 ("carried identically in both repositories"), which records a decision at its date.
- **Whether consumers must adopt the same release.** Contract `RELEASE.json` ("both repositories adopt the same release"), `AGENTS.md §11.3` (adopt in the same week or record why not) and `PROGRAM.md §6` ("both consume the same release") stay as they are in this release. This is an open item the owner logged for a later program ADR (`ironclad`'s `docs/OPEN_ITEMS.md`): they conflict with consumers being allowed to lag, and what has to match for data exchange is the contract `schema_version`, not the package version.

## Alternatives considered
| Option | Why not |
|---|---|
| Release with the other lines stale, new text winning | every consumer would inherit a stop condition when it bumps; the owner approved the wording instead |
| Leave the text and rely on release notes | the owner decided against it |
| A new contract major or minor version | nothing about a record changes; `schema_version` is about records |

## Consequences
Consumers bump when convenient. The bump changes marker lines, the passages above, and adds this ADR's file. A project's own ADR may share this number; the file names differ and `sync-policy` never touches a project ADR. Tests reverse each edit and require the original source hash, so any other change to the core, `PROGRAM.md` or ADR-0004 fails; this ADR and the shared process documents are not pinned that way.

## Reversibility
A later release can restore the words. A consumer on an older release is unaffected. Ledger lines stay.
