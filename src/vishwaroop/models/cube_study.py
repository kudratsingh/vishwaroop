"""Why did the pilot not learn the cube? Train-only diagnosis for WO-014, not an exit-test result.

    python -m vishwaroop.models.cube_study --manifest artifacts/manifests/m0-dataset-v1.json

Run it from the repository root, in the robotics environment. Results go to ``cube_study.json`` in
a new run directory. Exit codes: 0 measured, 2 refused.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass
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
from .pilot_data import ACTION_SIZE, STATE_SIZE, load_train, split_holdout

CUBE_FIRST, CUBE_LAST = STREAM_SLICES["object_position"]
FLAG_FIRST, FLAG_LAST = STREAM_SLICES["object_grasped"]
CONTACT_SCALE_M = 0.05
CONTACT_SIZE = 3
EPOCHS = 30
SEEDS = (0, 1, 2)


@dataclass(frozen=True)
class Variant:
    """One model structure from the work order's table."""

    carry: bool
    contact: bool
    beta: float


VARIANTS = {
    "hold": Variant(carry=False, contact=False, beta=0.0),
    "hold-contact": Variant(carry=False, contact=True, beta=0.0),
    "carry": Variant(carry=True, contact=False, beta=0.0),
    "carry-contact": Variant(carry=True, contact=True, beta=0.0),
    "carry-contact-beta": Variant(carry=True, contact=True, beta=0.5),
}


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


def _step(
    stats: dict[str, Any],
    variant: Variant,
    layers: list[Any],
    history: Any,
    state: Any,
    action: Any,
    gate: Any = None,
) -> tuple[Any, Any]:
    """One step of nominal plus residual. A carried cube follows the joints after their residual."""
    torch = _torch()
    parts = [_normalized_pair(stats, state, action), history]
    tool = stats["kinematics"](state[..., :JOINTS]) if variant.carry or variant.contact else None
    if variant.contact:
        parts.append((state[..., CUBE_FIRST:CUBE_LAST] - tool) / CONTACT_SCALE_M)
    output = _ensemble_forward(layers, torch.cat(parts, dim=-1))
    residual, log_var = output[..., :STATE_SIZE], output[..., STATE_SIZE:]
    prediction = _nominal(stats, state, action) + residual * stats["delta_std"]
    if variant.carry:
        chosen = _gate_of(state) if gate is None else gate
        moved = stats["kinematics"](prediction[..., :JOINTS]) - tool
        prediction = _with_cube_moved(prediction, chosen * moved)
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
    means, log_vars = [], []
    for step in range(HORIZON):
        action = actions[..., HISTORY + step, :]
        gate = _gate_of(states[..., HISTORY + step, :]) if true_gate else None
        mean, log_var = _step(stats, variant, layers, history, state, action, gate)
        means.append(mean)
        log_vars.append(log_var)
        pair = _normalized_pair(stats, state, action)
        history = torch.cat([history[..., STATE_SIZE + ACTION_SIZE :], pair], dim=-1)
        state = mean
    return means, log_vars


def _train(
    data: _Data, stats: dict[str, Any], variant: Variant, seed: int, epochs: int
) -> tuple[list[Any], dict[str, Any]]:
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
    for _ in range(epochs):
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
    return layers, {
        "median_seconds_per_epoch": sorted(times)[len(times) // 2],
        "final_loss": losses[-1],
        "best_loss": min(losses),
    }


def _metrics(
    prediction: Any, truth: Any, scale: Any, mask_by_phase: dict[str, Any]
) -> dict[str, Any]:
    """Per-stream error in stream standard deviations, and the cube by phase in millimetres."""
    error = (prediction - truth) / scale
    streams = {
        name: [math.sqrt(error[:, h, a:b].pow(2).mean().item()) for h in range(HORIZON)]
        for name, (a, b) in STREAM_SLICES.items()
    }
    squared = (prediction - truth)[..., CUBE_FIRST:CUBE_LAST].pow(2).sum(-1)
    phases = {
        phase: [1000.0 * math.sqrt(squared[mask, h].mean().item()) for h in range(HORIZON)]
        for phase, mask in mask_by_phase.items()
        if bool(mask.any())
    }
    return {
        "streams_normalized": streams,
        "cube_mm_all": [1000.0 * math.sqrt(squared[:, h].mean().item()) for h in range(HORIZON)],
        "cube_mm_by_phase": phases,
        "share_of_cube_squared_error_at_h10": {
            phase: float(squared[mask, -1].sum().item() / max(squared[:, -1].sum().item(), 1e-30))
            for phase, mask in mask_by_phase.items()
        },
    }


def _baselines(
    data: _Data, stats: dict[str, Any], masks: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    torch = _torch()
    states, actions = data.holdout_s, data.holdout_a
    start = states[:, HISTORY]
    previous = states[:, HISTORY - 1]
    truth = states[:, HISTORY + 1 : HISTORY + 1 + HORIZON]
    held: list[Any] = []
    carrying: list[Any] = []
    true_gate: list[Any] = []
    hold_state = carry_state = oracle_state = start
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
    predictions = {
        "constant": start.unsqueeze(1).expand_as(truth),
        "linear": torch.stack([start + (start - previous) * (h + 1) for h in range(HORIZON)], 1),
        "nominal_hold": torch.stack(held, 1),
        "nominal_carry": torch.stack(carrying, 1),
        "nominal_carry_true_flag_diagnostic": torch.stack(true_gate, 1),
    }
    return {
        name: _metrics(value, truth, data.state_std, masks) for name, value in predictions.items()
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
        means, _ = _rollout(stats, variant, layers, states, actions, true_gate)
    return _metrics(torch.stack(means, 2).mean(0), truth, data.state_std, masks)


def _study(args: argparse.Namespace, machine: dict[str, Any]) -> dict[str, Any]:
    torch = _torch()
    episodes = load_train(args.manifest, Path())
    _, holdout = split_holdout(episodes)
    data = _Data(args.manifest, args.device)
    stats = {**_stats_of(data), "kinematics": _Kinematics(args.device)}
    phases = [
        phase for item in holdout for phase in episode_window_phases(item.states, HISTORY, HORIZON)
    ]
    if len(phases) != len(data.holdout_s):
        raise ValueError("phase labels do not line up with the holdout windows")
    masks = {
        phase: torch.tensor([item == phase for item in phases], device=args.device)
        for phase in WINDOW_PHASES
    }
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
    parser.add_argument("--variants", default=",".join(VARIANTS))
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
            run.note = f"{args.variants} on seeds {args.seeds}, {args.epochs} epochs"
            print(run.directory)
    except (ValueError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
