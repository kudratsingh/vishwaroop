# SOURCES.md — primary sources and the date each was checked

These are references, not promises of compatibility with this project's hardware or stack. Recheck regulations, versions, availability and prices before acting on them. A design choice citing a source is a recommendation, not evidence that the cited method already works here.

## Regulatory (checked 2026-10-30 for the reference bundle; carried forward)
- [S1] FAA, Recreational Flyers — purpose, not payment, determines applicability; non-recreational small-UAS operations generally fall under Part 107. https://www.faa.gov/uas/recreational_flyers
- [S2] FAA, cost of the remote pilot certificate — approximately $175 for the initial knowledge test. https://www.faa.gov/faq/how-much-does-it-cost-get-remote-pilot-certificate
- [S3] FAA, registration — Part 107 registration ($5 per aircraft, three years) and the recreational-only weight exception. https://www.faa.gov/uas/getting_started/register_drone
- [S4] FAA, Remote ID — compliance routes and FRIA qualification. https://www.faa.gov/uas/getting_started/remote_id
- [S5] FAA, indoors-only operations — Part 107 does not apply to operations conducted indoors only. https://www.faa.gov/faq/do-faa-rules-and-regulations-apply-commercial-uas-or-drone-operations-conducted-indoors-only

## Flight stack and simulation (documentation references, not tested pins)
- [S6] PX4 v1.17 Offboard mode — state-estimate prerequisites, heartbeat vs setpoint stream, offboard-loss behaviour. https://docs.px4.io/v1.17/en/flight_modes/offboard
- [S7] ManiSkill trajectory replay — initial-state initialization vs forcing recorded states (`--use-env-states`); for executability tests restore the initial state only. https://maniskill.readthedocs.io/en/latest/user_guide/datasets/replay.html

## Robot learning references
- [S8] DreamGen (NVIDIA Research) — generated demonstrations and pseudo-action extraction. https://research.nvidia.com/labs/gear/dreamgen/
- [S9] WorldGym (ICLR 2026) — action-conditioned video environments for evaluating policies. https://proceedings.iclr.cc/paper_files/paper/2026/hash/7f5e909ac0324db03506b380c695ffaf-Abstract-Conference.html
- [S10] HIL-SERL — learned binary rewards and human-intervention RL. https://hil-serl.github.io/
- [S11] AprilTag (University of Michigan) — camera-relative tag pose. https://april.eecs.umich.edu/software/apriltag.html
- [S12] TD-MPC2 — latent world model planning without an image decoder. https://www.tdmpc2.com/
- [S13] PlaNet / Dreamer line — recurrent latent world models; observation update vs imagination. https://arxiv.org/abs/1811.04551
- [S14] PETS — probabilistic dynamics ensembles with uncertainty propagation for MPC. https://arxiv.org/abs/1805.12114
- [S15] Learned aerodynamic residuals inside quadrotor MPC (Torrente et al., RA-L 2021). https://rpg.ifi.uzh.ch/docs/RAL21_Torrente.pdf
- [S16] NIST e-Handbook — Wilson interval for a binomial proportion. https://www.itl.nist.gov/div898/handbook/

## Hardware and prices (checked 2026-10-30 by the owner's assistant; street prices move weekly)
- [H1] Used RTX 4090 / RTX 5090 floor / used RTX 3090 / rental rates (Sept 25, 2026). https://openclawdc.com/blog/is-the-rtx-4090-worth-it-local-llm/
- [H2] RTX PRO 5000 Blackwell price tracker (Oct 30, 2026: $8,000 current low; 12-month low $4,400). https://gpuprix.com/us/gpus/rtx-pro-5000-blackwell
- [H3] 64 GB DDR5 kit prices (Oct 30, 2026: cheapest new kit $930). https://datacenterdisk.com/ram/ddr5/64gb
- [H4] 128 GB DDR5 kit prices (Oct 29, 2026: from $2,816). https://datacenterdisk.com/ram/ddr5/128gb
- [H5] Holybro PX4 Development Kit X500 V2 — $609 (Pixhawk 6C) / $769 (6X); contents, 1.5 kg payload, ~18 min hover on 5000 mAh; sold out at Holybro on Oct 30, 2026. https://holybro.com/products/px4-development-kit-x500-v2
- [H6] NVIDIA Jetson repricing (July 21, 2026): Orin Nano Super dev kit $249 → $399. https://hwbusters.com/news/nvidia-jetson-prices-jump-up-to-101-the-249-orin-nano-super-is-now-399/
- [H7] Bambu Lab US store, P series — P1S $549 list-sale on Oct 30, 2026 (list $699). https://us.store.bambulab.com/collections/p-series
- [H8] LEAP Hand — CMU/ROBOTIS open-source hand; roughly $2,000 all-in per CMU. https://leaphand.com/ and https://www.robotis.us/leap-hand-bundle-xc330/

## Not verified in this packaging pass
Current PX4 stable release and its tested Gazebo/ROS 2 pairing; ManiSkill3/SAPIEN release numbers; Isaac Sim/Isaac Lab support for Ubuntu 24.04; LeRobot SO-101 driver status. Each repository's first work order resolves and records these pins (`config/stack-lock.pending.json`).
