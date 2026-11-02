"""Why did the pilot not learn the cube? Train-only diagnosis for WO-014, not an exit-test result.

    python -m vishwaroop.models.cube_study --manifest artifacts/manifests/m0-dataset-v1.json

Run it from the repository root, in the robotics environment. Results go to ``cube_study.json`` in
a new run directory. Exit codes: 0 measured, 2 refused.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from ..sim.runlog import ledgered_run, require_code_root
from ..sim.so100_kinematics import (
    _CHAIN,
    _FIXED_TIP,
    _GRIPPER_ORIGIN,
    _MOVING_TIP,
    BASE_POSITION,
    BASE_YAW,
    _rotation,
    tool_point,
)
from .compute_pilot import (
    BATCH,
    HIDDEN,
    HISTORY,
    HORIZON,
    JOINTS,
    MEMBERS,
    STREAM_SLICES,
    _Data,
    _ensemble_forward,
    _forward_kinematics,
    _machine,
    _new_ensemble,
    _nominal,
    _normalized_pair,
    _rollout_history,
    _stats_of,
    _torch,
)
from .cube_phases import WINDOW_PHASES, episode_window_phases, step_table
from .pilot_data import ACTION_SIZE, STATE_SIZE, load_train, split_family, split_holdout

CUBE_FIRST, CUBE_LAST = STREAM_SLICES["object_position"]
FLAG_FIRST, FLAG_LAST = STREAM_SLICES["object_grasped"]
CONTACT_SCALE_M = 0.05
CONTACT_SIZE = 3
REST_HEIGHT_M = 0.0125  # evals/M0-protocol.md
AIRBORNE_MARGIN_M = 0.001
CONTROL_PERIOD_S = 0.05
GRAVITY_M_S2 = 9.81
FALL_PER_STEP_M = GRAVITY_M_S2 * CONTROL_PERIOD_S * CONTROL_PERIOD_S
GRASP_REACH_M = 0.015  # evals/M1-followups-v2.json: train data never holds a cube beyond 11.83 mm
EPOCHS = 30
SEEDS = (0, 1, 2)


@dataclass(frozen=True)
class Variant:
    """One model structure from the work order's table."""

    carry: bool
    contact: bool
    beta: float
    fall: bool = False
    still: bool = False
    reach: bool = False
    onset_reach: bool = False
    nominal_only: bool = False


VARIANTS = {
    "hold": Variant(carry=False, contact=False, beta=0.0),
    "hold-contact": Variant(carry=False, contact=True, beta=0.0),
    "carry": Variant(carry=True, contact=False, beta=0.0),
    "carry-contact": Variant(carry=True, contact=True, beta=0.0),
    "carry-contact-beta": Variant(carry=True, contact=True, beta=0.5),
    "hold-beta": Variant(carry=False, contact=False, beta=0.5),
    "carry-beta": Variant(carry=True, contact=False, beta=0.5),
    "carry-beta-fall": Variant(carry=True, contact=False, beta=0.5, fall=True),
    "carry-contact-beta-fall": Variant(carry=True, contact=True, beta=0.5, fall=True),
    "carry-contact-beta-fall-still": Variant(
        carry=True, contact=True, beta=0.5, fall=True, still=True
    ),
    "carry-contact-beta-fall-still-reach": Variant(
        carry=True, contact=True, beta=0.5, fall=True, still=True, reach=True
    ),
    "carry-contact-beta-fall-still-onset": Variant(
        carry=True, contact=True, beta=0.5, fall=True, still=True, onset_reach=True
    ),
    "nominal-still-reach": Variant(
        carry=True, contact=True, beta=0.5, fall=True, still=True, reach=True, nominal_only=True
    ),
}
FROZEN_VARIANTS = ("hold", "hold-contact", "carry", "carry-contact", "carry-contact-beta")
Z_90 = 1.6449
CALIBRATED_STREAMS = ("joint_position", "object_position")


class _Kinematics:
    """The tool point for batches of joints, with the fixed transforms computed once.

    ``_forward_kinematics`` rebuilds them on every call, which made a carrying model about ten
    times slower to train. ``largest_gap_m`` compares this with it.
    """

    def __init__(self, device: str) -> None:
        torch = _torch()

        def matrix(rpy: tuple[float, float, float]) -> Any:
            return torch.tensor(_rotation(rpy), dtype=torch.float32, device=device)

        def vector(value: tuple[float, float, float]) -> Any:
            return torch.tensor(value, dtype=torch.float32, device=device)

        self.base_position = vector(BASE_POSITION)
        self.base_frame = matrix((0.0, 0.0, BASE_YAW))
        self.links = [
            (vector(origin), matrix(rpy), axis, float(sign)) for origin, rpy, (axis, sign) in _CHAIN
        ]
        self.fixed_tip = vector(_FIXED_TIP)
        self.moving_tip = vector(_MOVING_TIP)
        self.gripper_origin = vector(_GRIPPER_ORIGIN[0])
        self.gripper_rotation = matrix(_GRIPPER_ORIGIN[1])

    @staticmethod
    def _axis(axis: int, angle: Any) -> Any:
        torch = _torch()
        cosine, sine = torch.cos(angle), torch.sin(angle)
        zero, one = torch.zeros_like(angle), torch.ones_like(angle)
        rows = {
            0: (one, zero, zero, zero, cosine, -sine, zero, sine, cosine),
            1: (cosine, zero, sine, zero, one, zero, -sine, zero, cosine),
            2: (cosine, -sine, zero, sine, cosine, zero, zero, zero, one),
        }[axis]
        return torch.stack(rows, dim=-1).reshape(*angle.shape, 3, 3)

    def __call__(self, joints: Any) -> Any:
        position = self.base_position.expand(*joints.shape[:-1], 3)
        frame = self.base_frame.expand(*joints.shape[:-1], 3, 3)
        for index, (origin, rotation, axis, sign) in enumerate(self.links):
            position = position + frame @ origin
            frame = frame @ rotation @ self._axis(axis, sign * joints[..., index])
        fixed_tip = position + frame @ self.fixed_tip
        moving_position = position + frame @ self.gripper_origin
        moving_frame = frame @ self.gripper_rotation @ self._axis(2, joints[..., 5])
        return (fixed_tip + moving_position + moving_frame @ self.moving_tip) / 2


def largest_gap_m(device: str) -> float:
    """How far ``_Kinematics`` is from the pure-Python model and from ``_forward_kinematics``."""
    torch = _torch()
    kinematics = _Kinematics(device)
    worst = 0.0
    for joints in ([0.0, 0.4, 0.2, 1.0, 1.57, -0.8], [-0.3, 0.1, -0.5, 0.7, 0.2, 0.3], [0.5] * 6):
        batch = torch.tensor(joints, dtype=torch.float32, device=device)
        point = kinematics(batch)
        worst = max(worst, math.dist(point.tolist(), tool_point(joints)))
        worst = max(worst, math.dist(point.tolist(), _forward_kinematics(batch).tolist()))
    if worst > 1e-4:
        raise ValueError(f"batched kinematics differs by {worst} m")
    return worst


def _gate_of(state: Any) -> Any:
    return state[..., FLAG_FIRST:FLAG_LAST].clamp(0.0, 1.0)


def _with_cube_moved(prediction: Any, displacement: Any) -> Any:
    return _torch().cat(
        [
            prediction[..., :CUBE_FIRST],
            prediction[..., CUBE_FIRST:CUBE_LAST] + displacement,
            prediction[..., CUBE_LAST:],
        ],
        dim=-1,
    )


def fall_displacement(state: Any, previous: Any, gate: Any) -> Any:
    """Where a released, airborne cube goes next: its last step, plus gravity, down to the table."""
    torch = _torch()
    cube = state[..., CUBE_FIRST:CUBE_LAST]
    last = cube - previous[..., CUBE_FIRST:CUBE_LAST]
    height = cube[..., 2:] - REST_HEIGHT_M
    airborne = (height > AIRBORNE_MARGIN_M).to(cube.dtype)
    down = torch.maximum(last[..., 2:] - FALL_PER_STEP_M, -height)
    return (1.0 - gate) * airborne * torch.cat([last[..., :2], down], dim=-1)


def within_reach(gate: Any, state: Any, tool: Any) -> Any:
    """The grasp gate, or 0 where the tool point is beyond reach of the cube."""
    distance = (state[..., CUBE_FIRST:CUBE_LAST] - tool).norm(dim=-1, keepdim=True)
    return gate * (distance <= GRASP_REACH_M).to(gate.dtype)


def grasp_starts_within_reach(prediction: Any, gate: Any, kinematics: Any) -> Any:
    """A grasp may start only within reach; once started, it holds at any distance.

    Where the cube is not held now and the step predicts it held next, but the predicted tool
    point is beyond reach, the predicted flag is set to 0, so the next step treats the cube as
    free. Dev-informed (WO-005, owner, 2026-11-02).
    """
    torch = _torch()
    flag = prediction[..., FLAG_FIRST:FLAG_LAST]
    tool = kinematics(prediction[..., :JOINTS])
    far = (prediction[..., CUBE_FIRST:CUBE_LAST] - tool).norm(dim=-1, keepdim=True) > GRASP_REACH_M
    refused = (gate < 0.5) & (flag >= 0.5) & far
    return torch.cat(
        [
            prediction[..., :FLAG_FIRST],
            torch.where(refused, torch.zeros_like(flag), flag),
            prediction[..., FLAG_LAST:],
        ],
        dim=-1,
    )


def hold_free_cube(prediction: Any, state: Any, gate: Any) -> Any:
    """A cube that is neither held nor in the air stays exactly where it is (WO-005, owner).

    Held means a gate of at least 0.5. Everything else the step predicted for the cube is dropped,
    so in those states the cube matches the stays-put baseline step for step.
    """
    cube = state[..., CUBE_FIRST:CUBE_LAST]
    airborne = cube[..., 2:] - REST_HEIGHT_M > AIRBORNE_MARGIN_M
    free = ((gate < 0.5) & ~airborne).to(cube.dtype)
    return _with_cube_moved(prediction, free * (cube - prediction[..., CUBE_FIRST:CUBE_LAST]))


def _step(
    stats: dict[str, Any],
    variant: Variant,
    layers: list[Any],
    history: Any,
    state: Any,
    action: Any,
    gate: Any = None,
    previous: Any = None,
) -> tuple[Any, Any]:
    """One step of nominal plus residual. A carried cube follows the joints after their residual."""
    torch = _torch()
    parts = [_normalized_pair(stats, state, action), history]
    tool = stats["kinematics"](state[..., :JOINTS]) if variant.carry or variant.contact else None
    if variant.contact:
        parts.append((state[..., CUBE_FIRST:CUBE_LAST] - tool) / CONTACT_SCALE_M)
    output = _ensemble_forward(layers, torch.cat(parts, dim=-1))
    if variant.nominal_only:
        output = torch.zeros_like(output)
    residual, log_var = output[..., :STATE_SIZE], output[..., STATE_SIZE:]
    prediction = _nominal(stats, state, action) + residual * stats["delta_std"]
    chosen = _gate_of(state) if gate is None else gate
    if variant.reach:
        chosen = within_reach(chosen, state, tool)
    if variant.carry:
        moved = stats["kinematics"](prediction[..., :JOINTS]) - tool
        prediction = _with_cube_moved(prediction, chosen * moved)
    if variant.fall:
        prediction = _with_cube_moved(prediction, fall_displacement(state, previous, chosen))
    if variant.still:
        prediction = hold_free_cube(prediction, state, chosen)
    if variant.onset_reach:
        prediction = grasp_starts_within_reach(prediction, chosen, stats["kinematics"])
    return prediction, log_var.clamp(-10.0, 4.0)


def _rollout(
    stats: dict[str, Any],
    variant: Variant,
    layers: list[Any],
    states: Any,
    actions: Any,
    true_gate: bool = False,
) -> tuple[list[Any], list[Any]]:
    """Steps 1 to ``HORIZON``, feeding predictions back. ``true_gate`` is for diagnosis only."""
    torch = _torch()
    history = _rollout_history(stats, states, actions)
    state = states[..., HISTORY, :]
    previous = states[..., HISTORY - 1, :]
    means, log_vars = [], []
    for step in range(HORIZON):
        action = actions[..., HISTORY + step, :]
        gate = _gate_of(states[..., HISTORY + step, :]) if true_gate else None
        mean, log_var = _step(stats, variant, layers, history, state, action, gate, previous)
        means.append(mean)
        log_vars.append(log_var)
        pair = _normalized_pair(stats, state, action)
        history = torch.cat([history[..., STATE_SIZE + ACTION_SIZE :], pair], dim=-1)
        previous, state = state, mean
    return means, log_vars


def _save_checkpoint(
    path: Path,
    layers: list[Any],
    optimizer: Any,
    epoch: int,
    times: list[float],
    losses: list[float],
) -> None:
    """Replace the checkpoint in one step, so a crash leaves the last complete epoch."""
    torch = _torch()
    partial_file = path.with_suffix(".partial")
    torch.save(
        {
            "epoch": epoch,
            "layers": [[item.detach().cpu() for item in layer] for layer in layers],
            "optimizer": optimizer.state_dict(),
            "rng": torch.get_rng_state(),
            "times": times,
            "losses": losses,
        },
        partial_file,
    )
    os.replace(partial_file, path)


def _train(
    data: _Data,
    stats: dict[str, Any],
    variant: Variant,
    seed: int,
    epochs: int,
    checkpoint: Path | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    """Train one ensemble. With ``checkpoint``, every epoch is saved and a saved run continues."""
    torch = _torch()
    torch.manual_seed(seed)
    pair = STATE_SIZE + ACTION_SIZE
    inputs = pair + HISTORY * pair + (CONTACT_SIZE if variant.contact else 0)
    device = data.device
    layers = [
        (w.to(device).detach().requires_grad_(), b.to(device).detach().requires_grad_())
        for w, b in _new_ensemble([inputs, HIDDEN, HIDDEN, HIDDEN, 2 * STATE_SIZE])
    ]
    parameters = [item for layer in layers for item in layer]
    optimizer = torch.optim.Adam(parameters, lr=1e-3)
    count = len(data.windows_s)
    times: list[float] = []
    losses: list[float] = []
    first_epoch = 0
    if checkpoint is not None and checkpoint.exists():
        saved = torch.load(checkpoint, map_location="cpu", weights_only=True)
        with torch.no_grad():
            for layer, stored in zip(layers, saved["layers"], strict=True):
                for item, value in zip(layer, stored, strict=True):
                    item.copy_(value.to(device))
        optimizer.load_state_dict(saved["optimizer"])
        torch.set_rng_state(saved["rng"])
        first_epoch = saved["epoch"]
        times, losses = list(saved["times"]), list(saved["losses"])
    for epoch in range(first_epoch, epochs):
        start = time.perf_counter()
        order = torch.stack([torch.randperm(count) for _ in range(MEMBERS)], dim=0).to(device)
        total = 0.0
        batches = 0
        for first in range(0, count - BATCH + 1, BATCH):
            index = order[:, first : first + BATCH]
            states = data.windows_s[index]
            means, log_vars = _rollout(stats, variant, layers, states, data.windows_a[index])
            loss: Any = 0.0
            for h, (mean, log_var) in enumerate(zip(means, log_vars, strict=True)):
                error = (mean - states[:, :, HISTORY + 1 + h]) / data.delta_std
                term = error.pow(2) * torch.exp(-log_var) + log_var
                if variant.beta:
                    term = term * torch.exp(variant.beta * log_var.detach())
                loss = loss + term.mean()
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(parameters, 100.0)
            optimizer.step()
            total += float(loss.item()) / HORIZON
            batches += 1
        times.append(time.perf_counter() - start)
        losses.append(total / batches)
        if not math.isfinite(losses[-1]):
            raise ValueError(f"loss became {losses[-1]}")
        if checkpoint is not None:
            _save_checkpoint(checkpoint, layers, optimizer, epoch + 1, times, losses)
    return layers, {
        "resumed_at_epoch": first_epoch,
        "median_seconds_per_epoch": sorted(times)[len(times) // 2],
        "final_loss": losses[-1],
        "best_loss": min(losses),
    }


def _metrics(
    prediction: Any, truth: Any, scale: Any, mask_by_phase: dict[str, Any]
) -> dict[str, Any]:
    """Per-stream error in standard deviations and own units, and the cube by phase in mm."""
    raw = prediction - truth
    error = raw / scale
    streams = {
        name: [math.sqrt(error[:, h, a:b].pow(2).mean().item()) for h in range(HORIZON)]
        for name, (a, b) in STREAM_SLICES.items()
    }
    own_units = {
        name: [math.sqrt(raw[:, h, a:b].pow(2).mean().item()) for h in range(HORIZON)]
        for name, (a, b) in STREAM_SLICES.items()
    }
    squared = raw[..., CUBE_FIRST:CUBE_LAST].pow(2).sum(-1)
    phases = {
        phase: [1000.0 * math.sqrt(squared[mask, h].mean().item()) for h in range(HORIZON)]
        for phase, mask in mask_by_phase.items()
        if bool(mask.any())
    }
    return {
        "streams_normalized": streams,
        "streams_own_units": own_units,
        "joint_rad_by_joint": [
            [math.sqrt(raw[:, h, joint].pow(2).mean().item()) for h in range(HORIZON)]
            for joint in range(JOINTS)
        ],
        "cube_mm_all": [1000.0 * math.sqrt(squared[:, h].mean().item()) for h in range(HORIZON)],
        "cube_mm_by_phase": phases,
        "share_of_cube_squared_error_at_h10": {
            phase: float(squared[mask, -1].sum().item() / max(squared[:, -1].sum().item(), 1e-30))
            for phase, mask in mask_by_phase.items()
        },
    }


def _spearman(a: Any, b: Any) -> float:
    torch = _torch()

    def ranks(values: Any) -> Any:
        order = values.argsort()
        result = torch.empty_like(values)
        result[order] = torch.arange(len(values), dtype=values.dtype)
        return result

    x, y = ranks(a), ranks(b)
    x, y = x - x.mean(), y - y.mean()
    return float((x * y).sum().item() / (x.norm() * y.norm()).item())


def _uncertainty(means: Any, log_vars: Any, truth: Any, delta_std: Any) -> dict[str, Any]:
    """A first look at what ET-M1-3 will ask, on this holdout. Its streams are not frozen yet."""
    torch = _torch()
    mean = means.mean(0)
    variance = (torch.exp(log_vars) * delta_std.pow(2)).mean(0) + means.var(0, unbiased=False)
    std = variance.sqrt().cpu().double()
    error = (mean - truth).abs().cpu().double()
    result = {}
    for name in CALIBRATED_STREAMS:
        a, b = STREAM_SLICES[name]
        s, e = std[..., a:b].flatten(), error[..., a:b].flatten()
        result[name] = {
            "spearman_std_vs_abs_error": _spearman(s, e),
            "coverage_of_90_percent_interval": float((e <= Z_90 * s).double().mean().item()),
        }
    return result


def _baseline_predictions(data: _Data, stats: dict[str, Any]) -> dict[str, Any]:
    """Every baseline's prediction for each window in ``data.holdout_s``."""
    torch = _torch()
    states, actions = data.holdout_s, data.holdout_a
    start = states[:, HISTORY]
    previous = states[:, HISTORY - 1]
    truth = states[:, HISTORY + 1 : HISTORY + 1 + HORIZON]
    held: list[Any] = []
    carrying: list[Any] = []
    true_gate: list[Any] = []
    falling: list[Any] = []
    falling_true_gate: list[Any] = []
    hold_state = carry_state = oracle_state = fall_state = fall_oracle_state = start
    fall_previous = fall_oracle_previous = previous
    kinematics = stats["kinematics"]

    def carried(state: Any, action: Any, gate: Any) -> Any:
        following = _nominal(stats, state, action)
        moved = kinematics(following[..., :JOINTS]) - kinematics(state[..., :JOINTS])
        return _with_cube_moved(following, gate * moved)

    for h in range(HORIZON):
        action = actions[:, HISTORY + h]
        hold_state = _nominal(stats, hold_state, action)
        carry_state = carried(carry_state, action, _gate_of(carry_state))
        oracle_state = carried(oracle_state, action, _gate_of(states[:, HISTORY + h]))
        held.append(hold_state)
        carrying.append(carry_state)
        true_gate.append(oracle_state)
        gate = _gate_of(fall_state)
        moved_state = _with_cube_moved(
            carried(fall_state, action, gate), fall_displacement(fall_state, fall_previous, gate)
        )
        fall_previous, fall_state = fall_state, moved_state
        falling.append(fall_state)
        gate = _gate_of(states[:, HISTORY + h])
        moved_state = _with_cube_moved(
            carried(fall_oracle_state, action, gate),
            fall_displacement(fall_oracle_state, fall_oracle_previous, gate),
        )
        fall_oracle_previous, fall_oracle_state = fall_oracle_state, moved_state
        falling_true_gate.append(fall_oracle_state)
    return {
        "constant": start.unsqueeze(1).expand_as(truth),
        "linear": torch.stack([start + (start - previous) * (h + 1) for h in range(HORIZON)], 1),
        "nominal_hold": torch.stack(held, 1),
        "nominal_carry": torch.stack(carrying, 1),
        "nominal_carry_true_flag_diagnostic": torch.stack(true_gate, 1),
        "nominal_carry_fall": torch.stack(falling, 1),
        "nominal_carry_fall_true_flag_diagnostic": torch.stack(falling_true_gate, 1),
    }


def _baselines(
    data: _Data, stats: dict[str, Any], masks: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    truth = data.holdout_s[:, HISTORY + 1 : HISTORY + 1 + HORIZON]
    return {
        name: _metrics(value, truth, data.state_std, masks)
        for name, value in _baseline_predictions(data, stats).items()
    }


def _evaluate(
    data: _Data,
    stats: dict[str, Any],
    variant: Variant,
    layers: list[Any],
    masks: dict[str, Any],
    true_gate: bool,
) -> dict[str, Any]:
    torch = _torch()
    states = data.holdout_s.unsqueeze(0).expand(MEMBERS, -1, -1, -1)
    actions = data.holdout_a.unsqueeze(0).expand(MEMBERS, -1, -1, -1)
    truth = data.holdout_s[:, HISTORY + 1 : HISTORY + 1 + HORIZON]
    with torch.no_grad():
        means, log_vars = _rollout(stats, variant, layers, states, actions, true_gate)
    stacked = torch.stack(means, 2)
    return {
        **_metrics(stacked.mean(0), truth, data.state_std, masks),
        "uncertainty_first_look": _uncertainty(
            stacked, torch.stack(log_vars, 2), truth, data.delta_std
        ),
    }


def phase_masks(holdout: Sequence[Any], count: int, device: str) -> dict[str, Any]:
    """One boolean mask per window phase, checked against the number of holdout windows."""
    torch = _torch()
    phases = [
        phase for item in holdout for phase in episode_window_phases(item.states, HISTORY, HORIZON)
    ]
    if len(phases) != count:
        raise ValueError("phase labels do not line up with the holdout windows")
    return {
        phase: torch.tensor([item == phase for item in phases], device=device)
        for phase in WINDOW_PHASES
    }


def _study(args: argparse.Namespace, machine: dict[str, Any]) -> dict[str, Any]:
    episodes = load_train(args.manifest, Path())
    split: Callable[[Any], tuple[list[Any], list[Any]]] = split_holdout
    if args.holdout_family:
        split = partial(split_family, family=args.holdout_family)
    _, holdout = split(episodes)
    data = _Data(args.manifest, args.device, split)
    stats = {**_stats_of(data), "kinematics": _Kinematics(args.device)}
    masks = phase_masks(holdout, len(data.holdout_s), args.device)
    cells: dict[str, dict[str, Any]] = {}
    for name in args.variants.split(","):
        variant = VARIANTS[name]
        cells[name] = {}
        for seed in (int(item) for item in args.seeds.split(",")):
            print(f"{name} seed {seed}", file=sys.stderr, flush=True)
            started = time.perf_counter()
            layers, training = _train(data, stats, variant, seed, args.epochs)
            cell = {
                "training": training,
                "seconds": time.perf_counter() - started,
                "predicted_flag": _evaluate(data, stats, variant, layers, masks, False),
            }
            if variant.carry:
                cell["true_flag_diagnostic"] = _evaluate(data, stats, variant, layers, masks, True)
            cells[name][str(seed)] = cell
    return {
        "machine": machine,
        "epochs": args.epochs,
        "holdout_family": args.holdout_family or None,
        "kinematics_gap_m": largest_gap_m(args.device),
        "fit_episodes": data.fit_episodes,
        "holdout_episodes": data.holdout_episodes,
        "windows_per_epoch": len(data.windows_s),
        "holdout_windows": {phase: int(mask.sum().item()) for phase, mask in masks.items()},
        "step_table_all_train": step_table(item.states for item in episodes),
        "baselines": _baselines(data, stats, masks),
        "variants": cells,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    parser.add_argument("--seeds", default=",".join(str(seed) for seed in SEEDS))
    parser.add_argument("--variants", default=",".join(FROZEN_VARIANTS))
    parser.add_argument(
        "--holdout-family", default="", help="hold out this whole train family, not the seed split"
    )
    parser.add_argument("--device", choices=("mps", "cpu"), default="mps")
    args = parser.parse_args(argv)
    try:
        require_code_root()
        unknown = set(args.variants.split(",")) - set(VARIANTS)
        if unknown:
            raise ValueError(f"unknown variants: {sorted(unknown)}")
        machine = _machine()
        with ledgered_run(
            purpose="WO-014: why the pilot did not learn the cube; train data, not an exit test",
            config={
                "manifest": str(args.manifest),
                "epochs": args.epochs,
                "variants": args.variants,
                "device": args.device,
                "holdout_family": args.holdout_family,
            },
            seeds={"torch": 0},
            env_lock={"machine": machine},
        ) as run:
            report = {
                "run": run.directory.name,
                "code": run.code_note,
                "seeds": args.seeds,
                **_study(args, machine),
            }
            with (run.directory / "cube_study.json").open("x", encoding="utf-8") as stream:
                json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
                stream.write("\n")
            run.note = (
                f"{args.variants} on seeds {args.seeds}, {args.epochs} epochs,"
                f" holdout {args.holdout_family or 'by seed'}"
            )
            print(run.directory)
    except (ValueError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
