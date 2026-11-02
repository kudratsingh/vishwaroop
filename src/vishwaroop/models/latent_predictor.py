"""A compact recurrent latent predictor on state observations, for WO-004. Train data only.

    python -m vishwaroop.models.latent_predictor --manifest artifacts/manifests/m0-dataset-v1.json

Observation-update mode folds the window's first states into the latent state. Imagination mode then
rolls forward from actions alone. The latent state only supplies the residual: the frozen nominal
structure (lag, carry, fall) stays underneath, as in the ensemble. Each epoch is saved, and
``--resume-from runs/<id>`` continues a stopped run from its last one. Exit codes: 0 measured,
2 refused.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

from ..sim.runlog import Run, ledgered_run, require_code_root
from .compute_pilot import (
    BATCH,
    HIDDEN,
    HISTORY,
    HORIZON,
    JOINTS,
    STREAM_SLICES,
    _Data,
    _machine,
    _nominal,
    _normalized_pair,
    _stats_of,
    _torch,
)
from .cube_study import (
    CONTACT_SCALE_M,
    CONTACT_SIZE,
    CUBE_FIRST,
    CUBE_LAST,
    EPOCHS,
    SEEDS,
    _gate_of,
    _Kinematics,
    _metrics,
    _with_cube_moved,
    fall_displacement,
    phase_masks,
)
from .family_sweep import PLAN_FILE, _code_changed, _write_new, check_resume
from .pilot_data import ACTION_SIZE, STATE_SIZE, load_train, split_holdout

STOCHASTIC = 32
KL_WEIGHT = 0.1
BETA = 0.5
LEARNING_RATE = 1e-3
LATENT_HIDDEN = 128
CHECKPOINT = "checkpoint.pt"
RESULT = "result.json"


def new_modules(device: str) -> Any:
    """Encoder, recurrent cell, prior, posterior and residual decoder."""
    nn = _torch().nn
    return nn.ModuleDict(
        {
            "encoder": nn.Sequential(
                nn.Linear(STATE_SIZE + CONTACT_SIZE, HIDDEN),
                nn.SiLU(),
                nn.Linear(HIDDEN, LATENT_HIDDEN),
            ),
            "cell": nn.GRUCell(STOCHASTIC + ACTION_SIZE, LATENT_HIDDEN),
            "prior": nn.Linear(LATENT_HIDDEN, 2 * STOCHASTIC),
            "posterior": nn.Linear(2 * LATENT_HIDDEN, 2 * STOCHASTIC),
            "decoder": nn.Sequential(
                nn.Linear(LATENT_HIDDEN + STOCHASTIC + STATE_SIZE + ACTION_SIZE, HIDDEN),
                nn.SiLU(),
                nn.Linear(HIDDEN, 2 * STATE_SIZE),
            ),
        }
    ).to(device)


def _encoded(modules: Any, stats: dict[str, Any], state: Any) -> Any:
    torch = _torch()
    tool = stats["kinematics"](state[..., :JOINTS])
    contact = (state[..., CUBE_FIRST:CUBE_LAST] - tool) / CONTACT_SCALE_M
    normalized = (state - stats["state_mean"]) / stats["state_std"]
    return modules["encoder"](torch.cat([normalized, contact], dim=-1))


def _split(parameters: Any) -> tuple[Any, Any]:
    mean, log_std = parameters.chunk(2, dim=-1)
    return mean, log_std.clamp(-5.0, 2.0)


def observe(modules: Any, stats: dict[str, Any], states: Any, actions: Any) -> tuple[Any, Any, Any]:
    """Observation-update mode, up to and including the state at index ``HISTORY``."""
    torch = _torch()
    count = states.shape[0]
    device = states.device
    hidden = torch.zeros(count, LATENT_HIDDEN, device=device)
    latent = torch.zeros(count, STOCHASTIC, device=device)
    kl: Any = 0.0
    scaled = (actions - stats["action_mean"]) / stats["action_std"]
    for step in range(HISTORY):
        hidden = modules["cell"](torch.cat([latent, scaled[:, step]], dim=-1), hidden)
        prior_mean, prior_log_std = _split(modules["prior"](hidden))
        embedded = _encoded(modules, stats, states[:, step + 1])
        mean, log_std = _split(modules["posterior"](torch.cat([hidden, embedded], dim=-1)))
        kl = (
            kl
            + (
                prior_log_std
                - log_std
                + (log_std.exp().pow(2) + (mean - prior_mean).pow(2))
                / (2 * prior_log_std.exp().pow(2))
                - 0.5
            )
            .sum(-1)
            .mean()
        )
        latent = mean + torch.randn_like(mean) * log_std.exp() if modules.training else mean
    return hidden, latent, kl


def imagine(
    modules: Any, stats: dict[str, Any], hidden: Any, latent: Any, states: Any, actions: Any
) -> tuple[Any, Any]:
    """Imagination mode: steps 1 to ``HORIZON``, from actions alone, feeding predictions back."""
    torch = _torch()
    state = states[:, HISTORY]
    previous = states[:, HISTORY - 1]
    means, log_vars = [], []
    kinematics = stats["kinematics"]
    for step in range(HORIZON):
        action = actions[:, HISTORY + step]
        pair = _normalized_pair(stats, state, action)
        output = modules["decoder"](torch.cat([hidden, latent, pair], dim=-1))
        residual, log_var = output[..., :STATE_SIZE], output[..., STATE_SIZE:]
        tool = kinematics(state[..., :JOINTS])
        following = _nominal(stats, state, action) + residual * stats["delta_std"]
        gate = _gate_of(state)
        following = _with_cube_moved(following, gate * (kinematics(following[..., :JOINTS]) - tool))
        following = _with_cube_moved(following, fall_displacement(state, previous, gate))
        means.append(following)
        log_vars.append(log_var.clamp(-10.0, 4.0))
        scaled = (action - stats["action_mean"]) / stats["action_std"]
        hidden = modules["cell"](torch.cat([latent, scaled], dim=-1), hidden)
        prior_mean, prior_log_std = _split(modules["prior"](hidden))
        latent = (
            prior_mean + torch.randn_like(prior_mean) * prior_log_std.exp()
            if modules.training
            else prior_mean
        )
        previous, state = state, following
    return torch.stack(means, 1), torch.stack(log_vars, 1)


def predict(modules: Any, stats: dict[str, Any], states: Any, actions: Any) -> tuple[Any, Any]:
    """Predicted means and log variances for a batch of windows."""
    hidden, latent, _ = observe(modules, stats, states, actions)
    return imagine(modules, stats, hidden, latent, states, actions)


def train(
    data: Any,
    stats: dict[str, Any],
    seed: int,
    epochs: int,
    checkpoint: Path | None = None,
    device: str = "mps",
) -> tuple[Any, dict[str, Any]]:
    """Train one model. With ``checkpoint``, every epoch is saved and a saved run continues."""
    torch = _torch()
    torch.manual_seed(seed)
    modules = new_modules(device)
    optimizer = torch.optim.Adam(modules.parameters(), lr=LEARNING_RATE)
    count = len(data.windows_s)
    times: list[float] = []
    losses: list[float] = []
    first_epoch = 0
    if checkpoint is not None and checkpoint.exists():
        saved = torch.load(checkpoint, map_location=device, weights_only=True)
        modules.load_state_dict(saved["modules"])
        optimizer.load_state_dict(saved["optimizer"])
        torch.set_rng_state(saved["rng"].cpu())
        first_epoch = saved["epoch"]
        times, losses = list(saved["times"]), list(saved["losses"])
    modules.train()
    for epoch in range(first_epoch, epochs):
        start = time.perf_counter()
        order = torch.randperm(count).to(device)
        total = 0.0
        batches = 0
        for first in range(0, count - BATCH + 1, BATCH):
            index = order[first : first + BATCH]
            states, actions = data.windows_s[index], data.windows_a[index]
            hidden, latent, kl = observe(modules, stats, states, actions)
            means, log_vars = imagine(modules, stats, hidden, latent, states, actions)
            error = (means - states[:, HISTORY + 1 :]) / data.delta_std
            terms = error.pow(2) * torch.exp(-log_vars) + log_vars
            terms = terms * torch.exp(BETA * log_vars.detach())
            loss = terms.mean() * HORIZON + KL_WEIGHT * kl
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(modules.parameters(), 100.0)
            optimizer.step()
            total += float(loss.item()) / HORIZON
            batches += 1
        times.append(time.perf_counter() - start)
        losses.append(total / batches)
        if not math.isfinite(losses[-1]):
            raise ValueError(f"loss became {losses[-1]}")
        if checkpoint is not None:
            partial_file = checkpoint.with_suffix(".partial")
            torch.save(
                {
                    "epoch": epoch + 1,
                    "modules": modules.state_dict(),
                    "optimizer": optimizer.state_dict(),
                    "rng": torch.get_rng_state(),
                    "times": times,
                    "losses": losses,
                },
                partial_file,
            )
            os.replace(partial_file, checkpoint)
    modules.eval()
    return modules, {
        "resumed_at_epoch": first_epoch,
        "median_seconds_per_epoch": sorted(times)[len(times) // 2],
        "final_loss": losses[-1],
        "parameters": sum(int(item.numel()) for item in modules.parameters()),
    }


def load(checkpoint: Path, device: str, epochs: int) -> Any:
    """A trained model, refused unless it finished exactly ``epochs``."""
    torch = _torch()
    saved = torch.load(checkpoint, map_location=device, weights_only=True)
    if saved["epoch"] != epochs:
        raise ValueError(f"{checkpoint} stopped at epoch {saved['epoch']}, not {epochs}")
    modules = new_modules(device)
    modules.load_state_dict(saved["modules"])
    modules.eval()
    return modules


def _sweep(args: argparse.Namespace, work: Path, machine: dict[str, Any]) -> dict[str, Any]:
    torch = _torch()
    _, held_out = split_holdout(load_train(args.manifest, Path()))
    data = _Data(args.manifest, args.device, split_holdout)
    stats = {**_stats_of(data), "kinematics": _Kinematics(args.device)}
    masks = phase_masks(held_out, len(data.holdout_s), args.device)
    truth = data.holdout_s[:, HISTORY + 1 :]
    cells: dict[str, Any] = {}
    reused = 0
    for seed in (int(item) for item in args.seeds.split(",")):
        directory = work / f"seed-{seed}"
        directory.mkdir(parents=True, exist_ok=True)
        finished = directory / RESULT
        if finished.exists():
            cells[str(seed)] = json.loads(finished.read_text(encoding="utf-8"))
            reused += 1
            continue
        print(f"latent seed {seed}", file=sys.stderr, flush=True)
        started = time.perf_counter()
        modules, training = train(
            data, stats, seed, args.epochs, directory / CHECKPOINT, args.device
        )
        with torch.no_grad():
            means, _ = predict(modules, stats, data.holdout_s, data.holdout_a)
        cell = {
            "training": training,
            "seconds_this_process": time.perf_counter() - started,
            "predicted_flag": _metrics(means, truth, data.state_std, masks),
        }
        _write_new(finished, cell)
        cells[str(seed)] = cell
    return {
        "machine": machine,
        "epochs": args.epochs,
        "seeds": args.seeds,
        "streams": list(STREAM_SLICES),
        "cells_reused": reused,
        "resumed_from": str(args.resume_from) if args.resume_from else None,
        "fit_episodes": data.fit_episodes,
        "holdout_episodes": data.holdout_episodes,
        "windows_per_epoch": len(data.windows_s),
        "seeds_trained": cells,
    }


def _work_directory(args: argparse.Namespace, run: Run, config: dict[str, Any]) -> Path:
    if args.resume_from is None:
        fresh = run.directory / "work"
        fresh.mkdir()
        _write_new(fresh / PLAN_FILE, {"config": config, "commit": run.commit})
        return fresh
    if run.dirty:
        raise ValueError("commit the run ledger before resuming, so the code note stays true")
    work: Path = args.resume_from / "work"
    plan = json.loads((work / PLAN_FILE).read_text(encoding="utf-8"))
    check_resume(plan, config, _code_changed(plan["commit"]))
    return work


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--seeds", default=",".join(str(seed) for seed in SEEDS))
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    parser.add_argument("--device", choices=("mps", "cpu"), default="mps")
    parser.add_argument("--resume-from", type=Path, default=None)
    args = parser.parse_args(argv)
    config = {
        "manifest": str(args.manifest),
        "seeds": args.seeds,
        "epochs": args.epochs,
        "device": args.device,
    }
    try:
        require_code_root()
        machine = _machine()
        with ledgered_run(
            purpose="WO-004: latent predictor on train data, not an exit test",
            config={**config, "resume_from": str(args.resume_from)},
            seeds={"torch": 0},
            env_lock={"machine": machine},
        ) as run:
            work = _work_directory(args, run, config)
            report = {
                "run": run.directory.name,
                "code": run.code_note,
                **_sweep(args, work, machine),
            }
            with (run.directory / "latent_predictor.json").open("x", encoding="utf-8") as stream:
                json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
                stream.write("\n")
            run.note = f"latent, seeds {args.seeds}, {args.epochs} epochs"
            print(run.directory)
    except (ValueError, OSError, KeyError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
