<!-- ironclad-policy v1.2.0 -->
# ADR-0004 — Shared material becomes a versioned dependency: `ironclad`

**Date:** 2026-10-31 · **Status:** accepted (owner decision; implementation in `ironclad` WO-001…WO-005, adoption in each project's own work order) · **Work order:** WO-001 in `ironclad` · **Program link:** PROGRAM §5.3, §6, §10

## Context
ADR-0001 chose two independent projects joined by one shared contract, and ADR-0002 added a shared `AGENTS.md` core and append-only tooling. The starter kits delivered those shared parts as byte-identical copies in each repository, kept in sync by hand with hash locks. On the first day of work the rename (ADR-0003) and five tooling fixes each had to be authored in `banshee` and copied into `vishwaroop` with hash confirmation, the two repositories collided on work-order and ADR numbers, and each merge waited on the other. The owner's requirement is separate, agile development: each project moves at its own speed, and anything shared is a dependency.

## Decision
1. **A new repository and Python package, `ironclad`,** holds every shared artifact in one canonical location: `contracts/v1`, the `core` record helpers, the six CPU-tier tools as console scripts, the shared tests as a pytest plugin, `AGENTS_CORE.md`, `PROGRAM.md`, and the program-level ADRs. Design: `docs/DESIGN.md`.
2. **Consumers pin a version** (`ironclad-kit @ git+…@vX.Y.Z`, or a full commit) and upgrade in work orders of their own. A consumer may lag indefinitely and must stay green. The hash locks (`config/contract-lock.json`, `config/program-lock.json`) are replaced by `ironclad verify`.
3. **Policy is authored in `ironclad`.** The `AGENTS.md` core and `PROGRAM.md` change through program-level ADRs written here and reach projects through `ironclad sync-policy`. Project `§13` addenda and project ADRs stay in the projects. Program ADRs number in `ironclad` (this is ADR-0004 here; ADR-0001–0003 are copied in as history). Project ADRs number locally and never collide with program ADRs again.
4. **`ironclad` is a dependency, not a third project.** No runtime, no shared state, no knowledge of either consumer, no imports from them, tests pass with only itself installed. This honours the 2026-10-30 review warning against a third project or shared runtime: a pinned dev-time and data-format dependency is what makes the two projects *more* independent, not less.
5. **Numbering.** `ironclad` has its own work-order sequence (WO-001…) and its own stage ladder (I0–I2).
6. **Ownership.** `ironclad` is built and maintained by its own agent session in its own checkout. `banshee` remains the source for the initial copy (its `main` at the commit recorded in `SOURCE_MANIFEST.json`); after `v1.0.0` it is a consumer like `vishwaroop`.

## Consequences
- One PR per shared change, in one place; consumers adopt when ready. No more hand-copying or hash relays.
- A consumer's `make check` calls console scripts; its Makefile and CI shrink to wrappers.
- Policy text changes become releases, with notes that say what each consumer must do; the owner refreshes the Claude Project copy of `PROGRAM.md` from the release.
- Migration cost: one work order here (split into WO-001…WO-005) and one work order per project. During migration, consumers keep their vendored copies and stay green.

## Alternatives considered
| Alternative | Why not |
|---|---|
| Keep byte-identical copies, add a tooling hash lock | detects drift but still requires hand-copying every change into every consumer |
| Git submodule or subtree of a shared repo | ties consumers to a commit of a source tree rather than a tested release; subtree merges re-create the copy problem |
| Let `banshee` own the shared files permanently | makes the drone agent the gatekeeper of the world-model project's tooling; violates the independence requirement |
| A monorepo | one CI, one history, one merge queue for two projects that should not wait on each other |

## Authorization
Owner decision recorded 2026-10-31 (`ledgers/approvals.jsonl` in this repository once the first session records it). Creating the private remote `kudratsingh/ironclad` is a separate `§2.2` approval (WO-004). No purchase, hardware or paid action is implied.

## Amendment 2026-10-31
ADR-0007 corrected the pin form in decision 2, after the distribution was named `ironclad-kit` because `ironclad` on PyPI is an unrelated project. Wording only.
