"""Can the M1 models train on this Mac? Time per epoch and peak memory, not an exit-test result.

Each workload runs in its own process under ``/usr/bin/time -l``, so each has its own peak memory.
It reads train episodes only. The models have realistic sizes but are not the WO-004 and WO-005
models: the nominal model is a simple joint lag, and the scorer's labels are stand-ins, because the
branch data does not exist yet. So timing and memory are the results here, and nothing in this
file supports a claim about prediction quality or a task succeeding.

    python -m vishwaroop.models.compute_pilot --manifest artifacts/manifests/m0-dataset-v1.json

Run it from the repository root, in the robotics environment. Results go to ``pilot.json`` in a new
run directory. Exit codes: 0 measured, 2 refused, 3 a workload failed.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import platform
import re
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..sim.baseline import VARIANTS, ScriptedPickPlace
from ..sim.env import ManiSkillPickCube
from ..sim.runlog import ledgered_run, require_code_root
from ..sim.so100_kinematics import (
    _CHAIN,
    _FIXED_TIP,
    _GRIPPER_ORIGIN,
    _MOVING_TIP,
    BASE_POSITION,
    BASE_YAW,
    tool_point,
)
from .pilot_data import ACTION_SIZE, STATE_SIZE, load_train, split_holdout

HISTORY = 3
HORIZON = 10
WINDOW = HISTORY + HORIZON + 1
MEMBERS = 3
HIDDEN = 256
BATCH = 256
LATENT_SEQUENCE = 32
LATENT_BATCH = 64
LATENT_STRIDE = 8
PREDICTOR_WEIGHTS = "predictor-mps.pt"
JOINTS = 6
CHILD_TIMEOUT_S = 1800
STREAM_SLICES = {
    "joint_position": (0, 6),
    "object_position": (6, 9),
    "target_position": (9, 12),
    "object_grasped": (12, 13),
}


def _torch() -> Any:
    import torch

    return torch


def _sync(device: str) -> None:
    if device == "mps":
        _torch().mps.synchronize()


def _peak_tracker(device: str) -> Callable[[], float]:
    """A function that samples Metal's allocation and returns the highest seen, in bytes."""
    torch = _torch()
    peak = [0.0]

    def sample() -> float:
        if device == "mps":
            peak[0] = max(peak[0], float(torch.mps.driver_allocated_memory()))
        return peak[0]

    return sample


class _Data:
    """Windows of the train partition, normalized on the fit part only."""

    def __init__(
        self,
        manifest: Path,
        device: str,
        split: Callable[[Any], tuple[list[Any], list[Any]]] = split_holdout,
    ) -> None:
        torch = _torch()
        fit, holdout = split(load_train(manifest, Path()))
        self.device = device
        self.fit_episodes = len(fit)
        self.holdout_episodes = len(holdout)
        fit_states = [torch.tensor(item.states, dtype=torch.float32) for item in fit]
        fit_actions = [torch.tensor(item.actions, dtype=torch.float32) for item in fit]
        self.transitions = sum(len(item) for item in fit_actions)
        every = torch.cat(fit_states)
        self.state_mean = every.mean(0)
        self.state_std = every.std(0).clamp_min(1e-3)
        deltas = torch.cat([s[1:] - s[:-1] for s in fit_states])
        self.delta_std = deltas.std(0).clamp_min(1e-4)
        action = torch.cat(fit_actions)
        joints = torch.cat([s[:-1, :JOINTS] for s in fit_states])
        moves = torch.cat([s[1:, :JOINTS] - s[:-1, :JOINTS] for s in fit_states])
        gap = action - joints
        self.lag = ((moves * gap).sum(0) / (gap * gap).sum(0).clamp_min(1e-9)).clamp(0.0, 1.0)
        self.action_mean = action.mean(0)
        self.action_std = action.std(0).clamp_min(1e-3)
        self.windows_s, self.windows_a = self._windows(fit, WINDOW)
        self.holdout_s, self.holdout_a = self._windows(holdout, WINDOW)
        self.sequences_s, self.sequences_a = self._windows(fit, LATENT_SEQUENCE + 1, LATENT_STRIDE)
        for name in (
            "state_mean",
            "state_std",
            "delta_std",
            "lag",
            "action_mean",
            "action_std",
            "windows_s",
            "windows_a",
            "holdout_s",
            "holdout_a",
            "sequences_s",
            "sequences_a",
        ):
            setattr(self, name, getattr(self, name).to(device))

    @staticmethod
    def _windows(sequences: list[Any], length: int, stride: int = 1) -> tuple[Any, Any]:
        torch = _torch()
        state_parts = []
        action_parts = []
        for item in sequences:
            states = torch.tensor(item.states, dtype=torch.float32)
            actions = torch.tensor(item.actions, dtype=torch.float32)
            for start in range(0, len(states) - length + 1, stride):
                state_parts.append(states[start : start + length])
                action_parts.append(actions[start : start + length - 1])
        return torch.stack(state_parts), torch.stack(action_parts)


def _nominal(data: Any, state: Any, action: Any) -> Any:
    """The next state under a per-joint lag, with everything else held still."""
    torch = _torch()
    joints = state[..., :JOINTS]
    moved = joints + data["lag"] * (action - joints)
    return torch.cat([moved, state[..., JOINTS:]], dim=-1)


def _new_ensemble(sizes: list[int]) -> list[tuple[Any, Any]]:
    torch = _torch()
    layers = []
    for size_in, size_out in itertools.pairwise(sizes):
        weight = torch.empty(MEMBERS, size_in, size_out)
        for member in range(MEMBERS):
            torch.nn.init.xavier_uniform_(weight[member])
        layers.append(
            (
                torch.nn.Parameter(weight),
                torch.nn.Parameter(torch.zeros(MEMBERS, 1, size_out)),
            )
        )
    return layers


def _ensemble_forward(layers: list[tuple[Any, Any]], x: Any) -> Any:
    """``x`` has shape (members, batch, inputs)."""
    torch = _torch()
    for index, (weight, bias) in enumerate(layers):
        x = torch.bmm(x, weight) + bias
        if index < len(layers) - 1:
            x = torch.nn.functional.silu(x)
    return x


def _predict_step(
    stats: dict[str, Any], layers: list[Any], history: Any, state: Any, action: Any
) -> tuple[Any, Any]:
    """One step of nominal plus residual. Shapes: (members, batch, ...)."""
    torch = _torch()
    inputs = torch.cat(
        [
            (state - stats["state_mean"]) / stats["state_std"],
            (action - stats["action_mean"]) / stats["action_std"],
            history,
        ],
        dim=-1,
    )
    output = _ensemble_forward(layers, inputs)
    mean, log_var = output[..., :STATE_SIZE], output[..., STATE_SIZE:]
    return _nominal(stats, state, action) + mean * stats["delta_std"], log_var.clamp(-10.0, 4.0)


def _normalized_pair(stats: dict[str, Any], state: Any, action: Any) -> Any:
    torch = _torch()
    return torch.cat(
        [
            (state - stats["state_mean"]) / stats["state_std"],
            (action - stats["action_mean"]) / stats["action_std"],
        ],
        dim=-1,
    )


def _rollout_history(stats: dict[str, Any], states: Any, actions: Any) -> Any:
    """Flattened, normalized (state, action) pairs for the ``HISTORY`` steps before the rollout."""
    pairs = _normalized_pair(stats, states[..., :HISTORY, :], actions[..., :HISTORY, :])
    return pairs.flatten(-2)


def _stats_of(data: _Data) -> dict[str, Any]:
    return {
        "state_mean": data.state_mean,
        "state_std": data.state_std,
        "delta_std": data.delta_std,
        "lag": data.lag,
        "action_mean": data.action_mean,
        "action_std": data.action_std,
    }


def _epoch_result(times: list[float], extra: dict[str, Any]) -> dict[str, Any]:
    return {
        "epochs": len(times),
        "seconds_per_epoch": times,
        "median_seconds_per_epoch": statistics.median(times),
        **extra,
    }


def _rollout(
    stats: dict[str, Any], layers: list[Any], states: Any, actions: Any
) -> tuple[list[Any], list[Any]]:
    """Predictions for steps 1 to ``HORIZON``, feeding each prediction back in."""
    torch = _torch()
    history = _rollout_history(stats, states, actions)
    state = states[..., HISTORY, :]
    means = []
    log_vars = []
    for step in range(HORIZON):
        action = actions[..., HISTORY + step, :]
        mean, log_var = _predict_step(stats, layers, history, state, action)
        means.append(mean)
        log_vars.append(log_var)
        pair = _normalized_pair(stats, state, action)
        history = torch.cat([history[..., STATE_SIZE + ACTION_SIZE :], pair], dim=-1)
        state = mean
    return means, log_vars


def _holdout_rmse(
    data: _Data, stats: dict[str, Any], layers: list[Any]
) -> dict[str, dict[str, list[float]]]:
    """Error by horizon on the pilot's holdout, in state-normalized units. A sanity check only."""
    torch = _torch()
    states = data.holdout_s
    actions = data.holdout_a
    start = states[:, HISTORY]
    previous = states[:, HISTORY - 1]
    truth = states[:, HISTORY + 1 : HISTORY + 1 + HORIZON]
    scale = data.state_std

    def rmse(prediction: Any) -> dict[str, list[float]]:
        error = (prediction - truth) / scale
        parts = {"all": (0, STATE_SIZE), **STREAM_SLICES}
        return {
            name: [math.sqrt(error[:, h, first:last].pow(2).mean().item()) for h in range(HORIZON)]
            for name, (first, last) in parts.items()
        }

    constant = start.unsqueeze(1).expand_as(truth)
    linear = torch.stack([start + (start - previous) * (h + 1) for h in range(HORIZON)], dim=1)
    nominal = []
    state = start
    for h in range(HORIZON):
        state = _nominal(stats, state, actions[:, HISTORY + h])
        nominal.append(state)
    member_batch_s = states.unsqueeze(0).expand(MEMBERS, -1, -1, -1)
    member_batch_a = actions.unsqueeze(0).expand(MEMBERS, -1, -1, -1)
    with torch.no_grad():
        learned = []
        history = _rollout_history(stats, member_batch_s, member_batch_a)
        state = member_batch_s[:, :, HISTORY]
        for h in range(HORIZON):
            action = member_batch_a[:, :, HISTORY + h]
            mean, _ = _predict_step(stats, layers, history, state, action)
            learned.append(mean.mean(0))
            pair = _normalized_pair(stats, state, action)
            history = torch.cat([history[..., STATE_SIZE + ACTION_SIZE :], pair], dim=-1)
            state = mean
    return {
        "constant": rmse(constant),
        "linear": rmse(linear),
        "nominal_joint_lag": rmse(torch.stack(nominal, dim=1)),
        "learned_pilot": rmse(torch.stack(learned, dim=1)),
    }


def predictor(args: argparse.Namespace, device: str, out: Path) -> dict[str, Any]:
    """The 3-member residual ensemble, trained with a 10-step rollout loss."""
    torch = _torch()
    torch.manual_seed(0)
    data = _Data(args.manifest, device)
    stats = _stats_of(data)
    pair = STATE_SIZE + ACTION_SIZE
    sizes = [pair + HISTORY * pair, HIDDEN, HIDDEN, HIDDEN, 2 * STATE_SIZE]
    layers = [
        (w.to(device).detach().requires_grad_(), b.to(device).detach().requires_grad_())
        for w, b in _new_ensemble(sizes)
    ]
    parameters = [item for layer in layers for item in layer]
    optimizer = torch.optim.Adam(parameters, lr=1e-3)
    count = len(data.windows_s)
    peak = _peak_tracker(device)
    times: list[float] = []
    losses: list[float] = []
    for _ in range(args.predictor_epochs):
        start = time.perf_counter()
        order = torch.stack([torch.randperm(count) for _ in range(MEMBERS)], dim=0).to(device)
        total = 0.0
        batches = 0
        for first in range(0, count - BATCH + 1, BATCH):
            index = order[:, first : first + BATCH]
            states = data.windows_s[index]
            actions = data.windows_a[index]
            means, log_vars = _rollout(stats, layers, states, actions)
            loss: Any = 0.0
            for h, (mean, log_var) in enumerate(zip(means, log_vars, strict=True)):
                error = (mean - states[:, :, HISTORY + 1 + h]) / data.delta_std
                loss = loss + (error.pow(2) * torch.exp(-log_var) + log_var).mean()
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(parameters, 100.0)
            optimizer.step()
            total += float(loss.item()) / HORIZON
            batches += 1
            peak()
        _sync(device)
        times.append(time.perf_counter() - start)
        losses.append(total / batches)
    parameter_count = sum(int(item.numel()) for item in parameters)
    if device == "mps":
        torch.save(
            {
                "layers": [(w.detach().cpu(), b.detach().cpu()) for w, b in layers],
                "stats": {k: v.cpu() for k, v in stats.items()},
            },
            out / PREDICTOR_WEIGHTS,
        )
    return _epoch_result(
        times,
        {
            "windows_per_epoch": count,
            "fit_episodes": data.fit_episodes,
            "holdout_episodes": data.holdout_episodes,
            "batch": BATCH,
            "members": MEMBERS,
            "parameters": parameter_count,
            "training_loss_by_epoch": losses,
            "pilot_holdout_rmse_normalized": _holdout_rmse(data, stats, layers),
            "metal_driver_peak_bytes": peak(),
        },
    )


def latent(args: argparse.Namespace, device: str, _out: Path) -> dict[str, Any]:
    """A recurrent state-space model on state observations: 16 updated steps, then 16 imagined."""
    torch = _torch()
    nn = torch.nn
    torch.manual_seed(0)
    data = _Data(args.manifest, device)
    stochastic = 32
    modules = nn.ModuleDict(
        {
            "encoder": nn.Sequential(
                nn.Linear(STATE_SIZE, HIDDEN), nn.SiLU(), nn.Linear(HIDDEN, HIDDEN)
            ),
            "cell": nn.GRUCell(stochastic + ACTION_SIZE, HIDDEN),
            "prior": nn.Linear(HIDDEN, 2 * stochastic),
            "posterior": nn.Linear(2 * HIDDEN, 2 * stochastic),
            "decoder": nn.Sequential(
                nn.Linear(HIDDEN + stochastic, HIDDEN), nn.SiLU(), nn.Linear(HIDDEN, STATE_SIZE)
            ),
        }
    ).to(device)
    optimizer = torch.optim.Adam(modules.parameters(), lr=3e-4)
    count = len(data.sequences_s)
    peak = _peak_tracker(device)
    times: list[float] = []
    losses: list[float] = []

    def sample(parameters: Any) -> tuple[Any, Any, Any]:
        mean, log_std = parameters.chunk(2, dim=-1)
        log_std = log_std.clamp(-5.0, 2.0)
        return mean + torch.randn_like(mean) * log_std.exp(), mean, log_std

    for _ in range(args.latent_epochs):
        start = time.perf_counter()
        order = torch.randperm(count).to(device)
        total = 0.0
        batches = 0
        for first in range(0, count - LATENT_BATCH + 1, LATENT_BATCH):
            index = order[first : first + LATENT_BATCH]
            states = (data.sequences_s[index] - data.state_mean) / data.state_std
            actions = (data.sequences_a[index] - data.action_mean) / data.action_std
            hidden = torch.zeros(LATENT_BATCH, HIDDEN, device=device)
            latent_state = torch.zeros(LATENT_BATCH, stochastic, device=device)
            loss: Any = 0.0
            for step in range(LATENT_SEQUENCE):
                hidden = modules["cell"](
                    torch.cat([latent_state, actions[:, step]], dim=-1), hidden
                )
                prior_sample, prior_mean, prior_log_std = sample(modules["prior"](hidden))
                if step < LATENT_SEQUENCE // 2:
                    embedded = modules["encoder"](states[:, step + 1])
                    latent_state, mean, log_std = sample(
                        modules["posterior"](torch.cat([hidden, embedded], dim=-1))
                    )
                    kl = (
                        prior_log_std
                        - log_std
                        + (log_std.exp().pow(2) + (mean - prior_mean).pow(2))
                        / (2 * prior_log_std.exp().pow(2))
                        - 0.5
                    )
                    loss = loss + 0.1 * kl.sum(-1).mean()
                else:
                    latent_state = prior_sample
                decoded = modules["decoder"](torch.cat([hidden, latent_state], dim=-1))
                loss = loss + (decoded - states[:, step + 1]).pow(2).sum(-1).mean()
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(modules.parameters(), 100.0)
            optimizer.step()
            total += float(loss.item()) / LATENT_SEQUENCE
            batches += 1
            peak()
        _sync(device)
        times.append(time.perf_counter() - start)
        losses.append(total / batches)
    return _epoch_result(
        times,
        {
            "sequences_per_epoch": count,
            "sequence_steps": LATENT_SEQUENCE,
            "batch": LATENT_BATCH,
            "parameters": sum(int(item.numel()) for item in modules.parameters()),
            "training_loss_by_epoch": losses,
            "metal_driver_peak_bytes": peak(),
        },
    )


def _forward_kinematics(joints: Any) -> Any:
    """The tool point for a batch of joints. A test run compares it with ``tool_point``."""
    torch = _torch()

    def rotation(axis: int, angle: Any) -> Any:
        cosine, sine = torch.cos(angle), torch.sin(angle)
        zero, one = torch.zeros_like(angle), torch.ones_like(angle)
        rows = {
            0: (one, zero, zero, zero, cosine, -sine, zero, sine, cosine),
            1: (cosine, zero, sine, zero, one, zero, -sine, zero, cosine),
            2: (cosine, -sine, zero, sine, cosine, zero, zero, zero, one),
        }[axis]
        return torch.stack(rows, dim=-1).reshape(*angle.shape, 3, 3)

    def constant(value: float) -> Any:
        return torch.full(joints.shape[:-1], float(value), device=joints.device, dtype=joints.dtype)

    def fixed_rotation(rpy: tuple[float, float, float]) -> Any:
        return (
            rotation(2, constant(rpy[2]))
            @ rotation(1, constant(rpy[1]))
            @ rotation(0, constant(rpy[0]))
        )

    def vector(value: tuple[float, float, float]) -> Any:
        return torch.stack([constant(item) for item in value], dim=-1)

    def apply(matrix: Any, value: Any) -> Any:
        return (matrix @ value.unsqueeze(-1)).squeeze(-1)

    position = vector(BASE_POSITION)
    frame = rotation(2, constant(BASE_YAW))
    for index, (origin, rpy, (axis, sign)) in enumerate(_CHAIN):
        position = position + apply(frame, vector(origin))
        frame = frame @ fixed_rotation(rpy) @ rotation(axis, sign * joints[..., index])
    fixed_tip = position + apply(frame, vector(_FIXED_TIP))
    origin, rpy = _GRIPPER_ORIGIN
    moving_position = position + apply(frame, vector(origin))
    moving_frame = frame @ fixed_rotation(rpy) @ rotation(2, joints[..., 5])
    moving_tip = moving_position + apply(moving_frame, vector(_MOVING_TIP))
    return (fixed_tip + moving_tip) / 2


def _check_kinematics() -> float:
    """The largest gap, in metres, from the pure-Python model at a few joint values."""
    torch = _torch()
    worst = 0.0
    for joints in ([0.0, 0.4, 0.2, 1.0, 1.57, -0.8], [-0.3, 0.1, -0.5, 0.7, 0.2, 0.3], [0.5] * 6):
        batch = _forward_kinematics(torch.tensor(joints, dtype=torch.float32))
        worst = max(worst, math.dist(batch.tolist(), tool_point(joints)))
    if worst > 1e-4:
        raise ValueError(f"batched kinematics differs from the pure-Python model by {worst} m")
    return worst


class _Planner:
    """CEM over the trained ensemble: bounded actions, a simple cost, an uncertainty penalty."""

    def __init__(
        self, weights: Path, device: str, env_lower: list[float], env_upper: list[float]
    ) -> None:
        torch = _torch()
        saved = torch.load(weights, weights_only=True)
        self.device = device
        self.layers = [(w.to(device), b.to(device)) for w, b in saved["layers"]]
        self.stats = {name: value.to(device) for name, value in saved["stats"].items()}
        self.lower = torch.tensor(env_lower, device=device)
        self.upper = torch.tensor(env_upper, device=device)

    def decide(
        self, state: list[float], samples: int, horizon: int, iterations: int
    ) -> list[float]:
        torch = _torch()
        current = torch.tensor(state, dtype=torch.float32, device=self.device)
        mean = current[:JOINTS].expand(horizon, -1).clone()
        spread = torch.full_like(mean, 0.2)
        elites = max(4, samples // 8)
        with torch.no_grad():
            for _ in range(iterations):
                noise = torch.randn(samples, horizon, ACTION_SIZE, device=self.device)
                candidates = torch.max(torch.min(mean + noise * spread, self.upper), self.lower)
                cost = self._cost(current, candidates)
                best = torch.topk(cost, elites, largest=False).indices
                chosen = candidates[best]
                mean, spread = chosen.mean(0), chosen.std(0).clamp_min(1e-3)
            _sync(self.device)
        result: list[float] = mean[0].tolist()
        return result

    def _cost(self, current: Any, candidates: Any) -> Any:
        torch = _torch()
        samples, horizon, _ = candidates.shape
        state = current.expand(MEMBERS, samples, -1)
        pair = _normalized_pair(
            self.stats, state, self.stats["action_mean"].expand(MEMBERS, samples, -1)
        )
        history = pair.repeat(1, 1, HISTORY)
        cost = torch.zeros(samples, device=self.device)
        for step in range(horizon):
            action = candidates[:, step].expand(MEMBERS, -1, -1)
            mean, _ = _predict_step(self.stats, self.layers, history, state, action)
            pair = _normalized_pair(self.stats, state, action)
            history = torch.cat([history[..., STATE_SIZE + ACTION_SIZE :], pair], dim=-1)
            state = mean
            tool = _forward_kinematics(state[..., :JOINTS])
            to_object = (tool - state[..., JOINTS : JOINTS + 3]).norm(dim=-1)
            to_target = (
                state[..., JOINTS : JOINTS + 3] - state[..., JOINTS + 3 : JOINTS + 6]
            ).norm(dim=-1)
            cost = cost + (to_object + to_target).mean(0) + 0.1 * state.var(0).sum(-1)
        return cost


def _limits() -> tuple[list[float], list[float]]:
    manifest = json.loads(
        next(Path("data/derived/m0-dataset").glob("*/*/episode.json")).read_text(encoding="utf-8")
    )
    action_spec = manifest["action_spec"]
    return list(action_spec["lower"]), list(action_spec["upper"])


def planner(args: argparse.Namespace, device: str, out: Path) -> dict[str, Any]:
    """Milliseconds per CEM decision, on weights from the ``predictor`` workload."""
    torch = _torch()
    torch.manual_seed(0)
    lower, upper = _limits()
    plan = _Planner(out / PREDICTOR_WEIGHTS, device, lower, upper)
    sequences = load_train(args.manifest, Path())
    state = sequences[0].states[0]
    peak = _peak_tracker(device)
    settings = {}
    for samples, horizon, iterations in ((128, 20, 3), (256, 20, 5), (256, 40, 5)):
        times = []
        for _ in range(args.planner_decisions):
            start = time.perf_counter()
            plan.decide(state, samples, horizon, iterations)
            times.append((time.perf_counter() - start) * 1000.0)
            peak()
        settled = times[1:]
        settings[f"samples{samples}-horizon{horizon}-iterations{iterations}"] = {
            "decisions": len(times),
            "first_ms": times[0],
            "median_ms": statistics.median(settled),
            "max_ms_after_first": max(settled),
        }
    return {
        "settings": settings,
        "kinematics_max_gap_m": _check_kinematics(),
        "members": MEMBERS,
        "metal_driver_peak_bytes": peak(),
    }


def closed_loop(args: argparse.Namespace, device: str, out: Path) -> dict[str, Any]:
    """Real physics with a CEM decision at each step, to time the loop. No success is claimed."""
    torch = _torch()
    torch.manual_seed(0)
    lower, upper = _limits()
    plan = _Planner(out / PREDICTOR_WEIGHTS, device, lower, upper)
    env = ManiSkillPickCube()
    steps = 0
    planning = 0.0
    physics = 0.0
    start = time.perf_counter()
    for seed in range(3000, 3000 + args.closed_loop_episodes):
        packet = env.reset(seed)
        for _ in range(args.closed_loop_steps):
            state = [
                *packet["joint_position"],
                *packet["object_position"],
                *packet["target_position"],
                *packet["object_grasped"],
            ]
            mark = time.perf_counter()
            action = plan.decide(state, 256, 20, 5)
            middle = time.perf_counter()
            packet = env.step(action)
            physics += time.perf_counter() - middle
            planning += middle - mark
            steps += 1
    total = time.perf_counter() - start
    return {
        "episodes": args.closed_loop_episodes,
        "steps": steps,
        "total_seconds": total,
        "planning_ms_per_step": planning / steps * 1000.0,
        "physics_ms_per_step": physics / steps * 1000.0,
        "settings": "256 samples, horizon 20, 5 iterations, 3 members",
        "note": "timing only; the model is a short pilot and task success was not assessed",
    }


def scorer(args: argparse.Namespace, device: str, _out: Path) -> dict[str, Any]:
    """Heads for progress, clearance, violation and uncertainty, trained on stand-in labels."""
    torch = _torch()
    nn = torch.nn
    torch.manual_seed(0)
    data = _Data(args.manifest, device)
    modules = nn.ModuleDict(
        {
            "chunk": nn.GRU(ACTION_SIZE, HIDDEN, batch_first=True),
            "state": nn.Sequential(nn.Linear(STATE_SIZE, HIDDEN), nn.SiLU()),
            "shared": nn.Sequential(
                nn.Linear(2 * HIDDEN, HIDDEN), nn.SiLU(), nn.Linear(HIDDEN, HIDDEN), nn.SiLU()
            ),
            "heads": nn.Linear(HIDDEN, 4),
        }
    ).to(device)
    optimizer = torch.optim.Adam(modules.parameters(), lr=1e-3)
    count = len(data.windows_s)
    state_now = data.windows_s[:, HISTORY]
    chunk = data.windows_a[:, HISTORY : HISTORY + HORIZON]
    future = data.windows_s[:, HISTORY + 1 : HISTORY + 1 + HORIZON]
    distance = (future[..., JOINTS : JOINTS + 3] - future[..., JOINTS + 3 : JOINTS + 6]).norm(
        dim=-1
    )
    now_distance = (state_now[:, JOINTS : JOINTS + 3] - state_now[:, JOINTS + 3 : JOINTS + 6]).norm(
        dim=-1
    )
    progress = now_distance - distance[:, -1]
    clearance = future[..., JOINTS + 2].min(dim=1).values
    grasp_lost = ((state_now[:, -1] > 0.5) & (future[:, -1, -1] < 0.5)).float()
    state_input = (state_now - data.state_mean) / data.state_std
    chunk_input = (chunk - data.action_mean) / data.action_std
    peak = _peak_tracker(device)
    times: list[float] = []
    losses: list[float] = []
    for _ in range(args.scorer_epochs):
        start = time.perf_counter()
        order = torch.randperm(count).to(device)
        total = 0.0
        batches = 0
        for first in range(0, count - BATCH + 1, BATCH):
            index = order[first : first + BATCH]
            _, encoded = modules["chunk"](chunk_input[index])
            joined = torch.cat([modules["state"](state_input[index]), encoded[0]], dim=-1)
            outputs = modules["heads"](modules["shared"](joined))
            log_var = outputs[:, 3].clamp(-10.0, 4.0)
            regression = (outputs[:, 0] - progress[index] * 10).pow(2) + (
                outputs[:, 1] - clearance[index] * 10
            ).pow(2)
            violation = nn.functional.binary_cross_entropy_with_logits(
                outputs[:, 2], grasp_lost[index]
            )
            loss = (regression * torch.exp(-log_var) + log_var).mean() + violation
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            total += float(loss.item())
            batches += 1
            peak()
        _sync(device)
        times.append(time.perf_counter() - start)
        losses.append(total / batches)
    return _epoch_result(
        times,
        {
            "windows_per_epoch": count,
            "batch": BATCH,
            "parameters": sum(int(item.numel()) for item in modules.parameters()),
            "training_loss_by_epoch": losses,
            "labels": "stand-ins from logged windows; the real labels need the WO-005 branch data",
            "metal_driver_peak_bytes": peak(),
        },
    )


def branches(args: argparse.Namespace, _device: str, _out: Path) -> dict[str, Any]:
    """Real physics: restore a mid-episode state and run alternative 10-step chunks from it."""
    torch = _torch()
    generator = torch.Generator().manual_seed(0)
    env = ManiSkillPickCube()
    count = 0
    start = time.perf_counter()
    for seed in range(3000, 3000 + args.branch_states):
        packet = env.reset(seed)
        policy = ScriptedPickPlace(VARIANTS["nominal"])
        action = policy(packet, 0)
        for step in range(60):
            if action is None:
                break
            packet = env.step(action)
            action = policy(packet, step + 1)
        saved = env.save_state()
        for _ in range(args.branch_chunks):
            env.restore_state(saved)
            for _step in range(HORIZON):
                base = packet["joint_position"] if action is None else action
                noise = torch.randn(JOINTS, generator=generator).tolist()
                env.step([value + 0.02 * delta for value, delta in zip(base, noise, strict=True)])
            count += 1
    total = time.perf_counter() - start
    return {
        "states": args.branch_states,
        "chunks_per_state": args.branch_chunks,
        "chunks": count,
        "total_seconds_including_setup_steps": total,
        "seconds_per_state_all_chunks": total / args.branch_states,
    }


def render(args: argparse.Namespace, _device: str, _out: Path) -> dict[str, Any]:
    """Real rendering through MoltenVK, for the visual path that the state data does not have."""
    env = ManiSkillPickCube(render=True)
    env.reset(3000)
    start = time.perf_counter()
    shape: Any = None
    for _ in range(args.render_frames):
        shape = env.render_rgb().shape
    total = time.perf_counter() - start
    return {
        "frames": args.render_frames,
        "frames_per_second": args.render_frames / total,
        "shape": list(shape),
    }


def encoder(args: argparse.Namespace, device: str, _out: Path) -> dict[str, Any]:
    """A ViT-S/14-shaped encoder with random weights, at 224 x 224, for images per second."""
    torch = _torch()
    nn = torch.nn
    torch.manual_seed(0)
    patch = nn.Conv2d(3, 384, kernel_size=14, stride=14).to(device)
    layer = nn.TransformerEncoderLayer(384, 6, 1536, batch_first=True, norm_first=True, dropout=0.0)
    body = nn.TransformerEncoder(layer, 12).to(device).eval()
    images = torch.rand(args.encoder_batch, 3, 224, 224, device=device)
    peak = _peak_tracker(device)
    times = []
    with torch.no_grad():
        for _ in range(args.encoder_batches):
            start = time.perf_counter()
            tokens = patch(images).flatten(2).transpose(1, 2)
            body(tokens).mean(1).sum().item()
            _sync(device)
            times.append(time.perf_counter() - start)
            peak()
    settled = statistics.median(times[1:])
    return {
        "weights": "MOCKED: random, so this measures the architecture's cost only",
        "batch": args.encoder_batch,
        "images_per_second": args.encoder_batch / settled,
        "parameters": sum(int(p.numel()) for p in patch.parameters())
        + sum(int(p.numel()) for p in body.parameters()),
        "metal_driver_peak_bytes": peak(),
    }


WORKLOADS: dict[str, Callable[[argparse.Namespace, str, Path], dict[str, Any]]] = {
    "predictor": predictor,
    "latent": latent,
    "scorer": scorer,
    "planner": planner,
    "closed_loop": closed_loop,
    "branches": branches,
    "render": render,
    "encoder": encoder,
}

# The predictor on MPS comes first, because the planner workloads load its weights.
PLAN = (
    ("predictor", "mps"),
    ("predictor", "cpu"),
    ("latent", "mps"),
    ("latent", "cpu"),
    ("scorer", "mps"),
    ("scorer", "cpu"),
    ("planner", "mps"),
    ("planner", "cpu"),
    ("closed_loop", "mps"),
    ("closed_loop", "cpu"),
    ("branches", "cpu"),
    ("render", "cpu"),
    ("encoder", "mps"),
    ("encoder", "cpu"),
)


def _parse_time_output(text: str) -> dict[str, int]:
    """The peak figures that macOS ``/usr/bin/time -l`` prints, in bytes."""
    found: dict[str, int] = {}
    for key, label in (
        ("peak_footprint_bytes", "peak memory footprint"),
        ("max_rss_bytes", "maximum resident set size"),
    ):
        match = re.search(rf"(\d+)\s+{label}", text)
        if match is None:
            raise ValueError(f"/usr/bin/time did not report {label}")
        found[key] = int(match.group(1))
    return found


def _child_arguments(args: argparse.Namespace) -> list[str]:
    arguments = ["--manifest", str(args.manifest)]
    for name in OPTION_DEFAULTS:
        arguments += [f"--{name.replace('_', '-')}", str(getattr(args, name))]
    return arguments


def _run_child(args: argparse.Namespace, workload: str, device: str, out: Path) -> dict[str, Any]:
    result_path = out / f"{workload}-{device}.json"
    command = [
        "/usr/bin/time",
        "-l",
        sys.executable,
        "-m",
        "vishwaroop.models.compute_pilot",
        *_child_arguments(args),
        "--child",
        workload,
        "--device",
        device,
        "--out",
        str(out),
    ]
    before = os.getloadavg()[0]
    start = time.perf_counter()
    finished = subprocess.run(
        command, capture_output=True, text=True, timeout=CHILD_TIMEOUT_S, check=False
    )
    elapsed = time.perf_counter() - start
    if finished.returncode != 0:
        raise RuntimeError(f"{workload} on {device} failed: {finished.stderr[-2000:]}")
    measured: dict[str, Any] = json.loads(result_path.read_text(encoding="utf-8"))
    return {
        **measured,
        **_parse_time_output(finished.stderr),
        "wall_seconds": elapsed,
        "load_average_before": before,
        "load_average_after": os.getloadavg()[0],
    }


OPTION_DEFAULTS = {
    "predictor_epochs": 30,
    "latent_epochs": 5,
    "scorer_epochs": 5,
    "planner_decisions": 21,
    "closed_loop_episodes": 2,
    "closed_loop_steps": 185,
    "branch_states": 50,
    "branch_chunks": 4,
    "render_frames": 200,
    "encoder_batch": 32,
    "encoder_batches": 11,
}


def _machine() -> dict[str, Any]:
    torch = _torch()
    chip = subprocess.run(
        [
            "/usr/sbin/sysctl",
            "-n",
            "machdep.cpu.brand_string",
            "hw.memsize",
            "hw.perflevel0.physicalcpu",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\n")
    return {
        "chip": chip[0],
        "memory_bytes": int(chip[1]),
        "performance_cores": int(chip[2]),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "torch": str(torch.__version__),
        "mps_available": bool(torch.backends.mps.is_available()),
        "torch_threads": int(torch.get_num_threads()),
    }


def _parent(args: argparse.Namespace) -> int:
    require_code_root()
    machine = _machine()
    if not machine["mps_available"]:
        raise ValueError("MPS is not available, so this pilot would not measure the question")
    only = set(args.only.split(",")) if args.only else None
    with ledgered_run(
        purpose="WO-012: can the M1 models train on this Mac; timing and memory only",
        config={"manifest": str(args.manifest), **{n: getattr(args, n) for n in OPTION_DEFAULTS}},
        seeds={"torch": 0},
        env_lock={"machine": machine},
    ) as run:
        results: dict[str, Any] = {}
        for workload, device in PLAN:
            if only is not None and not {workload, f"{workload}-{device}"} & only:
                continue
            print(f"{workload} on {device}", file=sys.stderr, flush=True)
            results[f"{workload}-{device}"] = _run_child(args, workload, device, run.directory)
        report = {
            "machine": machine,
            "run": run.directory.name,
            "code": run.code_note,
            "results": results,
        }
        with (run.directory / "pilot.json").open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
        run.note = f"{len(results)} workloads"
        print(run.directory)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    for name, default in OPTION_DEFAULTS.items():
        parser.add_argument(f"--{name.replace('_', '-')}", type=int, default=default)
    parser.add_argument(
        "--only", default="", help="comma-separated workloads or workload-device pairs"
    )
    parser.add_argument("--child", choices=sorted(WORKLOADS))
    parser.add_argument("--device", choices=("mps", "cpu"), default="cpu")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.child is None:
        try:
            return _parent(args)
        except (ValueError, OSError) as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            print(f"failed: {exc}", file=sys.stderr)
            return 3
    result = WORKLOADS[args.child](args, args.device, args.out)
    (args.out / f"{args.child}-{args.device}.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
