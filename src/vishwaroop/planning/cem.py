"""CEM model-predictive control for pick-and-place, over the learned or the nominal model.

The cost is staged from known geometry, read from the real current state: approach above the
cube, descend, close, carry to above the target, lower, open, then rise. Both planners use the
same cost, settings and budget; only the model differs (``evals/M1-planner-scorer.json``). The
learned model's calibrated spread adds an uncertainty penalty.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from ..models.compute_pilot import HISTORY, HORIZON, JOINTS, MEMBERS, _torch
from ..models.cube_study import VARIANTS, _rollout

REST_HEIGHT_M = 0.0125
TARGET_RADIUS_M = 0.015625
WRIST_ROLL_RAD = 1.5708  # the scripted controller's, from known geometry
GRIPPER = 5
ROLL = 4

APPROACH, DESCEND, CLOSE, CARRY, PLACE, RISE = range(6)
STAGES = ("approach", "descend", "close", "carry", "place", "rise")


@dataclass(frozen=True)
class Settings:
    """Everything the planner does, frozen before the suite runs."""

    samples: int = 256
    iterations: int = 5
    elite_fraction: float = 0.125
    arm_spread_rad: float = 0.08
    gripper_spread_rad: float = 0.2
    approach_height_m: float = 0.05
    carry_height_m: float = 0.05
    aligned_xy_m: float = 0.008
    grasp_height_m: float = 0.012
    at_cube_m: float = 0.012
    open_rad: float = -0.3
    closed_rad: float = -0.8
    gripper_weight: float = 0.02
    roll_weight: float = 0.01
    flag_weight: float = 0.05
    smooth_weight: float = 0.01
    uncertainty_weight: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def stage_of(
    state: list[float], tool: tuple[float, float, float], settings: Settings, carried: bool
) -> int:
    """The task stage, from the real state and whether the cube has been held this episode."""
    cube = state[6:9]
    target = state[9:12]
    held = state[12] >= 0.5
    cube_to_target = math.hypot(cube[0] - target[0], cube[1] - target[1])
    if held:
        return CARRY if cube_to_target > settings.aligned_xy_m else PLACE
    placed = carried and cube_to_target <= TARGET_RADIUS_M and abs(cube[2] - REST_HEIGHT_M) < 0.004
    tool_to_cube_xy = math.hypot(tool[0] - cube[0], tool[1] - cube[1])
    if placed:
        return RISE
    if tool_to_cube_xy > settings.aligned_xy_m:
        return APPROACH
    if math.dist(tool, cube) > settings.at_cube_m:
        return DESCEND
    return CLOSE


class Planner:
    """One CEM decision per control step, warm-started from the last plan."""

    def __init__(
        self,
        stats: dict[str, Any],
        layers: list[Any],
        variant: str,
        settings: Settings,
        lower: list[float],
        upper: list[float],
        cube_scales: list[float] | None,
        device: str,
        seed: int,
    ) -> None:
        torch = _torch()
        self.stats = stats
        self.layers = layers
        self.variant = VARIANTS[variant]
        self.settings = settings
        self.lower = torch.tensor(lower, device=device)
        self.upper = torch.tensor(upper, device=device)
        self.cube_scales = None if cube_scales is None else torch.tensor(cube_scales, device=device)
        self.device = device
        self.generator = torch.Generator(device="cpu").manual_seed(seed)
        self.plan: Any = None
        self.carried = False

    def reset(self) -> None:
        self.plan = None
        self.carried = False

    def decide(
        self,
        states: list[list[float]],
        actions: list[list[float]],
        tool: tuple[float, float, float],
    ) -> tuple[list[float], dict[str, Any]]:
        """``states`` are the last 4 real states, ``actions`` the 3 before the current one."""
        torch = _torch()
        settings = self.settings
        self.carried = self.carried or states[-1][12] >= 0.5
        stage = stage_of(states[-1], tool, settings, self.carried)
        current = torch.tensor(states[-1], device=self.device)
        if self.plan is None:
            self.plan = current[:JOINTS].expand(HORIZON, JOINTS).clone()
        else:
            self.plan = torch.cat([self.plan[1:], self.plan[-1:]], 0)
        spread = torch.full((HORIZON, JOINTS), settings.arm_spread_rad, device=self.device)
        spread[:, GRIPPER] = settings.gripper_spread_rad
        mean = self.plan
        history_s = torch.tensor(states, device=self.device)
        history_a = torch.tensor(actions, device=self.device)
        elites = max(2, int(settings.samples * settings.elite_fraction))
        best_cost = math.inf
        for _ in range(settings.iterations):
            noise = torch.randn(settings.samples, HORIZON, JOINTS, generator=self.generator).to(
                self.device
            )
            candidates = torch.max(torch.min(mean + noise * spread, self.upper), self.lower)
            candidates[0] = mean  # keep the current mean in play
            cost = self._cost(stage, history_s, history_a, candidates, current)
            order = torch.topk(cost, elites, largest=False).indices
            chosen = candidates[order]
            mean = chosen.mean(0)
            spread = chosen.std(0).clamp_min(1e-3)
            best_cost = min(best_cost, float(cost[order[0]].item()))
        self.plan = mean
        action: list[float] = mean[0].tolist()
        return action, {"stage": STAGES[stage], "cost": best_cost}

    def _cost(
        self, stage: int, history_s: Any, history_a: Any, candidates: Any, current: Any
    ) -> Any:
        torch = _torch()
        settings = self.settings
        count = candidates.shape[0]
        states = history_s.expand(MEMBERS, count, HISTORY + 1, -1)
        actions = torch.cat(
            [history_a.expand(MEMBERS, count, HISTORY, -1), candidates.expand(MEMBERS, -1, -1, -1)],
            dim=2,
        )
        with torch.no_grad():
            means, log_vars = _rollout(self.stats, self.variant, self.layers, states, actions)
        predicted = torch.stack(means, 2)  # members, samples, horizon, 13
        tool = self.stats["kinematics"](predicted[..., :JOINTS])
        cube = predicted[..., 6:9]
        target = current[9:12]
        flag = predicted[..., 12]
        gripper = candidates[:, :, GRIPPER]
        rest = torch.tensor([0.0, 0.0, REST_HEIGHT_M], device=self.device)
        up = torch.tensor([0.0, 0.0, 1.0], device=self.device)
        open_gap = (gripper - settings.open_rad).abs()
        closed_gap = (gripper - settings.closed_rad).abs()
        if stage == APPROACH:
            goal = current[6:9] + up * settings.approach_height_m
            step_cost = (tool - goal).norm(dim=-1).mean(0) + settings.gripper_weight * open_gap
        elif stage == DESCEND:
            goal = current[6:9] + up * (settings.grasp_height_m - REST_HEIGHT_M)
            step_cost = (tool - goal).norm(dim=-1).mean(0) + settings.gripper_weight * open_gap
        elif stage == CLOSE:
            step_cost = (
                (tool - cube).norm(dim=-1).mean(0)
                + settings.gripper_weight * closed_gap
                - settings.flag_weight * flag.clamp(0.0, 1.0).mean(0)
            )
        elif stage == CARRY:
            goal = torch.cat([target[:2], (rest + up * settings.carry_height_m)[2:]])
            step_cost = (cube - goal).norm(dim=-1).mean(0) + settings.gripper_weight * closed_gap
        elif stage == PLACE:
            goal = torch.cat([target[:2], rest[2:]])
            low = (cube[..., 2] - REST_HEIGHT_M).mean(0) < 0.004
            step_cost = (cube - goal).norm(dim=-1).mean(0) + settings.gripper_weight * torch.where(
                low, open_gap, closed_gap
            )
        else:
            goal = target + up * settings.approach_height_m
            step_cost = (tool - goal).norm(dim=-1).mean(0) + settings.gripper_weight * open_gap
        step_cost = (
            step_cost + settings.roll_weight * (candidates[:, :, ROLL] - WRIST_ROLL_RAD).abs()
        )
        moves = torch.cat(
            [candidates[:, :1] - current[:JOINTS], candidates[:, 1:] - candidates[:, :-1]], 1
        )
        step_cost = step_cost + settings.smooth_weight * moves.norm(dim=-1)
        if self.cube_scales is not None and settings.uncertainty_weight > 0:
            variance = (torch.exp(torch.stack(log_vars, 2)) * self.stats["delta_std"].pow(2)).mean(
                0
            )
            variance = variance + predicted.var(0, unbiased=False)
            cube_std = variance[..., 6:9].sqrt().pow(2).mean(-1).sqrt() * self.cube_scales
            step_cost = step_cost + settings.uncertainty_weight * cube_std
        return step_cost.sum(-1)
