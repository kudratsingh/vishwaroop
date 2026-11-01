<!-- ironclad-policy v1.2.0 -->
# <WO-id or Phase-id> — <title>

**Status:** not started / partial / passed / failed
**Date:** YYYY-MM-DD · **Author:** <agent/session id> · **Work order:** WO-xxx · **Phase:** <id> · **Protocol version:** <evals/… hash>
**Program link:** PROGRAM §<n> → <project> <phase>

> Four words with fixed meanings throughout this report: **measured** (ran here, evidence attached), **estimated** (arithmetic from stated assumptions), **mocked/fixture** (fabricated for tests), **not run**.

## 1. Claim and scope
What was tested, in which environment (simulation / replay / shadow / bench / physical), and what remains untested.

## 2. Frozen method
Baselines; seeds; training/compute budget; sample sizes and the unit of analysis (episode, session, pair); preprocessing; exclusions; success rubric; stopping rules; **pre-declared thresholds** (quote the frozen `evals/` file and its hash).

## 3. Reproduction
Exact commands; stack lock (`config/stack-lock.*.json` hash); dataset / split / checkpoint / calibration hashes; machine and sensor context; run directory ids.

## 4. Results
Counts with denominators; effect sizes with intervals (Wilson for proportions; paired analysis for pairs; session clustering stated); uncertainty and abstention rates; per-shift and per-run breakdowns. Tables, not prose.

## 5. Failure analysis
Representative successes **and** failures with run ids; incomplete episodes; interventions; label disagreements; what the failures have in common.

## 6. Cost and latency
Measured end-to-end cost including failed runs (`ledgers/costs.jsonl` line ids); cost per accepted trajectory / evaluated checkpoint / flight hour; runtime and latency distributions.

## 7. Sealed access
Opening id, authorization line, frozen candidate hashes, timestamps, outputs released, suite retirement/refresh decision — or "none".

## 8. Exit tests and acceptance
| Exit test | Threshold (frozen) | Result | Evidence | Pass? |
|---|---|---|---|---|
| ET-… | … | … | run id / artifact hash | yes / no / not run |

Unresolved prerequisites and anything that is **not run**.

## 9. Limits
What this report does not show. No extrapolation to physical performance from simulation, to full-episode success from chunk scores, or to other embodiments.

## 10. Next bounded work order
The next WO, its prerequisites, and the owner decisions it needs (if any). Rollback: what reverting this work restores.

## 11. Retro note
One to five lines: what slowed this WO, what to change in the process, sizing estimate vs actual.

## Errata (append-only)
Dated entries only; never edit the sections above after merge.
