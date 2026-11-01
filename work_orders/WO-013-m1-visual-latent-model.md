# WO-013 | M1 visual latent model, on the Mac first
**Phase:** M1
**Exit tests advanced:** none (no M1 exit test depends on it)
**Size:** M (milestone-level stub; expand when next)
**Prerequisites:** WO-004 accepted; rendered frames for the dataset, which M0 does not have because its data is state-only.
**Authorization:** AGENTS §2.1 only on the owner's Mac. Paid GPU time needs §2.3 approval and a new estimate from a measured need.
**Files:** `src/vishwaroop/models/`, `tests/`, `reports/WO-013-m1-visual-latent-model.md`, ignored `data/` and `runs/`.

## Objective
Add the visual form of the compact latent model from `docs/ARCHITECTURE.md §4`: a frozen encoder, features cached once, and no image decoder. WO-012 split it from WO-004 because no exit test needs it. WO-012 measured its parts on the Mac with a random-weight encoder, so this work starts there. It goes to a rented GPU only if a measured workload, such as training the encoder end to end, turns out too slow.

## Scope
Render the dataset's frames by replay on the same stack; a frozen encoder with a named license and hash; cached features; the latent model on them; the same evaluation as WO-004.

## Out of scope
Exit-test claims, M2a's observation model, image generation.

## Verification
Written when expanded.

## Stop conditions
A rendered replay straying past the frozen tolerance; an encoder without a clear license; paid compute without approval.

## Report
`reports/WO-013-m1-visual-latent-model.md`
