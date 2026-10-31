"""Simulator adapter: export through the contract, replay from the initial state, negative tests.

The logic here runs on the CPU tier against any ``SimEnv``. ``ManiSkillPickCube`` is the real
adapter and needs the robotics environment, which is separate from the tooling environment
(docs/ENVIRONMENT.md section 1); it has **not run** yet.
"""

from __future__ import annotations
