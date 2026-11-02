"""Score WO-004's frozen predictors on dev, once, for ET-M1-1 and ET-M1-3.

    python -m vishwaroop.models.m1_evaluate \\
        --train-manifest artifacts/manifests/m0-dataset-v1.json \\
        --dev-manifests artifacts/manifests/m0-dataset-v1.json,artifacts/manifests/m1-dev-v1.json \\
        --ensemble-run runs/<id> --latent-run runs/<id> --epochs <frozen>

Run it from the repository root, in the robotics environment. It is the only code that reads a dev
episode for a predictor. It refuses a plan other than the frozen one, too few dev episodes, a model
that did not finish its frozen epochs or no longer reproduces its train-side numbers, and a second
scoring once one has completed. Results go to ``m1_dev_evaluation.json`` in a new run directory.
Exit codes: 0 scored, whether or not the tests passed; 2 refused.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..sim.runlog import ledgered_run, require_code_root
from . import latent_predictor
from .compute_pilot import (
    HISTORY,
    HORIZON,
    MEMBERS,
    STREAM_SLICES,
    WINDOW,
    _Data,
    _machine,
    _stats_of,
)
from .compute_pilot import _torch as _torch_module
from .cube_study import (
    CALIBRATED_STREAMS,
    VARIANTS,
    Z_90,
    _baseline_predictions,
    _Kinematics,
    _metrics,
    _rollout,
    phase_masks,
)
from .family_sweep import BASELINES, SEED_HOLDOUT
from .m1_scoring import (
    MIN_DEV_EPISODES,
    bootstrap_interval,
    conformal_scale,
    et_m1_1_passes,
    et_m1_3_passes,
    lowest_baseline,
    reductions_at_each_horizon,
)
from .pilot_data import FIRST_DEV_SEED, EpisodeArrays, read_episode, split_holdout

PLAN_PATH = Path("evals/M1-stage-b.json")
PLAN_SHA256 = "41a64cb136bd683ba840aee6e7ddb5d2bb3cfe025a6f746dd1619505074f7339"
PURPOSE = "WO-004: the one dev scoring of the frozen predictors"
REPRODUCE_TOLERANCE = 1e-5


def check_plan(path: Path, expected: str = PLAN_SHA256) -> dict[str, Any]:
    """The frozen plan, refused if it is not byte for byte what was frozen before any dev metric."""
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise ValueError(f"{path} has sha256 {actual}, and the frozen plan is {expected}")
    plan: dict[str, Any] = json.loads(raw)
    return plan


def check_not_scored(runs_ledger: Path, purpose: str = PURPOSE) -> None:
    """Dev is scored once. A run that crashed before writing a result may be repeated."""
    records = [json.loads(line) for line in runs_ledger.read_text(encoding="utf-8").splitlines()]
    mine = {
        record["run_id"]
        for record in records
        if record.get("status") == "started" and record.get("purpose") == purpose
    }
    for record in records:
        if record.get("status") == "completed" and record.get("run_id") in mine:
            run_id = record["run_id"]
            raise ValueError(f"dev was already scored by {run_id}; another scoring needs a new WO")


def load_dev(paths: Sequence[Path], root: Path) -> list[EpisodeArrays]:
    """Every dev episode of these manifests, each once, and nothing else."""
    episodes: list[EpisodeArrays] = []
    seen: set[str] = set()
    for path in paths:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for entry in manifest["episodes"]:
            if entry["partition"] != "dev":
                continue
            if entry["seed"] < FIRST_DEV_SEED:
                raise ValueError(f"{entry['episode_id']}: seed {entry['seed']} is not a dev seed")
            if entry["episode_id"] in seen:
                raise ValueError(f"{entry['episode_id']} is in two manifests")
            seen.add(entry["episode_id"])
            episode = read_episode(root / entry["path"], entry["transitions_sha256"], entry["seed"])
            episodes.append(replace(episode, family=entry["family"]))
    if len(episodes) < MIN_DEV_EPISODES:
        raise ValueError(f"{len(episodes)} dev episodes; the exit tests need {MIN_DEV_EPISODES}")
    return sorted(episodes, key=lambda item: (item.family, item.seed))


class _Windows:
    """Dev windows, with the episode each one came from."""

    def __init__(self, episodes: Sequence[EpisodeArrays], device: str) -> None:
        torch = _torch_module()
        states, actions = _Data._windows(list(episodes), WINDOW)
        self.states = states.to(device)
        self.actions = actions.to(device)
        counts = [max(len(item.states) - WINDOW + 1, 0) for item in episodes]
        self.counts = counts
        self.episode = torch.repeat_interleave(torch.tensor(counts)).to(device)
        self.families = [item.family for item in episodes]
        if len(self.episode) != len(self.states):
            raise ValueError("episode labels do not line up with the dev windows")


def _load_ensemble(path: Path, device: str, epochs: int) -> list[Any]:
    torch = _torch_module()
    saved = torch.load(path, map_location="cpu", weights_only=True)
    if saved["epoch"] != epochs:
        raise ValueError(f"{path} stopped at epoch {saved['epoch']}, not {epochs}")
    return [tuple(item.to(device) for item in layer) for layer in saved["layers"]]


def _ensemble_on(stats: dict[str, Any], variant: Any, layers: list[Any], s: Any, a: Any) -> Any:
    """Member means and the combined std, in own units."""
    torch = _torch_module()
    states = s.unsqueeze(0).expand(MEMBERS, -1, -1, -1)
    actions = a.unsqueeze(0).expand(MEMBERS, -1, -1, -1)
    with torch.no_grad():
        means, log_vars = _rollout(stats, variant, layers, states, actions)
    stacked = torch.stack(means, 2)
    variance = (torch.exp(torch.stack(log_vars, 2)) * stats["delta_std"].pow(2)).mean(0)
    variance = variance + stacked.var(0, unbiased=False)
    return stacked.mean(0), variance.sqrt()


def _latent_on(stats: dict[str, Any], modules: Any, s: Any, a: Any) -> Any:
    torch = _torch_module()
    with torch.no_grad():
        means, log_vars = latent_predictor.predict(modules, stats, s, a)
    return means, (torch.exp(log_vars) * stats["delta_std"].pow(2)).sqrt()


def _stream_rmse(mean: Any, truth: Any) -> dict[str, list[float]]:
    streams: dict[str, list[float]] = _metrics(mean, truth, truth.new_ones(truth.shape[-1]), {})[
        "streams_own_units"
    ]
    return streams


def _check_reproduces(mean: Any, truth: Any, recorded: dict[str, Any], label: str) -> None:
    """A stale or wrong weights file must not reach dev."""
    now = _stream_rmse(mean, truth)
    for stream in CALIBRATED_STREAMS:
        for h, (a, b) in enumerate(zip(now[stream], recorded[stream], strict=True)):
            if abs(a - b) > REPRODUCE_TOLERANCE * max(abs(b), 1e-6):
                raise ValueError(f"{label} {stream} h{h + 1}: {a} here, {b} when trained")


def _scales(mean: Any, std: Any, truth: Any) -> dict[str, list[float]]:
    """Per stream and horizon, fitted on the train partition's own holdout, never on dev."""
    ratio = ((mean - truth).abs() / std.clamp_min(1e-12)).cpu().double()
    return {
        stream: [conformal_scale(ratio[:, h, a:b].flatten().tolist()) for h in range(HORIZON)]
        for stream, (a, b) in ((name, STREAM_SLICES[name]) for name in CALIBRATED_STREAMS)
    }


def tied_spearman(a: Any, b: Any) -> float:
    """Spearman rank correlation, with tied values sharing their average rank."""
    torch = _torch_module()

    def ranks(values: Any) -> Any:
        _, inverse, counts = torch.unique(values, return_inverse=True, return_counts=True)
        last = counts.cumsum(0).to(torch.float64)
        return (last - (counts.to(torch.float64) - 1.0) / 2.0)[inverse]

    x, y = ranks(a), ranks(b)
    x, y = x - x.mean(), y - y.mean()
    denominator = (x.norm() * y.norm()).item()
    if denominator == 0.0:
        raise ValueError("a rank correlation needs values that differ")
    return float((x * y).sum().item() / denominator)


def _uncertainty(mean: Any, std: Any, truth: Any, scales: dict[str, list[float]]) -> dict[str, Any]:
    error = (mean - truth).abs().cpu().double()
    spread = std.cpu().double()
    result: dict[str, Any] = {}
    for stream in CALIBRATED_STREAMS:
        a, b = STREAM_SLICES[stream]
        e, s = error[:, :, a:b], spread[:, :, a:b]
        by_horizon = [(e[:, h].flatten(), s[:, h].flatten()) for h in range(HORIZON)]
        result[stream] = {
            "spearman": [tied_spearman(y, x) for x, y in by_horizon],
            "uncalibrated_coverage": [
                float((x <= Z_90 * y).double().mean().item()) for x, y in by_horizon
            ],
            "calibrated_coverage": [
                float((x <= k * y).double().mean().item())
                for (x, y), k in zip(by_horizon, scales[stream], strict=True)
            ],
            "report_only_pooled_over_horizons": {
                "spearman": tied_spearman(s.flatten(), e.flatten()),
                "uncalibrated_coverage": float((e <= Z_90 * s).double().mean().item()),
            },
            "report_only_spearman_by_coordinate": [
                tied_spearman(s[:, :, c].flatten(), e[:, :, c].flatten()) for c in range(b - a)
            ],
        }
    return result


def _episode_squares(mean: Any, truth: Any, windows: _Windows, stream: str) -> list[list[float]]:
    """For each horizon, each episode's sum over windows of the mean squared coordinate error."""
    torch = _torch_module()
    a, b = STREAM_SLICES[stream]
    per_window = (mean - truth)[:, :, a:b].pow(2).mean(-1).cpu().double()
    index = windows.episode.cpu()
    size = len(windows.counts)
    return [
        torch.zeros(size, dtype=torch.float64).index_add_(0, index, per_window[:, h]).tolist()
        for h in range(HORIZON)
    ]


def _family_rmse(mean: Any, truth: Any, windows: _Windows, family: str) -> dict[str, list[float]]:
    torch = _torch_module()
    chosen = torch.tensor(
        [windows.families[i] == family for i in windows.episode.cpu().tolist()],
        device=mean.device,
    )
    return _stream_rmse(mean[chosen], truth[chosen])


def _score(
    mean: Any,
    std: Any,
    truth: Any,
    state_std: Any,
    masks: dict[str, Any],
    windows: _Windows,
    baselines: dict[str, Any],
    baseline_squares: dict[str, dict[str, list[list[float]]]],
    scales: dict[str, list[float]],
    seed: int,
) -> dict[str, Any]:
    metrics = _metrics(mean, truth, state_std, masks)
    scored = metrics["streams_own_units"]
    squares = {
        stream: _episode_squares(mean, truth, windows, stream) for stream in CALIBRATED_STREAMS
    }
    families = sorted(set(windows.families))
    by_family: dict[str, Any] = {}
    for family in families:
        own = _family_rmse(mean, truth, windows, family)
        by_family[family] = {
            stream: reductions_at_each_horizon(
                own[stream],
                {
                    name: _family_rmse(value, truth, windows, family)[stream]
                    for name, value in baselines.items()
                },
            )
            for stream in CALIBRATED_STREAMS
        }
    return {
        "own_units": scored,
        "reductions": {
            stream: reductions_at_each_horizon(
                scored[stream],
                {name: _stream_rmse(value, truth)[stream] for name, value in baselines.items()},
            )
            for stream in CALIBRATED_STREAMS
        },
        "reduction_intervals_95": {
            stream: [
                bootstrap_interval(
                    squares[stream][h],
                    windows.counts,
                    {name: baseline_squares[name][stream][h] for name in baselines},
                    seed=seed,
                )
                for h in range(HORIZON)
            ]
            for stream in CALIBRATED_STREAMS
        },
        "reductions_by_family_report_only": by_family,
        "uncertainty": _uncertainty(mean, std, truth, scales),
        "scales_from_train_holdout": scales,
        "cube_mm_by_phase": metrics["cube_mm_by_phase"],
        "joint_rad_by_joint": metrics["joint_rad_by_joint"],
    }


def _evaluate(
    args: argparse.Namespace, plan: dict[str, Any], machine: dict[str, Any]
) -> dict[str, Any]:
    torch = _torch_module()
    device = args.device
    data = _Data(args.train_manifest, device, split_holdout)
    stats = {**_stats_of(data), "kinematics": _Kinematics(device)}
    episodes = load_dev([Path(item) for item in args.dev_manifests.split(",")], Path())
    windows = _Windows(episodes, device)
    dev_view = copy.copy(data)
    dev_view.holdout_s, dev_view.holdout_a = windows.states, windows.actions
    truth = windows.states[:, HISTORY + 1 :]
    held_truth = data.holdout_s[:, HISTORY + 1 :]
    masks = phase_masks(episodes, len(windows.states), device)
    with torch.no_grad():
        predictions = _baseline_predictions(dev_view, stats)
    baselines = {name: predictions[name] for name in BASELINES}
    baseline_rmse = {name: _stream_rmse(value, truth) for name, value in baselines.items()}
    baseline_squares = {
        name: {s: _episode_squares(value, truth, windows, s) for s in CALIBRATED_STREAMS}
        for name, value in baselines.items()
    }
    seeds = [int(item) for item in plan["seeds"]]
    variant_name = plan["final_variant"]
    variant = VARIANTS[variant_name]
    epochs = int(args.epochs)
    ensemble: dict[str, Any] = {}
    latent: dict[str, Any] = {}
    sweep = json.loads((args.ensemble_run / "family_sweep.json").read_text(encoding="utf-8"))
    if sweep["epochs"] != epochs:
        raise ValueError(f"{args.ensemble_run} trained {sweep['epochs']} epochs, not {epochs}")
    recorded = sweep["holdouts"][SEED_HOLDOUT]["variants"][variant_name]
    latent_report = json.loads(
        (args.latent_run / "latent_predictor.json").read_text(encoding="utf-8")
    )
    for seed in seeds:
        print(f"seed {seed}", file=sys.stderr, flush=True)
        path = (
            args.ensemble_run
            / "work"
            / SEED_HOLDOUT
            / variant_name
            / f"seed-{seed}"
            / "checkpoint.pt"
        )
        layers = _load_ensemble(path, device, epochs)
        held_mean, held_std = _ensemble_on(stats, variant, layers, data.holdout_s, data.holdout_a)
        _check_reproduces(
            held_mean,
            held_truth,
            recorded[str(seed)]["predicted_flag"]["streams_own_units"],
            f"ensemble seed {seed}",
        )
        mean, std = _ensemble_on(stats, variant, layers, windows.states, windows.actions)
        ensemble[str(seed)] = _score(
            mean,
            std,
            truth,
            data.state_std,
            masks,
            windows,
            baselines,
            baseline_squares,
            _scales(held_mean, held_std, held_truth),
            seed,
        )
        modules = latent_predictor.load(
            args.latent_run / "work" / f"seed-{seed}" / latent_predictor.CHECKPOINT,
            device,
            int(plan["latent"]["epochs"]),
        )
        held_mean, held_std = _latent_on(stats, modules, data.holdout_s, data.holdout_a)
        _check_reproduces(
            held_mean,
            held_truth,
            latent_report["seeds_trained"][str(seed)]["predicted_flag"]["streams_own_units"],
            f"latent seed {seed}",
        )
        mean, std = _latent_on(stats, modules, windows.states, windows.actions)
        latent[str(seed)] = _score(
            mean,
            std,
            truth,
            data.state_std,
            masks,
            windows,
            baselines,
            baseline_squares,
            _scales(held_mean, held_std, held_truth),
            seed,
        )
    count = len(episodes)
    return {
        "machine": machine,
        "plan_sha256": PLAN_SHA256,
        "dev_episodes": count,
        "dev_windows": len(windows.states),
        "episodes_by_family": dict(Counter(windows.families)),
        "windows_by_phase": {name: int(mask.sum().item()) for name, mask in masks.items()},
        "final_variant": variant_name,
        "epochs": epochs,
        "ensemble_run": str(args.ensemble_run),
        "latent_run": str(args.latent_run),
        "baselines_in_best": list(BASELINES),
        "baselines_own_units": baseline_rmse,
        "lowest_baseline": {
            stream: lowest_baseline({name: baseline_rmse[name][stream] for name in BASELINES})
            for stream in CALIBRATED_STREAMS
        },
        "ensemble": ensemble,
        "latent_report_only": latent,
        "verdicts": {
            "ET-M1-1": et_m1_1_passes(
                {seed: cell["reductions"] for seed, cell in ensemble.items()}, count
            ),
            "ET-M1-3": et_m1_3_passes(
                {seed: cell["uncertainty"] for seed, cell in ensemble.items()}, count
            ),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-manifest", type=Path, required=True)
    parser.add_argument("--dev-manifests", required=True)
    parser.add_argument("--ensemble-run", type=Path, required=True)
    parser.add_argument("--latent-run", type=Path, required=True)
    parser.add_argument("--epochs", type=int, required=True)
    parser.add_argument("--device", choices=("mps", "cpu"), default="mps")
    parser.add_argument("--runs-ledger", type=Path, default=Path("ledgers/runs.jsonl"))
    args = parser.parse_args(argv)
    try:
        require_code_root()
        plan = check_plan(PLAN_PATH)
        if args.epochs not in plan["allowed_epochs"]:
            raise ValueError(f"{args.epochs} epochs is not in the frozen plan")
        check_not_scored(args.runs_ledger)
        machine = _machine()
        with ledgered_run(
            purpose=PURPOSE,
            config={
                "plan_sha256": PLAN_SHA256,
                "ensemble_run": str(args.ensemble_run),
                "latent_run": str(args.latent_run),
                "dev_manifests": args.dev_manifests,
                "epochs": args.epochs,
            },
            seeds={"bootstrap": 0},
            env_lock={"machine": machine},
        ) as run:
            if run.dirty:
                raise ValueError("commit before scoring dev, so the code note stays true")
            started = time.perf_counter()
            report = {
                "run": run.directory.name,
                "code": run.code_note,
                **_evaluate(args, plan, machine),
            }
            report["seconds"] = time.perf_counter() - started
            with (run.directory / "m1_dev_evaluation.json").open("x", encoding="utf-8") as stream:
                json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
                stream.write("\n")
            run.note = f"verdicts {report['verdicts']}"
            print(run.directory)
    except (ValueError, OSError, KeyError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
