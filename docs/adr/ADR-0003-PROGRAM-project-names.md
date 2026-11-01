<!-- ironclad-policy v1.2.0 -->
# ADR-0003 — Project names: `banshee` and `vishwaroop`

**Date:** 2026-10-31 · **Status:** accepted · **Work order:** WO-006 in `banshee`; WO-007 in `vishwaroop` · **Program link:** PROGRAM §5, §11, §14

## Context
The owner decided the project names on 2026-10-31. Both starter kits still carried the old identifiers, including in files that must stay byte-identical across the repositories: `PROGRAM.md`, the shared `AGENTS.md` core (sections 1–12) and `contracts/v1/`. The episode schema's `producer` enum and two fabricated example episodes are among them, so this is a contract change (`AGENTS.md §2.3, §11`) and needs a program-level ADR.

## Decision
1. **Names and meanings.**
   - **`banshee`** is the Omni Drone repository and Python package: the spirit whose wail forewarns a death, and the sound a quadrotor makes.
   - **`vishwaroop`** is the World Model & Planner repository and Python package: Sanskrit *viśvarūpa*, the universal form Krishna shows Arjuna, all of creation seen at once. A world model sees everything and is trusted only as far as it has earned.
2. **Where the short names apply.** Repository paths, package imports, `config/phases.json#project` and contract `producer` values use them. "Omni Drone" and "World Model & Planner" stay valid in prose and docs.
3. **Contract.** The `producer` enum becomes `arm`, `banshee`, `vishwaroop`, and the `drone_sim` and `imagined_arm` fixtures use the new values. `RELEASE.json` names the new consumers.
4. **Contract version.** `schema_version` stays `1.0.0`, with release label `1.0.0+kit.2026-10-31.names`. The owner decided on 2026-10-31 that the major-version rule does not apply and that `contracts/v1/` must not carry 2.0.0: this rename predates any data, because no episode data exists outside the fixtures. Once the first real episode exists, `AGENTS.md §11.3` applies in full.
5. **What stays.** The directory stays `contracts/v1/`. `omni-world trajectory contract` and the `urn:omni-world:...` schema ids stay as they are; they name the contract, not a repository or package.
6. **`PROGRAM.md`** becomes version 1.1: §5.1 and §5.2 state the repository and package names, and §11 and §14 gain dated rows.
7. **`AGENTS.md` core** becomes policy version 1.1, gains a Names paragraph after the policy header, and its header sentence about the core being byte-identical now names `banshee` and `vishwaroop`. No rule changes.
8. **ADR numbers.** This program ADR takes ADR-0003 in both repositories. Planned project ADRs move up one: in `banshee`, the D0 airframe and stack ADR becomes ADR-0004 and the D1 frame and timebase ADR becomes ADR-0005; in `vishwaroop`, the M0 task-choice ADR becomes ADR-0004.

## Shared files changed
`banshee` is the single source. `vishwaroop` copies these byte for byte from the `banshee` commit and authors nothing shared:
- `PROGRAM.md`
- `AGENTS.md`, bytes before the `## 13.` heading
- everything under `contracts/v1/`
- `config/contract-lock.json`
- `config/program-lock.json`
- `docs/adr/ADR-0003-PROGRAM-project-names.md` (this file)

## Hash table
| Item | sha256 |
|---|---|
| `PROGRAM.md` | `58f4c930ca08aaa2fd630826905e9ef9892968e7ceda8e2d920863f5142d02a9` |
| `config/program-lock.json` | `6c6e8cf7ddfb8434754b223d12e1d12a23023be7da2a41e6f118f964c0f77e17` |
| `contracts/v1/SHA256SUMS.json` | `9c0b9347be3758b359c7c7e9fdf7eb7798086167fb1162112fcc9d22bd5a61c3` |
| `config/contract-lock.json` | `f8c3cc1f24919af858a6d77038f3e2127f64d6206610e02f7d9b6b59cbe595ff` |
| `AGENTS.md` core (bytes before `## 13.`) | `8f174fdc05d6184675491181d91a9a8921f7678b22006378f696ec27847659b6` |

## Alternatives considered
| Option | Why not |
|---|---|
| Keep the old `producer` values and rename only repositories and packages | contradicts the owner's decision; contract records would name projects that no longer exist under those names |
| New major contract release (`schema_version` 2.0.0) | the owner ruled it out: the rename predates any data, and `contracts/v1/` must not carry 2.0.0 |
| Accept both old and new `producer` values | keeps retired names in the contract permanently, and no record needs them |

## Consequences
- Any record using a retired `producer` value now fails validation. None exists outside the fixtures changed here.
- The change is complete only when both repositories carry the same bytes and each one's `make check` is green. Neither repository's change merges to `main` until the hashes above are confirmed in both, or until the owner records why not (`AGENTS.md §11.3`).
- The owner's Claude Project copy of `PROGRAM.md` must be updated to version 1.1.
- This decision authorizes no remote, purchase or hardware action.

## Reversibility
Low cost while no real records exist: revert the rename commits in both repositories. After real episodes exist, changing `producer` values again would be another breaking contract release under `AGENTS.md §11.3`.
