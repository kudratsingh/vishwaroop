"""FABRICATED environments for WO-022's recorder and gate tests. Not a simulator.

``FakeM3Env`` is ``fake_scene.FakeSceneEnv`` (six joints that follow the action, a cube out of the
SO-100's reach so the scripted plan fails and holds, a fake render) plus an ``object_grasped``
stream, so the rubric can decide. Options make a replay misbehave:

- ``lift``: the cube rises to 0.0525 m for control steps 2 to 4 after each reset or restore, then
  rests, so the rubric says ``outside_target`` instead of ``never_lifted``;
- ``drift``: joint 0 is offset by ``drift`` rad times the number of restores, so replays deviate;
- ``flip_on_restore``: on that restore, ``object_grasped`` reads 1 from step 5 on, so that repeat's
  label becomes ``still_grasped`` while every compared stream is unchanged;
- ``grasp_stream=False``: no ``object_grasped`` stream, so every label is undecided.

Its configuration names the M0 task's embodiment, as a replay's identity check requires.

Nothing here says anything about ManiSkill3 or any robot.
"""

from __future__ import annotations

from typing import Any

from fake_scene import FakeSceneEnv
from vishwaroop.sim.env import Packet, StreamSpec

REST_Z = 0.0125
LIFTED_Z = 0.0525


class FakeM3Env(FakeSceneEnv):
    def __init__(
        self,
        *,
        lift: bool = False,
        drift: float = 0.0,
        flip_on_restore: int | None = None,
        grasp_stream: bool = True,
    ) -> None:
        super().__init__(exposed=True)
        self._grasp_stream = grasp_stream
        if grasp_stream:
            self.stream_specs = [
                *self.stream_specs,
                StreamSpec(
                    "object_grasped", "other", "world", ["bool"], [1], "float64", "reference_only"
                ),
            ]
        self._lift = lift
        self._drift = drift
        self._flip = flip_on_restore
        self._steps = 0

    def _grasped(self) -> float:
        return 1.0 if self._flip == self._restores and self._steps >= 5 else 0.0

    def _packet(self) -> Packet:
        if not self._grasp_stream:
            return super()._packet()
        return {**super()._packet(), "object_grasped": [self._grasped()]}

    def configuration(self) -> dict[str, Any]:
        return {**super().configuration(), "embodiment_id": "maniskill3_so100"}

    def reset(self, seed: int) -> Packet:
        self._steps = 0
        super().reset(seed)
        return self._packet()

    def restore_state(self, state: bytes) -> Packet:
        self._steps = 0
        super().restore_state(state)
        return self._packet()

    def step(self, action: list[float]) -> Packet:
        self._steps += 1
        super().step(action)
        self._joints[0] += self._drift * self._restores
        lifted = self._lift and 2 <= self._steps <= 4
        self._object[2] = LIFTED_Z if lifted else REST_Z
        return self._packet()
