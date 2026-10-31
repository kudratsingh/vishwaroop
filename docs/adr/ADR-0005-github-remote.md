# ADR-0005 — Private GitHub remote for this repository

**Date:** 2026-10-31 · **Status:** accepted · **Work order:** WO-009 · **Program link:** PROGRAM §12 decision 7

## Context
The owner asked on 2026-10-31 for the `vishwaroop` GitHub repository to be created. `AGENTS.md §2.2` allows remote operations only once a remote is designated in `config/repo.json`, and only under an account the owner has named, never public. The owner named the repository but not the account. `gh` is logged in only to `kudratsingh`, which is also the owner's git identity and the home of the sibling repository `banshee`.

## Decision
- Remote: `https://github.com/kudratsingh/vishwaroop.git`, private, default branch `main`.
- `main` is pushed. Protection is requested for it, per `docs/WORKFLOW.md §8`: pull requests required, both CPU-tier checks required, force-push and deletion disallowed, administrators included.
- The rename branch `wo/WO-007-program-rename` stays local, because the owner's instruction for it says to commit locally. Until it merges, `main` here still carries the kit's old package name.
- ADR-0003 and ADR-0004 are taken on that branch, so this ADR takes 0005.

## Alternatives considered
| Option | Why not |
|---|---|
| Another account or an organization | none was named, and `gh` is logged in to no other account |
| Public repository | forbidden without a separate owner decision (`AGENTS.md §2.3`); no license is chosen (PROGRAM §12 decision 8) |
| Push the rename branch too | the owner's instruction for that branch says to commit locally |

## Consequences
Pushes and CI become available for this repository. CI on a private repository uses the account's GitHub Actions allowance. With protection on, changes reach `main` through pull requests only.

## Reversibility
The owner can set `designated` back to `false` and delete or move the repository on GitHub. Deleting it is a §2.3 action for the owner.
