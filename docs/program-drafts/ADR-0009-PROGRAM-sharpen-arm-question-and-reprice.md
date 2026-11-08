# ADR-0009 — PROGRAM: credit prior SO-101 best-of-N work, sharpen the arm question, and date the workstation prices

**Date:** 2026-11-08 · **Status:** proposed (draft only; nothing is applied to `PROGRAM.md`) · **Work order:** none, program decision · **Program link:** PROGRAM §8.2, §9, §11, §12, §14

**Authority.** The owner approved drafting this ADR on 2026-11-08, item 8 of `approvals-20261108T132556755986Z-2add2fa0` in `ledgers/approvals.jsonl`: "Draft the program-level ADR. Credit prior SO-101 best-of-N work and sharpen our question around abstention, latency, and gains versus fine-tuning at a matched real-trial budget. Date and source any replacement GPU prices." Item 6 of the same record: "Workstation — Defer. Re-price once a measured workload shows what local GPU capability we need." Drafting is all that is approved. The edits below take effect only if the owner accepts this ADR, and then through an `ironclad` release (ADR-0004 decision 3). Program ADRs are numbered in `ironclad`. `ironclad` ADR-0008 exists. This checkout cannot see whether 0009 is still free there, so `ironclad`'s number wins on adoption. The draft lives in `docs/program-drafts/`, not `docs/adr/`, because `ironclad verify` rejects a program ADR in `docs/adr/` that the pinned release does not ship. When accepted, the draft is carried into `ironclad` and arrives here through the release.

**Labels** (`AGENTS.md §7.2`). A number credited to a paper was **measured by that paper**, and this project has not reproduced any of them. A price is a **quote** with the date it was read and its source. Prices are asking or list prices, not completed sales. Arithmetic on quotes is **estimated**. Nothing here was run.

## Context

`PROGRAM.md §8.2` gives the arm build this question: "Does a world-model verifier at test time (best-of-N action chunks) buy the same real-success gain as RL fine-tuning on a low-cost arm, and at what N does it stop?" Its "why open" column says: "Published test-time-scaling work uses learned value heads on lab arms". That is no longer true, and parts of it were already wrong when it was written. The owner's 2026-11-08 review (`reports/REVIEW-2026-11-08-program-architecture-compute.md` §3, which is untracked in this checkout) pointed this out. Each claim below was checked against the primary source on 2026-11-08. The findings, all as **measured by the cited papers**:

- **The same recipe has already run on an SO-101.** *DREAM-Chunk* (arXiv 2606.18589, June 2026) added a latent world model (R2-Dreamer formulation) to SmolVLA on an SO-101. It sampled N = 10 candidate chunks and executed the chunk whose predicted latent best matched the observed state. This is latent matching, not a success or value score. In 20 rollouts per task, success went from 75% to 95% on USB unplug/insert, from 60% to 80% on picking a moving object, and from 35% to 45% on pick-and-insert toy. The paper reports no intervals. The world model was trained on the policy's own 50 to 100 demonstrations per task. Inference was 129 ms at N = 1 and 327 ms at N = 10 on an RTX 5090 workstation. The paper reports no abstention and no comparison with fine-tuning or RL.
- **Latent-world-model verifiers work on other arms too.** *VeriVLA* (arXiv 2610.21985, October 2026) scored K = 10 π0.5 candidates with a JEPA-style verifier: a frozen V-JEPA 2 encoder and an action-conditioned predictor. It ran on an AgileX PiperX dual-arm robot, not an SO-101. Over 50 trials per task, the average completion score rose from 50.8 to 65.5. This is a completion score, not a success rate. Each triggered decision added 326 ms on one RTX 4090, and the verifier took 8.7 GB of GPU memory. Training the verifier used 50 extra labelled rollouts per task. The paper has no abstention (the selector always acts) and no comparison with fine-tuning or RL.
- **Earlier test-time-scaling work did not use "learned value heads on lab arms" either.** *RoboMonkey* (arXiv 2506.17811, June 2025) used a VLM-based verifier on a WidowX-250 S. Its average success was 60%, against 35% for OpenVLA, over 4 tasks with 10 trials each. Sampling and verifying 16 candidates took about 650 ms on an H100. *MG-Select* (arXiv 2510.05681, ICLR 2026) used no verifier. It selected by KL divergence on a Franka Research 3 and raised average in-distribution success from 37.5% to 47.9%. The authors call gains beyond N = 4 "marginal".
- **Headroom is the open problem, and it was measured only in simulation.** The *best-of-N headroom study* (arXiv 2610.37196, October 2026) ran four world action models on two MuJoCo benchmarks, RoboCasa and LIBERO-Plus, with no real robot. Native policy samples gave near-zero held-out gain: +0.003 [−0.024, 0.035] on TurnOnStove. Structured perturbations gave +4.5 to +16 points depending on the model and task. A within-decision Spearman ρ of 0.01 for Cosmos Policy's value head compared with 0.19 for an imagined-future probe. A fail-gated selector raised closed-loop success from 76.9% to 81.6%. An *audit of test-time search* (arXiv 2610.41970, October 2026) studied Cosmos Policy on RoboCasa. There, a learned value selector scored 1.66 points below random, and in 82% of states every candidate had the same outcome.

None of these papers reports calibrated abstention, measured false optimism, or a comparison with fine-tuning at a matched budget of real trials. They measured latency only on RTX 4090, RTX 5090 or H100 cards. The bench has no NVIDIA GPU today (`PROGRAM.md §2`), and the owner deferred the workstation. That leaves three things open, and they are the three the owner named: abstention, latency on the bench's own hardware, and the gain compared with fine-tuning at the same real-trial cost. Abstention and false optimism are also what this project already measures (`docs/EVALUATION_PROTOCOL.md`; the M1 scorer's conformal abstention).

`PROGRAM.md §9` prices the workstation at "Sept 2026 used prices" and a "first-party floor". On 2026-11-08 those figures no longer matched any quote found (see the price table below). The owner has deferred the purchase until a measured workload exists. `§12` rows 1 and 10 repeat the same prices and timing.

## Decision

These are the proposed edits to `PROGRAM.md`. If the owner accepts them, they are applied mechanically. Each "old" string is quoted exactly from `PROGRAM.md` version 1.2. No other line changes.

**Definitions used in the new arm row.** A *real-trial budget* B is the number of real-arm episodes spent beyond the shared demonstration set. That covers the episodes used to collect, train and calibrate the verifier, and the same B spent instead on extra demonstrations or on RL fine-tuning. Evaluation trials are not part of B and are the same for every arm of the comparison. *Abstention* means the verifier may decline to choose. It then falls back to the policy's own chunk, or stops and asks, at a coverage set by calibration on held-out sessions. *Latency* is the added wall-clock time per decision, measured on the hardware beside the arm at trial time.

### Edit A: `§8.2`, arm row

Old:

```
| Arm + world model | Does a world-model verifier at test time (best-of-N action chunks) buy the same real-success gain as RL fine-tuning on a low-cost arm, and at what N does it stop? | N = 1; GRPO-tuned policy | Paired real success; compute per episode | Published test-time-scaling work uses learned value heads on lab arms |
```

New:

```
| Arm + world model | On an SO-101, does a world-model verifier that selects among N action chunks and abstains when its calibrated confidence is low raise paired real success more than spending the same real-trial budget on fine-tuning (more demonstrations, or RL), within the latency the bench's own hardware allows; and at what N does the gain stop? | N = 1 (the policy's own chunk); the same policy fine-tuned with the verifier's real-trial budget spent on extra demonstrations; RL fine-tuning at that budget when the arm project exports one; best-of-N without abstention | Paired real success with intervals; false-optimism rate and abstention coverage; added latency per decision on the bench's hardware; real trials consumed | Best-of-N with a latent world model already ran on an SO-101 (DREAM-Chunk, arXiv 2606.18589, Jun 2026: SmolVLA, N = 10, 20 rollouts per task, on an RTX 5090), and JEPA-latent verifiers on other arms (VeriVLA, arXiv 2610.21985, Oct 2026). None of the cited work reports calibrated abstention, false optimism, or a fine-tuning comparison at a matched real-trial budget, and latency was measured only on RTX 4090/5090 or H100 cards. Native policy samples left almost no selectable headroom in simulation (arXiv 2610.37196, Oct 2026) |
```

### Edit B: `§9`, workstation prices and timing

B1. The introductory sentence. Old:

```
Source of detail: the owner's "Lab Purchase Plan v1" (Oct 30, 2026; prices are US street prices seen Sept–Oct 2026 and move weekly). **This section records the plan; it authorizes nothing. Every purchase is an owner action.**
```

New:

```
Source of detail: the owner's "Lab Purchase Plan v1" (Oct 30, 2026; prices are US street prices seen Sept–Oct 2026 and move weekly). The workstation's GPU and RAM prices were re-checked on 2026-11-08 and each carries its date and source (ADR-0009); every other price is from Sept–Oct 2026 and was not re-checked. Quotes are asking or list prices, not completed sales. **This section records the plan; it authorizes nothing. Every purchase is an owner action.**
```

B2. The tier-1 workstation row. Old:

```
| 1 | Now | **Linux workstation**: Ryzen 9 class, 64 GB DDR5, 4 TB NVMe, 1,200 W PSU sized for a second card, Ubuntu 24.04. GPU paths: lean = used RTX 4090 24 GB (~$2.6k, Sept 2026 used prices); premium = RTX 5090 32 GB only at its ~$4.3k first-party floor; 48 GB RTX PRO 5000 only on a reseller quote ≤ ~$5.5k | $5.3–5.9k lean; $7.2–8.3k premium | The one purchase with no cloud substitute: Isaac Lab needs a local RTX card; real-robot RL needs the GPU next to the arm; cameras/servos on USB. Headless, reached from the Macs over Tailscale |
```

New:

```
| 1 | Deferred (owner, 2026-11-08): re-price once a measured workload shows what local GPU capability is needed | **Linux workstation**: Ryzen 9 class, 64 GB DDR5, 4 TB NVMe, 1,200 W PSU sized for a second card, Ubuntu 24.04. GPU path chosen from the measured workload. Quotes: used RTX 4090 24 GB, median asking $3,397 over 114 listings (as of 2026-11-08, dealhunter.io/prices/rtx-4090); RTX 5090 32 GB, MSRP $1,999, lowest new $7,799.98 and lowest used $6,299 (as of 2026-11-07, videocardprices.com/card/nvidia-rtx-5090, read 2026-11-08); RTX PRO 5000 48 GB, lowest new $7,290 (eBay OEM listing) and $7,985 (Amazon) (as of 2026-11-08, vramglass.com/gpu/rtx-pro-5000-blackwell-48g); DDR5 64 GB kit from $929.99, median $1,262.49 over 84 US kits (as of 2026-11-08, pgrid.app/us/advice/compare-64gb-ddr5-ram) | Not re-estimated; the Sept–Oct 2026 totals ($5.3–5.9k lean, $7.2–8.3k premium) are stale | The one purchase with no cloud substitute: Isaac Lab needs a local RTX card; real-robot RL needs the GPU next to the arm; cameras/servos on USB. Headless, reached from the Macs over Tailscale |
```

B3. The tier-2 second-GPU row's price cell. Old:

```
| $2.5–5k | 7B-class VLA fine-tunes, video-tier world model, 120B-class local inference |
```

New:

```
| Not re-estimated; priced with the first card (the Sept–Oct 2026 estimate of $2.5–5k is stale) | 7B-class VLA fine-tunes, video-tier world model, 120B-class local inference |
```

B4. The rent-versus-buy rule. Old:

```
**Rent vs buy rule (proposed default):** rent H100-class for anything bigger than one card (pretraining, large sweeps); own one workstation for the robot in the room. The lean box equals ~7,000–15,000 rented 4090-hours, so it is justified by real-robot RL and Isaac Lab iteration, not rent savings.
```

New:

```
**Rent vs buy rule (proposed default):** rent H100-class for anything bigger than one card (pretraining, large sweeps); own one workstation for the robot in the room, bought once a measured workload shows which local GPU capability it needs (owner, 2026-11-08). The box is justified by real-robot RL and Isaac Lab iteration, not rent savings; the ~7,000–15,000 rented-4090-hour equivalence was computed from Sept–Oct 2026 prices and is recomputed when the workstation is re-priced.
```

### Edit C: `§12`, the rows that repeat the stale prices and timing

Old:

```
| 1 | Workstation GPU path: used 4090 now, 5090 at the $4,299 floor, or PRO 5000 on a ≤ $5.5k quote | Lean (used 4090) | Nothing immediately; GPU-tier work rents meanwhile |
```

New:

```
| 1 | Workstation GPU path (used 4090, 5090 or PRO 5000), chosen once a measured workload shows the local GPU capability needed; dated quotes in §9 | Deferred (owner, 2026-11-08); GPU work rents meanwhile | Nothing immediately |
```

Old:

```
| 10 | Hardware purchase timing (Black Friday window for printer; workstation now) | As in §9 | — |
```

New:

```
| 10 | Hardware purchase timing (Black Friday window for printer; workstation deferred until a measured workload, owner 2026-11-08) | As in §9 | — |
```

### Edit D: `§11` and `§14`

Append to `§11` after the last row:

```
| 2026-11-08 | Arm research question sharpened to calibrated abstention, latency on the bench's hardware, and gain versus fine-tuning at a matched real-trial budget; prior SO-101 best-of-N work credited (DREAM-Chunk) (ADR-0009) | Confirmed |
| 2026-11-08 | Workstation purchase deferred; re-price once a measured workload shows what local GPU capability is needed. §9 prices re-checked and dated (ADR-0009) | Confirmed |
```

Append to `§14`, with the version number and date the `ironclad` release assigns:

```
| 1.3 | <release date> | §8.2 arm row sharpened and prior work credited; §9 workstation prices re-checked and dated, workstation deferred; §12 rows 1 and 10 follow; §11 records both decisions (ADR-0009). No change to budgets or authorization. |
```

### Prices as quoted (read 2026-11-08)

| Item | Quote as stated | As of | Source |
|---|---|---|---|
| Used RTX 4090 24 GB | median asking $3,397, 114 listings; eBay median $3,400; lowest price band $2,078–$2,393 (6 listings); "asking prices — not sold prices"; completed sales not observed | 2026-11-08 ("Updated November 8, 2026") | https://dealhunter.io/prices/rtx-4090 |
| RTX 5090 32 GB | MSRP $1,999.00; lowest new $7,799.98 (Amazon, ASUS TUF OC); lowest used $6,299.00 (eBay) | 2026-11-07 ("price as of November 7, 2026") | https://videocardprices.com/card/nvidia-rtx-5090/ |
| RTX 5090 32 GB (secondary report) | best US price $6,919 per Tom's Hardware's tracker, as reported by Tech Insider; not seen on the Tom's Hardware page itself | 2026-11-03 (article 2026-11-05) | https://tech-insider.org/gpu-price-tracking-2026-rtx-5090-6919-tomshardware-lowest-prices/ |
| RTX 5090 Founders Edition (secondary report) | "$1,999 list price but showed as out of stock"; same article reports one Gigabyte Aorus listing at $3,340 at Walmart, a single listing not confirmed here | 2026-11-02 (article 2026-11-03) | https://tech-insider.org/nvidia-rtx-50-prices-rise-november-2026-rtx-5090-3340/ |
| RTX PRO 5000 Blackwell 48 GB | new: $7,290 (eBay OEM), $7,300 (eBay Dell OEM), $7,985 (Amazon, PNY); eBay median $7,395, range $7,000–$9,202 | 2026-11-08 ("Price updated 11/08/2026, 07:55") | https://vramglass.com/gpu/rtx-pro-5000-blackwell-48g |
| DDR5 64 GB desktop kit | lowest $929.99 (Corsair Vengeance RGB 2×32 GB 6000 CL40, Newegg); median $1,262.49; 84 kits in stock | 2026-11-08 ("Updated 8 Nov 2026") | https://www.pgrid.app/us/advice/compare-64gb-ddr5-ram |

The NVIDIA store page could not be read (the fetch timed out), so the Founders Edition's stock status comes only from the secondary report. The 4 TB NVMe, the rest of the box, the printer, the bench kit and the drone parts were not re-priced. The edits mark the box totals and the rent equivalence as stale and do not replace them with new estimates. A total built from one day's asking prices would read as a plan, and the owner has deferred the purchase.

### Prior work cited (checked against the primary source, 2026-11-08)

| Work | Authors | Id, date | What it measured (by its own report) |
|---|---|---|---|
| DREAM-Chunk: Reactive Action Chunking with Latent World Model | W. Chen, K. Zhang, C. Lin, Z. Zhang, Y. She, Y. Liu, R. A. Yeh, S. Mou, Y. Gu | arXiv 2606.18589, 2026-06-17, https://arxiv.org/abs/2606.18589 | SO-101 + SmolVLA, N = 10, 20 rollouts per task: 75→95%, 60→80%, 35→45%; 129 ms (N = 1) vs 327 ms (N = 10) on an RTX 5090; Franka + π0.5 can insertion 10→65% at N = 5. Selection by latent matching; no abstention, no fine-tuning comparison, no intervals |
| VeriVLA: Adaptive Test-Time Verification for Flow-Based VLAs with Latent World Models | X. Sun, Y. Lu, Y. Liu, X. Fan, X. Chen, Z. Liu, H. Zhao | arXiv 2610.21985, 2026-10-15, https://arxiv.org/abs/2610.21985 | AgileX PiperX dual-arm + π0.5, K = 10, 50 trials per task: completion score 50.8→65.5; +326 ms per triggered decision on one RTX 4090; no abstention; no fine-tuning or RL comparison |
| How Much Can Best-of-N Help a World Action Model? Measuring Selectable Headroom and Realizing It in Closed Loop | H. Gao, Y. Cao, Y. Liu, H. Que, M. Liu, G. Guo, Z. Zou, B. Chen, X. Wang | arXiv 2610.37196, 2026-10-27, https://arxiv.org/abs/2610.37196 | Simulation only (RoboCasa, LIBERO-Plus), four world action models: native samples near-zero held-out gain; structured perturbations +4.5 to +16 points; value head ρ 0.01 vs imagined-future probe ρ 0.19; fail-gated selector 76.9→81.6% |
| When Does Test-Time Search Help World Action Models? An Empirical Audit of Candidate Selection and Simulator Integrity | J. Liu, D. Sun, Z. Kong, Z. Fan, P. Dong, F. Yang, W. Zhang, G. Yuan, X. Lin, Y. Wang, D. Huang | arXiv 2610.41970, 2026-10-30 (v2 2026-11-03), https://arxiv.org/abs/2610.41970 | Cosmos Policy on RoboCasa: learned value selector 1.66 points below random; hindsight oracle +1.40 with an interval spanning zero; all candidates tie in 82% of states |
| RoboMonkey: Scaling Test-Time Sampling and Verification for Vision-Language-Action Models | J. Kwok, C. Agia, R. Sinha, M. Foutter, S. Li, I. Stoica, A. Mirhoseini, M. Pavone | arXiv 2506.17811, 2025-06-21, https://arxiv.org/abs/2506.17811 | WidowX-250 S + OpenVLA, VLM verifier, 16 candidates: 60% vs 35% over 4 tasks × 10 trials; about 650 ms on an H100 |
| Verifier-free Test-Time Sampling for Vision-Language-Action Models (MG-Select) | S. Jang, D. Kim, C. Kim, Y. Kim, J. Shin | arXiv 2510.05681, 2025-10-07 (ICLR 2026), https://arxiv.org/abs/2510.05681 | Franka Research 3 + π0-FAST-DROID: in-distribution 37.5→47.9%; gains beyond N = 4 "marginal" (RoboCasa sweep) |

## Alternatives considered

| Option | Why not (or why not yet) |
|---|---|
| Leave `§8.2` as it is | Its "why open" claim is contradicted by DREAM-Chunk (an SO-101) and RoboMonkey (a VLM verifier, not a value head). `§8.4` requires the question to come from what the literature left untested |
| Keep the old question and only fix the "why open" cell | "At what N does it stop" on an SO-101 is now partly answered by DREAM-Chunk's N = 10 and MG-Select's N = 4 plateau. The parts nobody has measured are abstention, the matched-budget comparison, and latency on modest hardware |
| Make the proposal distribution (native samples vs structured perturbations) the headline | It is a design variable the M5-early protocol has to fix, especially because standard ACT inference is deterministic (owner, item 3). The headroom study already measured it in simulation. Recording N and the proposal source in the protocol is enough |
| Replace the arm question with the digital-twin evaluator question | The twin (owner item 1) answers a different question: ranking policies without the robot. The arm row is about selection at test time, and both can stand |
| Write new box totals and a new rent-versus-buy equivalence from today's quotes | The owner deferred the purchase until a measured workload exists. Totals built from one day's asking prices would be read as a plan and would go stale before they are used |
| Delete prices from `§9` | Loses the dated record. The owner asked for replacement prices to be dated and sourced, not removed |

## Consequences

- The M5-early design (owner item 3) and its frozen protocol take their hypothesis, baselines and metrics from the new row. Each comparison needs a stated real-trial budget B and abstention calibrated on held-out sessions. Latency is measured on the hardware beside the arm. Today that is a Mac, which is the M1 scorer's platform.
- The matched-budget comparison needs a fine-tuned policy at budget B. The extra-demonstrations baseline is cheap and always available. The RL baseline depends on the arm project exporting one, so the row names it "when the arm project exports one" rather than requiring it.
- DREAM-Chunk becomes a published method to compare against or to cite as the closest prior result. It should be added to `docs/SOURCES.md` in a later change; this ADR does not edit that file.
- `§9` no longer says "Now" for the workstation, and `§12` no longer gives a default GPU path. Agents must not plan GPU-local work on the assumption that a workstation is coming. GPU work rents under approvals, as it does today.
- `§8.3` item 1 still describes the verifier as "execute the best". It does not contradict the new row, because executing the policy's own chunk on abstention is an allowed outcome, so it is left alone. The same goes for `§2`'s note that the SO-101's arrival is not confirmed; the kit arrived on 2026-11-08. Both are noticed, not proposed.
- Applying the edits takes an `ironclad` release, and each repository then moves its pin (ADR-0004). This repository changes nothing until then.

## Reversibility

The change is text only. It touches no rules, budgets, authorization, data or runs. Undoing it takes another program ADR that restores the quoted old strings, released the same way. The cost of reversing is one release and one pin bump per repository. The prices are dated so that they can be superseded without argument. The next re-pricing, when a measured workload exists, replaces the quotes in `§9` with new dated quotes.
