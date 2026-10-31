# PROGRAM.md — Physical AI Program: trajectory, projects, and plan

**Version 1.0 — 2026-10-31. Owner: Kudrat Singh.**
Canonical copies: byte-identical at the root of the `omni-drone` and `world-model` repositories (sha256 pinned in each repo's `config/program-lock.json`) and in the owner's "Omni Drone / World Model / Planner" Claude Project.

This is the single document that says **where the whole program is going and why**. It covers every project the owner is building, not only the two repositories that carry it. Enforceable rules for agents live in `AGENTS.md`; the interface between projects lives in `contracts/v1/`; this document explains the destination, the order of work, and the reasoning behind both.

---

## 0. How to use this document

**Agents**
1. Read this document once at the start of every session, before the repository's `AGENTS.md` and `START_HERE.md`.
2. Every work order names the program stage and project phase it serves (for example `PROGRAM §6 → world-model M1`). Work that serves no listed stage is out of scope until the owner adds it here.
3. Nothing in this document authorizes spending, hardware motion, flight, or remote operations. Authorization lives in `AGENTS.md §2` and in dated owner approvals.
4. If this document and a repository document disagree, stop and report the conflict; do not pick the convenient reading.
5. Propose changes to this document as an ADR plus a pull request in the repository you work in, titled `PROGRAM: <change>`. The owner approves program changes; the same change is then applied to both repositories so the copies stay identical.

**Owner**
- Edit the Project copy, then paste the result into both repositories (or ask an agent to), bump the version line, and add a changelog entry at the bottom.
- Keep the decision log (§11) and open decisions (§12) current; they are what agents read when they must choose.

**Status words used throughout:** *confirmed* = owner stated it; *proposed default* = Claude or an agent suggested it and the owner has not objected, so it is the working assumption; *unknown* = nobody has established it; *future option* = a possibility the owner likes but has not decided.

---

## 1. Destination

The owner's long-term target (confirmed, Sept 25, 2026, reaffirmed Oct 30, 2026):

- Move into **physical AI** — robots that learn — as soon as possible, and become a **highly skilled ML engineer** in that field.
- Long-term role: **lead engineer of a physical-AI product**, potentially **technical founder/CEO**.
- Do **real frontier AI robotics research**: projects that answer **novel research questions at a one-person scale**, written up and published, leading into research with labs and companies.
- Build dexterous-hand and humanoid-class systems eventually — **not to have the best hand or humanoid**, but because they interest him and because building them is the experience that companies doing them at the next level hire for.
- Application areas he names: **autonomous and aerial systems, defense, medicine, space**. The program is not medical-first; medicine is one of several areas he finds interesting.
- Use graduate study and research to decide whether a PhD is the next step.

What "done" looks like in two to three years: a fleet of robots he built (arm, drone, hand, small legged platform), a learned world-model and evaluation stack that demonstrably improves how their policies are trained, selected and deployed, a run of workshop papers and preprints with real-robot evidence, and a hardware/software portfolio that physical-AI companies and labs recognize as the work of someone who has already done the job.

---

## 2. Where the program stands (2026-10-31)

**Background the program builds on (confirmed)**
- Software engineer, 3+ years. Current professional work: building **LLM post-training data pipelines (SFT/RLHF/RLVR)** for frontier labs across coding, agentic tool-use and reasoning. This is the program's unfair advantage: verification, data curation and evaluation discipline at frontier scale.
- Completed Stanford CS229/CS230/CS236/CS330, Caltech CS156, MIT 6.S191 and the deeplearning.ai specializations; post-bacc CS coursework at 4.0 GPA. Strong ML theory (VAEs, flows, autoregressive models, policy gradients, transformer internals).
- Physical AI Foundations self-study track (`physical-ai-foundations` repo: SE(3) transforms, MuJoCo PD control, ROS 2 pub/sub, FK/IK/Jacobians, first RL policies) completed through Week 8 as of Oct 11, 2026.
- Graduate school: admitted to USC M.S. Computer Science (Artificial Intelligence) for Spring 2027 (listed on his resume); also enrolled in Georgia Tech OMSCS (Machine Learning specialization) for Spring 2027.
- Machines: MacBook Pro (M3 Pro, 36 GB) and an iMac (16 GB) that runs his coding agents. **No Linux/NVIDIA machine yet** — decision to buy one is confirmed (Oct 30, 2026); purchase not yet made.

**Hardware owned or ordered (confirmed)**
- SO-101 leader + follower arm pair plus webcams: **ordered Oct 26, 2026**; arrival not confirmed as of this version.
- Nothing else robotics-grade is owned. No drone, no 3D printer, no workstation yet.

**Projects in flight** — see §4.

**Compute today** — cloud GPU rentals per project with owner-approved caps (the coding-agent project has a $900 cap; the arm project rents one GPU). The two new repositories start with **$0 approved** (see `AGENTS.md §2`).

---

## 3. Capability stages

The owner's Physical AI Leadership Roadmap (Sept 2026) defines competency stages. This table maps each stage to the project that satisfies it, so every project can say which rung it is climbing.

| Stage | Capability | Satisfied by | Status |
|---|---|---|---|
| 0 | Robotics foundations: frames, kinematics, control, MuJoCo, ROS 2 | `physical-ai-foundations` | Done through Week 8 (Oct 11, 2026) |
| 1 | Imitation and RL robot learning in simulation (ManiSkill / Isaac Lab, robomimic) | `vla-rl-so101` (arm project) | In progress (started Oct 26, 2026) |
| 2 | Model-level policies: VLAs, ACT, Diffusion Policy; fine-tuning and RL post-training | `vla-rl-so101` | In progress |
| 3 | Agentic embodied system: planner + skills + success detector + recovery (transfer of Incident Commander patterns) | `omni-drone` mission executive (D6+); drone is the home of the "brain" work now that the Microduck is dropped | Planned |
| 4 | Real hardware: deployment, calibration, sim-to-real, data collection | `vla-rl-so101` on the SO-101; `omni-drone` D2–D6; `rocket-twin` physical rocket | Arm hardware ordered; others planned |
| 5 | Research / train-time loop: world models, evaluators, synthetic data, verifiers, real-robot RL | `world-model` (all milestones); arm follow-on HIL-SERL | Planned (starts now) |
| 6 | Product ownership: a platform with missions, reliability, operations, cost | `omni-drone` as a product-like autonomy platform | Planned |
| 7 | Lead / founder readiness: fleet, papers, people, budget judgment | The program as a whole | Ongoing |

Rule kept from the roadmap: **manipulation first; simulation foundations before hardware purchases.** The SO-101 order is the one approved exception because the arm project is sim-first and ships a sim-only milestone before the arm is needed.

---

## 4. Portfolio: projects in flight

| Project | What it is | Status (as stated by owner) | Role in the program |
|---|---|---|---|
| `vla-rl-so101` ("the arm project") | Few-shot SFT of a pre-trained VLA, then GRPO RL post-training in ManiSkill3 on one rented GPU, then deployment to a real SO-101 arm for tabletop pick-and-place from camera + text | Started Oct 26, 2026. Sim-first; fast iteration, no independent review pass except on RL-loop work orders. Follow-on confirmed: HIL-SERL-style real-robot RL with human interventions | Stages 1, 2, 4. **First data environment, baseline and evaluation subject for `world-model`.** Read-only to the new projects |
| `coding-agent-from-scratch` | A coding agent whose language model is pretrained from scratch (web text then Python), SFT on language + code, RL on code; openly licensed data only | S rehearsal done; main model is L (477M); XL deferred until L's scorecard exists; $900 cloud cap; repo private until rehearsal passes | ML engineering depth; the owner's "run my own model at home" interest (see §9 rent-vs-buy) |
| `rocket-twin` | Digital twin of a thrust-vector-controlled model rocket with a 3D frontend (design, inspect parts, watch simulations), PID and RL controllers, then the real printed rocket within NAR limits; also a full-scale rocket in the frontend model | Started Oct 26, 2026. Same fast working style as the arm project | Mechanical/electrical/physics learning; flight-control math shared with the drone. **Not** a world-model warm-up (decided Oct 30, 2026) |
| `soundings` | Harbor-floor "air traffic control": detect unverified underwater vehicles, investigate, hand off to a human or act within pre-authorized limits (InnovateLA dual-use hackathon, Oct 16–18, 2026) | Not submitted to the hackathon; repo complete and frozen on main; owner says he is still building it out | Stage-3 pattern (planner, ladder, investigation logic) |
| `incident-commander` + `incident-platform` | Autonomous AI SRE agent (nine-state checkpointed state machine, deterministic guards, MCP tools, chaos eval harness) and its FastAPI platform | Flagship portfolio pieces; planned direction: a controlled research environment for inference-time agent improvement, later closing the loop with SFT/RL on logged trajectories | Source of the planner/success-detector/recovery pattern reused in the drone mission executive and the "reward vs independent assessment" discipline. Not the owner's long-term interest |
| `movielens-recommender`, `arxiv-research-agent`, mock-interview app | Smaller ML/agent portfolio projects | Various | Portfolio only |
| `physical-ai-foundations` | Stage-0 learning repo | Through Week 8 | Foundations |

Ground rules for the new repositories with respect to these: **never modify, import runtime code from, launch, or interfere with any of them.** The arm project becomes a *producer* only through completed, immutable, owner-provided exports (see §6 and `contracts/v1/README.md`).

---

## 5. The two new projects

### 5.1 Omni Drone — a real, general-purpose aerial autonomy platform
A flying robot that works in the real world, built **conventionally first**: PX4 flight control, ROS 2, visual-inertial odometry (camera + IMU position tracking without GPS), mapping, navigation, and a mission executive. Capability grows through a **ladder of narrow missions, each with an exit test** (D0 operating envelope → D1 simulation → D2 props-off sensing → D3 optional outdoor checkout → D4 indoor position hold → D5 GPS-denied route → D6 fixed-target inspection → D7+ one mission at a time). Learned components enter only through evidence gates. "Omni" means **broad mission capability**, not a mechanically omnidirectional airframe (that would be an explicit owner decision).

### 5.2 World Model & Planner — learning, planning, evaluation and synthetic-data infrastructure for robot policies
A standalone platform with three products, each with its own evidence: (1) a compact predictive model, latent planner and **action-chunk scorer**; (2) an action-conditioned, policy-compatible **closed-loop evaluator** for VLA checkpoints; (3) a **synthetic-data engine** whose generated demonstrations are filtered by physics replay and used on the SFT route only. Its first environment is the **arm project's ManiSkill3 setup**, and the arm's VLA is its first baseline and evaluation subject. M4 adapts the dynamics part to drone flight logs, offline and shadow-only, and branches from M0/M1 the moment usable logs exist — it never waits for M2/M3.

### 5.3 Why two projects (confirmed Oct 30, 2026)
- The **sim-to-real gap is large**, especially for a drone (wind, vibration, motion blur, estimator drift). Keeping the drone conventional means crashes and sim-to-real never stall ML progress.
- The owner wants the world model to **serve a purpose beyond the drone**: a learned simulator you can generate training data from, evaluate policies in, and plan in — the direct continuation of his post-training work into physical AI.
- Together they are one story: "I build the robot and the training/evaluation infrastructure for its brain."

### 5.4 Why the arm is the world model's first target (confirmed)
In pure simulation the physics engine already *is* the perfect world model, so an evaluator or data engine trained only in sim has nothing to be better than. The two purposes beyond planning only exist when there is a reality the simulator does not capture and real episodes are expensive. The SO-101 gives that reality at the lowest cost of any platform the owner could own. Its hobby-grade noise is reality to be modelled; the mitigation is protocol (paired runs, episode counts), not a different platform. M0 and M1 run entirely in ManiSkill3 before hardware matters.

### 5.5 What is deliberately not in the program
- **No Microduck** project (dropped Oct 30, 2026; previously planned for December).
- **No rocket warm-up** for the world model (dropped Oct 30, 2026).
- **No third research project, shared runtime, shared database, or microservices** between the two repositories. The only shared technical boundary is the versioned trajectory contract (§6).

---

## 6. Program dependency map

```
 physical-ai-foundations (done) ──┐
                                   ▼
 vla-rl-so101 (arm, in flight) ── sim tasks, action space, camera setup ──► world-model M0 (sim data today)
          │                                                                        │
          │ checkpoints + sim results (immutable exports) ────────────────────────► M1 → M2a (sim) → M2b (real arm)
          │ teleop + autonomous rollouts (immutable exports) ─────────────────────► M3 (synthetic data, SFT route)
          │                                                                        │
          └─ real SO-101 (ordered) ◄─── evaluator-selected checkpoints ◄───────────┘
                                                                                   │
 omni-drone D0 → D1 (SITL) → D2 → [D3 opt] → D4 → D5 → D6 → D7+                    │
          │                                                                        │
          └─ flight logs (immutable exports) ─────────────────────────────────────► M4 (drone dynamics, offline/shadow)
                                                                                   │
 LEAP hand on a stand (after arm ships) ── new embodiment ────────────────────────► evaluator / pipeline reuse
 Humanoid locomotion in Isaac Lab (any time, free) ── fall monitor ──────────────► small humanoid (later)
```

| Dependency | Direction | Nature | Must never become |
|---|---|---|---|
| Arm → World Model | arm produces; WM imports read-only | Completed, immutable exports: episodes, checkpoints with ids, frozen task suite, action convention, camera setup | Edits to the arm repo, imports of its training code, hooks into its training loop |
| Drone → World Model | drone produces flight logs; WM imports | Contract-v1 episodes from SITL, later real flights | A shared runtime or live command path |
| World Model → Drone | WM proposes; drone decides | Exported model manifests (same contract boundary), shadow-mode predictions, evaluation reports | Command authority; the drone can always reject or run without it |
| Both → Contract | both consume the same release | Byte-identical vendored `contracts/v1`, hash-pinned | Per-repo forks of semantics |

Ordering rules that follow:
1. World Model M0/M1 need only sim data the agent can generate today; they do not wait for the arm project.
2. M2 needs arm checkpoints; M2b needs real-arm episodes; M3 needs teleop data. Each waits for its input, not for the previous milestone of the other project.
3. M4 starts when SITL logs exist (after drone D1); it does not wait for M2/M3.
4. The one decision to make early in the arm project: **lock the task configs and action space** so the evaluator evaluates the same robot.

---

## 7. Build ladder beyond the current projects

Confirmed interest (Oct 30, 2026): hands and humanoids, built for the experience of shipping policies to that kind of hardware and understanding why they broke. Design rule: **build the smallest real version of each thing that touches the same problems and the same stack those teams use.** Order is a proposed default.

| # | Build | Cost (rough, Oct 2026) | What it touches | Prerequisite | Status |
|---|---|---|---|---|---|
| 1 | Arm → world model (this program) | GPU rental; SO-101 owned | VLA post-training, evaluation, synthetic data | — | In flight / starting |
| 2 | **Hand on a stand**: CMU LEAP Hand v1 (16-DoF, Dynamixel) on a fixed base; in-hand reorientation; sim-to-real RL in Isaac Lab or ManiSkill3; teleop via Quest 3S hand tracking or webcam + MediaPipe | ~$2.3k incl. headset | Multi-finger control, contact-rich sim-to-real, retargeting (mapping human finger motion to robot joints), later tactile | Arm project shipped its real-arm milestone; 3D printer | Future option (next hardware after the arm) |
| 3 | **Humanoid locomotion in simulation**: G1/H1-class walking policy in Isaac Lab with PPO and domain randomization | Free beyond GPU rental (~1–3 h per run) | The literal entry task for humanoid locomotion teams; massively parallel sim; system identification | Linux + NVIDIA GPU | Future option (can start any time) |
| 4 | **Small real legged platform**: Pupper-class quadruped (~$1k) or an open-source humanoid built for RL sim-to-real (Berkeley Humanoid Lite, ToddlerBot, ~$5–6k, 3D-printed) | $1k–6k | First real sim-to-real locomotion; compliance; fall handling | #3 results; printer | Future option |
| 5 | **Whole-body from human motion**: retarget human video/mocap to the small humanoid (HumanPlus-style), sim first | Included above | Motion retargeting, whole-body control | #4 | Future option |
| 6 | **Real-robot RL on the arm** (HIL-SERL-style, episodes on the physical arm with human interventions) | Owned hardware + GPU | Online RL, learned rewards, intervention data | Arm project complete | Confirmed follow-on |
| 7 | **Drone missions D7+** (object search, mapping unknown rooms, …) one at a time | Drone kit | Perception, mapping, mission intelligence | D6 | Planned |

Skip list (confirmed as "don't chase for novelty", still allowed for learning if the owner decides): Unitree G1-class humanoids, Allegro/Shadow-class hands, lab arms (Franka, xArm), video world models trained from scratch, massive cross-embodiment pretraining. They teach little that the cheaper builds don't, at 5–20× the price.

---

## 8. Research program

### 8.1 Where novelty comes from at this scale
1. **Cheap hardware as the variable.** Labs publish on Frankas and Allegros; almost nobody publishes what breaks with backlash and 2 mm repeatability.
2. **Verification, evaluation and data.** The lever is experimental rigor, not compute.
3. **Untested assumptions.** "Always trust the learned model", "sim success predicts real success", "more demos is better" — each is a study.
4. **A heterogeneous fleet** (arm, hand, drone, small humanoid) that almost no single lab has, enabling cross-embodiment questions about shared infrastructure.

### 8.2 One falsifiable question per build (proposed defaults; freeze each before buying its hardware)

| Build | Question | Baselines | Metric | Why open |
|---|---|---|---|---|
| Arm + world model | Does a world-model verifier at test time (best-of-N action chunks) buy the same real-success gain as RL fine-tuning on a low-cost arm, and at what N does it stop? | N = 1; GRPO-tuned policy | Paired real success; compute per episode | Published test-time-scaling work uses learned value heads on lab arms |
| Drone | When should the planner trust a learned residual-dynamics model? Gate by calibrated uncertainty vs always-on vs never-on | Nominal model; ungated learned model | Tracking error and interventions under held-out disturbances; shadow first | Learned-dynamics MPC papers assume always-on |
| Hand on a stand | Can an evaluator trained in sim pick the better real in-hand policy without real episodes? | Raw sim success as predictor | Selection regret vs real, with and without cheap tactile | Evaluator validation exists for arms, nearly absent for hands |
| Sim locomotion | Can a learned proprioceptive monitor predict falls before they happen, and with what lead time vs false-alarm rate? | Tilt/velocity thresholds | Lead time, false alarms, recovery success | The field publishes policies, not monitors |
| Small humanoid | Does the fall monitor transfer from sim to a 3D-printed compliant humanoid, and which motions retargeted from phone video survive that compliance? | Mocap-quality retargeting numbers from the literature | Tracking error and success per motion class | Low-cost compliant platforms are under-studied |

Thesis-level question tying them together: **which parts of a learned evaluator / world model transfer across embodiments, and which have to be rebuilt per robot?**

### 8.3 The autonomous-improvement loop (the extension that produces results)
Stacked on the world-model project; each layer is a paper-shaped result:
1. **Verifier at test time** — sample N action chunks from the VLA, score them with the evaluator/success judge, execute the best; no retraining.
2. **Verifier as reward for online RL on the real arm** — HIL-SERL-style, learned success judge replaces as many human labels as it safely can; measure labels saved and failure modes (reward hacking, false optimism). This is RLVR for robots — the owner's professional edge.
3. **Data curation closing the loop** — which experience goes back into training (all, quality-filtered, failure-weighted, synthetic-augmented); scaling curves of real success vs data volume and quality.

Guardrails that make these results trustworthy are part of the world-model protocol (`world-model/docs/EVALUATION_PROTOCOL.md`): independent final assessment vs training reward, policy-identity holdouts, sealed confirmation suites with logged access, paired randomized trials, abstention, measured false optimism and selection regret.

### 8.4 Method for making sure a question is novel
1. Before buying hardware for a build, read the last ~12 months in that sub-area and write a one-page table: paper, hardware, claim, what was left untested. The question comes from the last column.
2. Pre-write the abstract with blanks for the numbers. If the result is only interesting when the answer is "yes", pick a different question — a clean "no" on an untested assumption is publishable.
3. Email one or two authors a specific short question about their setup.

### 8.5 Publication and access path (proposed defaults)
- Write up as you go: a 4-page workshop paper (CoRL, RSS, ICRA workshops) after the first verifier result; open-source release; results shared in the LeRobot community where low-cost-arm work is visible.
- Graduate school in Spring 2027 is the door to lab compute and co-authors — arrive with real-arm results and a preprint, not a plan. Target groups working on learning from human feedback / preference-based RL for robots and on manipulation and language grounding.
- Say plainly that frontier-lab post-training data QA is a credential robot-learning labs are bottlenecked on.
- Realistic bar: workshop papers and preprints that get cited and open doors; main-track papers come later through those doors.

---

## 9. Hardware and infrastructure plan

Source of detail: the owner's "Lab Purchase Plan v1" (Oct 30, 2026; prices are US street prices seen Sept–Oct 2026 and move weekly). **This section records the plan; it authorizes nothing. Every purchase is an owner action.**

| Tier | When | What | Rough total | Program purpose |
|---|---|---|---|---|
| 1 | Now | **Linux workstation**: Ryzen 9 class, 64 GB DDR5, 4 TB NVMe, 1,200 W PSU sized for a second card, Ubuntu 24.04. GPU paths: lean = used RTX 4090 24 GB (~$2.6k, Sept 2026 used prices); premium = RTX 5090 32 GB only at its ~$4.3k first-party floor; 48 GB RTX PRO 5000 only on a reseller quote ≤ ~$5.5k | $5.3–5.9k lean; $7.2–8.3k premium | The one purchase with no cloud substitute: Isaac Lab needs a local RTX card; real-robot RL needs the GPU next to the arm; cameras/servos on USB. Headless, reached from the Macs over Tailscale |
| 1 | ~Black Friday | **3D printer**: Bambu Lab P1S (P2S Combo if ≤ ~$700 in US stock) + hardened nozzle, PETG/PLA/ASA, dryer | $600–900 | Rocket parts, LEAP hand, camera mounts, fixtures, drone parts, printed humanoids |
| 1 | Now | **Arm bench kit**: 2020 extrusion frame, rigid camera mounts, constant lighting, AprilTag boards, 8 spare STS3215 servos, load cell + IR break-beam success sensors, 8–12 TB backup HDD | $700–1,000 | Evaluation protocol: nothing moves between sessions; objective success labels independent of cameras |
| 1 | Now | **Electronics bench + rocket flight computer**: soldering, multimeter, bench PSU, Teensy 4.1/ESP32-S3, IMU, barometer, servos, 2S LiPos | $400–550 | Rocket, drone, hand all need it |
| 2 | After D0 + D1 | **Drone kit**: Holybro X500 V2 PX4 dev kit (Pixhawk 6C, M10 GPS, ~$609, sold out at Holybro Oct 30, 2026; dealers $540–950), Jetson Orin Nano Super 8 GB (repriced $249 → $399 July 2026), OAK-D Pro or RealSense D435i, 3 × 4S 5000 mAh, RadioMaster TX16S, containment, Part 107 (~$175 exam) | $1.9–2.3k | D2+ ; airframe changes to a 3–5 inch frame if D0 says the test space is a room |
| 2 | After the arm project ships | **LEAP Hand v1 bundle + Quest 3S** | ~$2.3k | Build #2 in §7 |
| 2 | When a weekly workload no longer fits VRAM | **Second GPU** (same family as the first; check the 15 A circuit; 2–2.5-slot first card keeps the slot usable) | $2.5–5k | 7B-class VLA fine-tunes, video-tier world model, 120B-class local inference |
| Skip | — | Frontier-open inference box ($10–28k); GPUs for XXL pretraining; G1/Allegro/lab arms | $0 | Below ~$500/month API spend a box never pays back; XXL pretraining is 1–3 days on 8×H100 rented vs months at home |

**Rent vs buy rule (proposed default):** rent H100-class for anything bigger than one card (pretraining, large sweeps); own one workstation for the robot in the room. The lean box equals ~7,000–15,000 rented 4090-hours, so it is justified by real-robot RL and Isaac Lab iteration, not rent savings.

**Running costs (LA, ~$0.30/kWh):** ~$50/month training 6 h/day on one card; ~$75/month 24/7 inference; put the numbers in each repo's budget config.

**Environment facts agents must respect:** ManiSkill3 (SAPIEN) and Isaac Lab are Linux + CUDA only; they do not run on the Macs. The Macs handle coding, CAD, slicing, LeRobot teleop/recording, PX4 SITL (Ubuntu VM for ROS 2 + Gazebo), and small local LLMs. Until the workstation exists, GPU work is rented and each repo's `docs/ENVIRONMENT.md` says what runs where.

---

## 10. Program principles (summary; enforceable versions are in each repo's `AGENTS.md`)

1. **Small, measurable increments toward a broad destination.** Every phase has exit tests written and frozen before the work starts; a phase passes only on executed evidence.
2. **Conventional first, learned by evidence.** Baselines exist before learned replacements; learned components pass held-out → shadow → controlled closed-loop before they touch anything real.
3. **Independent validation is permanent.** Training reward, development evaluator and final assessment have separate authority. Sealed suites are opened only with owner authorization and logged.
4. **Sim-first; no hardware before its simulation foundation** (the SO-101 is the approved exception).
5. **One shared technical boundary** (the contract), vendored identically; everything else is per project.
6. **Append-only records.** Data, runs, logs, ledgers, reports and accepted work orders are never deleted or overwritten; corrections are new records.
7. **Budgets are enforced, default $0, and an agent cannot approve its own spending.** Cost is tracked per accepted trajectory, per evaluated checkpoint, per flight hour.
8. **Honest status.** Measured, estimated, mocked and not-run are different words and are never mixed.
9. **Protect everything that already exists.** No edits, launches, cleanups or resource use that could touch another project.
10. **Agile cadence.** Backlog of bounded work orders; one active work order per agent; continuous integration; exit tests as the demo; a retro note per milestone report feeding ADRs and the backlog.

---

## 11. Decision log (program level, dated)

| Date | Decision | Status |
|---|---|---|
| 2026-09-25 | Long-term target: lead engineer of a physical-AI product, potentially technical founder; move into physical AI ASAP | Confirmed |
| 2026-09 | Physical AI Leadership Roadmap with Stages 0–7; manipulation first; no hardware before sim foundations | Confirmed |
| 2026-10-11 | Physical-AI interest is not medical-first; areas: autonomous/aerial, defense, medicine, space | Confirmed |
| 2026-10-25 | Next ML project is fine-tuning + RL on a pre-trained open model, exciting and usable in the real world, not a benchmark replication | Confirmed |
| 2026-10-26 | Arm project (`vla-rl-so101`) chosen; SO-101 pair + webcams ordered; sim-first; HIL-SERL real-robot RL as follow-on | Confirmed |
| 2026-10-26 | Rocket project (`rocket-twin`) started alongside | Confirmed |
| 2026-10-30 | Microduck dropped | Confirmed |
| 2026-10-30 | Omni Drone and World Model & Planner are the next two projects, built as two separate projects; world model must serve a purpose beyond the drone | Confirmed |
| 2026-10-30 | World model's first task/environment is the arm project's sim; arm is first baseline and evaluation subject | Confirmed |
| 2026-10-30 | No rocket warm-up for the world model | Confirmed (adopted from review) |
| 2026-10-30 | Three world-model products with separate evidence (action-chunk scorer; closed-loop evaluator; SFT-route synthetic data); M4 branches from M0/M1 | Confirmed (adopted from review) |
| 2026-10-30 | Drone ladder D0–D7+, conventional first, safety checks inside stage exit tests; D3 optional; Part 107 planned | Confirmed (adopted from review) |
| 2026-10-30 | Hands and humanoids are future builds for experience; research questions required for every build | Confirmed |
| 2026-10-30 | Buy a Linux NVIDIA workstation plus printer, bench kit and electronics bench; drone kit, LEAP hand and second GPU at milestones; skip inference box and pretraining GPUs | Confirmed intent; no purchase made |
| 2026-10-30 | Agents work autonomously and iteratively inside the designated new repositories (branches, PRs, merges under CI); separate approval for spending, hardware motion/flight, destructive operations, sealed-suite access, existing-project changes | Confirmed |
| 2026-10-30 | Never delete or overwrite data, runs, logs, reports; always append or create a new record | Confirmed |
| 2026-10-31 | One central program document (this file) carried identically in both repositories and in the Claude Project | Confirmed |

---

## 12. Open decisions (owner)

| # | Decision | Default until decided | Blocks |
|---|---|---|---|
| 1 | Workstation GPU path: used 4090 now, 5090 at the $4,299 floor, or PRO 5000 on a ≤ $5.5k quote | Lean (used 4090) | Nothing immediately; GPU-tier work rents meanwhile |
| 2 | RAM 64 GB vs 96 GB | 64 GB | — |
| 3 | AM5 self-build vs prebuilt vs Threadripper/RDIMM platform | AM5 self-build | — |
| 4 | Drone test space: garage/field vs room (decides X500 V2 vs 3–5 inch frame and containment method) | Unknown — D0 must resolve | Drone hardware purchase |
| 5 | Companion computer (Orin Nano Super 8 GB vs Orin NX 16 GB) and depth camera (OAK-D Pro vs RealSense D435i) | Orin Nano Super; OAK-D Pro | Drone BOM |
| 6 | LEAP Hand v1 full bundle vs Lite | v1 full | Build #2 |
| 7 | Remote repository designation for each new project (account, name, private) | None designated; local git only | Pushes, PRs on GitHub |
| 8 | Open-source license for the two repositories | None (all rights reserved) until chosen | Public release |
| 9 | Where sealed evaluation data physically lives (outside agent access) | Unknown | M2 real validation |
| 10 | Hardware purchase timing (Black Friday window for printer; workstation now) | As in §9 | — |

---

## 13. Glossary (plain language)

- **VLA (vision-language-action model):** a policy that takes camera images and a text instruction and outputs robot actions.
- **GRPO:** a reinforcement-learning method that samples several outputs from the current policy and pushes toward the ones that scored better.
- **World model:** a learned model that predicts what happens next given the current situation and an action.
- **Latent world model:** one that predicts in a compressed internal representation rather than in pixels.
- **MPC (model-predictive control):** try many candidate action sequences through a model, keep the best, execute its first step, observe, replan.
- **Action chunk:** a short sequence of actions a policy emits at once.
- **Evaluator:** a system that predicts how well a policy will do without running it on the real robot.
- **Inverse dynamics model (IDM):** looks at two frames and guesses the action between them.
- **Sim-to-real gap:** the difference between how a simulator and reality respond to the same actions.
- **VIO:** camera + inertial sensor position tracking without GPS.
- **SITL:** software-in-the-loop — the real flight-controller software running against a simulator.
- **Residual dynamics model:** physics model plus a learned correction for what the physics misses.
- **Sealed suite:** evaluation data nobody looks at during development; opened once, with authorization, to confirm a result.
- **Exit test:** a pre-written, numeric test that must pass with evidence before a phase is called done.
- **Work order (WO):** a bounded unit of agent work with acceptance tests; the program's backlog item.
- **ADR:** architecture decision record — a dated note of a decision, its alternatives and its reasons.

---

## 14. Changelog of this document

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-31 | First consolidated program document, assembled from the Sept–Oct 2026 planning conversations, the Physical AI Leadership Roadmap, the Lab Purchase Plan v1, and the reviewed starter-kit material. |
