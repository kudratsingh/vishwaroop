# WO-012 — Split M1 between the Mac and a GPU, from a measured pilot

**Status:** passed
**Date:** 2026-11-01 · **Author:** claude-code-vishwaroop · **Work order:** WO-012 · **Phase:** M1 · **Protocol version:** `m0-protocol-2`, `evals/M1-exit-tests.json` sha256 `145858ec1ff0f1d259e24756b832f2ce2ffe3497a0a769d799f5008d70388f07`
**Program link:** PROGRAM §5.2 → vishwaroop M1

> Four words with fixed meanings throughout this report: **measured** (ran here, evidence attached), **estimated** (arithmetic from stated assumptions), **mocked/fixture** (fabricated for tests), **not run**.

## 1. Claim and scope
**No M1 exit test needs CUDA or GPU simulation, so none goes to a rented machine.** The M1 predictor, latent model, chunk scorer, planner and simulator branches all ran on the owner's M3 Pro at sizes that make the exit tests practical, peaking at about 1.5 GB of 36 GB (**measured**). The GPU estimate for the M1 exit tests is **0 hours** (**estimated**).

Speed and memory are acceptable. **Prediction quality is not established, and the pilot gives reason for concern:** it learned the joints but not the cube, and ten times the epochs did not help (section 5). That points to the model, not to compute, so a GPU would not obviously help.

This is simulation only, on train data. It closes no exit test and says nothing about a physical arm. The pilot's models are not the WO-004 and WO-005 models.

## 2. Frozen method
The pilot changes no threshold. Train episodes only: `pilot_data.load_train` refuses a dev seed, and 26 of the 260 train episodes, chosen by seed, are the pilot's own holdout. No dev data was loaded. Every workload ran in its own process under `/usr/bin/time -l`, once, on seed 0.

| Workload | Size |
|---|---|
| Predictor | 3-member residual ensemble, 3 hidden layers of 256, 473,934 parameters, 10-step rollout loss, batch 256, 35,192 windows per epoch, 30 epochs and then 300 on MPS |
| Latent | recurrent state-space model on state observations, 423,309 parameters, 32-step sequences, 16 updated and 16 imagined, batch 64, 5 epochs |
| Scorer | GRU chunk encoder with 4 heads, 404,484 parameters, batch 256, 5 epochs, on **stand-in labels** because branch data does not exist yet |
| Planner | CEM over the 30-epoch ensemble, per `docs/ARCHITECTURE.md §5`; the three settings are below |
| Closed loop | real physics with a CEM decision per step, 2 episodes of 185 steps, timing only, success not assessed |
| Branches | real physics, 50 restored mid-episode states and 4 chunks of 10 steps each |
| Visual parts | real rendering at 512 x 512 on a static scene; a ViT-S/14-shaped encoder at 224 x 224 with **mocked** random weights |

## 3. Reproduction
```bash
python -m vishwaroop.models.compute_pilot --manifest artifacts/manifests/m0-dataset-v1.json
python -m vishwaroop.models.compute_pilot --manifest artifacts/manifests/m0-dataset-v1.json \
    --only predictor-mps --predictor-epochs 300
```
Run from the repository root in the robotics environment. Stack: `config/stack-lock.resolved.v2.json`, sha256 `f8db517142b3d720192fa51e23965d6637667d90c492519764503d79f6da19be`, torch 2.15.0. Dataset manifest sha256 `267d77ead98119715350f0fc82987e715f7ce41a4d0337401b7469206711b9c7`.

| Run | Commit, clean | Purpose | Results |
|---|---|---|---|
| `20261101T074208Z_bf56bd56` | `8c1ad30` | the pilot reported here | `artifacts/manifests/m1-mac-pilot-v1.json` |
| `20261101T074759Z_26d9b278` | `0e03efd` | 300 epochs on MPS | `artifacts/manifests/m1-mac-pilot-longer-v1.json` |
| `20261101T073543Z_07fc75f9` | `41084d9` | first full run, same timings within a few percent, before the per-stream error was added | `runs/` only |
| `20261101T073257Z_aa206789` | dirty | one-epoch trial, not evidence | `runs/` only |

## 4. Results
All **measured** on the M3 Pro, in the one run. Peak footprint is macOS's figure for the whole process, including Metal.

| Workload | MPS: median per epoch | CPU: median per epoch | MPS: peak footprint | CPU: peak footprint |
|---|---|---|---|---|
| Predictor | 0.92 s | 2.67 s | 1.46 GB | 0.36 GB |
| Predictor, 300 epochs | 0.92 s (280 s total) | not run | 1.54 GB | not run |
| Latent | 1.56 s | 1.75 s | 1.45 GB | 0.34 GB |
| Scorer | 0.48 s | 1.81 s | 1.43 GB | 0.36 GB |

| CEM decision, 3 members | MPS: median | CPU: median |
|---|---|---|
| 128 samples, horizon 20, 3 iterations | 87.0 ms | 67.0 ms |
| 256 samples, horizon 20, 5 iterations | 158.4 ms | 168.8 ms |
| 256 samples, horizon 40, 5 iterations | 314.3 ms | 344.6 ms |

| Other | Result |
|---|---|
| Closed-loop step, 256 samples, horizon 20 | 158.6 ms planning + 1.4 ms physics on MPS; 178.2 + 1.4 on CPU; peak 0.46 GB and 0.35 GB |
| 50 states with 4 chunks each | 5.3 s total, including the steps to reach each state; peak 0.35 GB |
| Rendering | 468 frames per second at 512 x 512, on a static scene with no stepping between frames |
| ViT-S/14-shaped encoder, random weights | 238 images per second on MPS, 69 on CPU; peak 1.47 GB and 0.44 GB |

MPS is about 3 to 4 times faster than CPU for the predictor and scorer, about the same for the latent model, and no real gain for the planner, where the smallest setting favours CPU. A virtual machine and other applications were running throughout, with load averages of about 3.3 to 4.4, so this is a shared machine and not a clean benchmark.

**Where each M1 exit test runs:**

| Exit test | What it needs | CUDA? | GPU simulation? | Runs on | Time, **estimated** from the above |
|---|---|---|---|---|---|
| ET-M1-1, multi-step error | predictor training; at least 200 dev episodes | no | no | Mac | minutes per training run; about 1 minute to collect 140 more dev episodes |
| ET-M1-2, branch ordering | at least 50 states, 2 chunks each, on physics; predictor inference | no | no | Mac | seconds |
| ET-M1-3, calibration | the ET-M1-1 ensemble and dev episodes | no | no | Mac | minutes |
| ET-M1-4, MPC comparison | 200 episodes per planner, on seed blocks 8 and 9 | no | no | Mac | at most 3.6 h at horizon 20, or 7 h at horizon 40, in one process |
| ET-M1-5, scorer | the ET-M1-2 branch data; scorer training | no | no | Mac | minutes |

ET-M1-4's time assumes at most 200 steps at the measured rate, two model-based planners, and a nominal planner no slower than the learned one. The scripted baseline adds under a minute.

**The split.** Mac-feasible: WO-004 and WO-005 in full. GPU-required: nothing, so there is no GPU work order. The visual latent model moved from WO-004 to a new stub, WO-013, because no exit test needs it. `docs/PHASES.md` asks for a "compact latent predictor", and I read a state-based one as meeting that, since M0's data is state-only; `docs/ARCHITECTURE.md §4` had proposed a visual encoder as a default. WO-013 also starts on the Mac: for the dataset's 53,440 transitions, rendering takes about 2 minutes, encoding about 4 minutes, and the cached features take about 82 MB (**estimated**, with a real encoder's speed **not run**).

## 5. Failure analysis
The pilot's holdout error, in units of each stream's standard deviation, as reduction against the best of the constant, linear and pilot-nominal baselines. This is a sanity check on 26 train episodes with one seed and no intervals. **It is not ET-M1-1 evidence.**

| Stream, epochs | h1 | h2 | h3 | h5 | h8 | h10 |
|---|---|---|---|---|---|---|
| All 13 values, 30 | 5.8% | 9.4% | 12.1% | 15.8% | 19.6% | 21.4% |
| All 13 values, 300 | 5.6% | 9.4% | 12.4% | 16.3% | 19.5% | 20.6% |
| `joint_position`, 30 | 2.1% | 16.2% | 26.6% | 40.9% | 45.1% | 47.5% |
| `joint_position`, 300 | 24.3% | 36.7% | 46.5% | 59.5% | 64.8% | 66.7% |
| `object_position`, 30 | -29.4% | -14.2% | -8.0% | -0.1% | 3.4% | 3.9% |
| `object_position`, 300 | -31.0% | -16.1% | -10.1% | -2.6% | 0.3% | 0.4% |
| `object_grasped`, 30 | 1.8% | 3.8% | 5.7% | 9.7% | 15.0% | 17.9% |
| `object_grasped`, 300 | 0.6% | 1.8% | 3.4% | 6.2% | 9.4% | 10.9% |

The joints improve with training. The cube does not: it is worse than linear extrapolation at short horizons, and level with the baselines by horizon 10. The grasp flag gets worse with more training. So the frozen 20% at every horizon is at risk. I have not tested why. One candidate is that the pilot's nominal model leaves a grasped cube where it was, while a nominal model using forward kinematics could carry it. The training loss also rose between epochs 200 and 300, from -6.74 to -6.25.

**Gaps in the frozen specs that this work found:**
- **Dev episodes.** ET-M1-1 and ET-M1-3 need at least 200 dev episodes, and M0 has 60. WO-004 now includes a frozen top-up plan before any dev metric.
- **Streams in the RMSE.** The frozen file does not say which streams ET-M1-1's RMSE covers. The combined figure can look fine while the cube is not predicted at all. Having now seen these numbers, I must not pick the definition that flatters them, so WO-004 will freeze the stricter reading before any dev result: the 20% applies to `joint_position` and to `object_position` **separately**, `object_grasped` is reported, and `target_position` is excluded because it never moves. The owner can overrule this.
- **Constraint violation.** ET-M1-5 needs AUROC for predicting a constraint violation, and no frozen file defines one. WO-005 must freeze a definition before any scorer result.

## 6. Cost and latency
$0: the owner's Mac, no line in `ledgers/costs.jsonl`. The reported pilot took about 5.5 minutes, and the 300-epoch run about 5 minutes. A CEM decision at 256 samples and horizon 20 takes about 160 ms, over the 50 ms control period, so these planners do **not** run in real time on this Mac. The simulator waits, so ET-M1-4 is unaffected.

## 7. Sealed access
None.

## 8. Exit tests and acceptance
This work order closes no exit test.

| Exit test | Threshold (frozen) | Result | Evidence | Pass? |
|---|---|---|---|---|
| ET-M1-1 to ET-M1-5 | `evals/M1-exit-tests.json` | not run | section 4 says where they run | not run |

Also recorded for the owner: the single copy of the episode bytes (`docs/DATA_AND_SNAPSHOTS.md §7`) and the review rule from M1 on (`AGENTS.md §13.8`). Staying on the Mac also means no replay platforms are mixed, and the Linux re-run the owner asked for applies only if Linux data is ever recorded.

**Not run:** the WO-004 and WO-005 models; any dev data; any NVIDIA comparison, so nothing here says the Mac is as fast as a GPU; a multi-hour run.

## 9. Limits
- **Short run.** Nothing here measured hours of sustained load, so ET-M1-4's hours assume no thermal slowdown. This Mac has already crashed once, so WO-005's planner runs must resume by episode.
- **Models will change.** A larger ensemble, longer horizons or a real nominal model will change these numbers. Memory has about 20 times the room, and time is the first limit, at the planner.
- **Data scale.** Training used the 234 fit episodes. Windows and epoch time should grow in proportion with more data (**estimated**).
- **Stand-ins.** The scorer's labels and the encoder's weights are not real. Rendering was measured without stepping between frames.
- **What would change the 0 hours.** A measured workload that is too slow here, such as training an encoder end to end, which M1 does not ask for. M2a's observation model is outside this estimate. I have not measured it, and it may well need a GPU.
- `make check` still fails in this checkout on the stored log named in `reports/WO-002-m0-dataset-successes-and-failures.md` section 9. Clean clones and CI pass.

## 10. Appendix
Code: `src/vishwaroop/models/compute_pilot.py`, `src/vishwaroop/models/pilot_data.py`; tests: `tests/test_compute_pilot.py`.
