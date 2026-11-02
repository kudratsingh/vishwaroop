"""Train and score predictors across holdouts, resumably, on train data. Not an exit-test result.

    python -m vishwaroop.models.family_sweep --manifest artifacts/manifests/m0-dataset-v1.json \
        --holdouts m0-scripted-missed-grasp --variants carry-beta

Run it from the repository root, in the robotics environment. Each epoch and each finished cell is
saved under the run directory's ``work/``. After a stop, commit the run ledger and pass that
directory to ``--resume-from``: finished cells are reused and a part-trained one continues from its
last epoch. Results go to ``family_sweep.json`` in a new run directory. Exit codes: 0 measured,
2 refused.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from functools import partial
from pathlib import Path
from typing import Any

from ..sim.runlog import Run, ledgered_run, require_code_root
from .compute_pilot import _Data, _machine, _stats_of
from .cube_phases import reductions
from .cube_study import (
    EPOCHS,
    SEEDS,
    VARIANTS,
    _baselines,
    _evaluate,
    _Kinematics,
    _train,
    largest_gap_m,
    phase_masks,
)
from .pilot_data import load_train, split_family, split_holdout

SEED_HOLDOUT = "seed"
BASELINES = ("constant", "linear", "nominal_hold", "nominal_carry", "nominal_carry_fall")
PLAN_FILE = "plan.json"
CODE_PATHS = ("src",)


def check_resume(plan: dict[str, Any], config: dict[str, Any], code_changed: bool) -> None:
    """Refuse to continue a run with different settings or different code."""
    if plan["config"] != config:
        raise ValueError(f"settings differ from the stopped run: {plan['config']} against {config}")
    if code_changed:
        raise ValueError(f"code under src/ changed since the stopped run's {plan['commit']}")


def _code_changed(commit: str) -> bool:
    result = subprocess.run(
        ["git", "diff", "--quiet", commit, "HEAD", "--", *CODE_PATHS], check=False
    )
    if result.returncode not in (0, 1):
        raise ValueError(f"git could not compare the code with {commit}")
    return result.returncode == 1


def _write_new(path: Path, value: dict[str, Any]) -> None:
    """Write a whole JSON file, or none, so a crash cannot leave half a finished cell."""
    partial_file = path.with_suffix(".partial")
    partial_file.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    partial_file.replace(path)


def _with_reductions(cell: dict[str, Any], baselines: dict[str, Any]) -> dict[str, Any]:
    scored = cell["predicted_flag"]["streams_own_units"]
    return {
        **cell,
        "reduction_against_best_baseline": {
            stream: reductions(
                scored[stream],
                [baselines[name]["streams_own_units"][stream] for name in BASELINES],
            )
            for stream in ("joint_position", "object_position")
        },
    }


def _cell(
    data: _Data,
    stats: dict[str, Any],
    masks: dict[str, Any],
    name: str,
    seed: int,
    epochs: int,
    directory: Path,
) -> tuple[dict[str, Any], bool]:
    directory.mkdir(parents=True, exist_ok=True)
    finished = directory / "result.json"
    if finished.exists():
        return json.loads(finished.read_text(encoding="utf-8")), True
    variant = VARIANTS[name]
    started = time.perf_counter()
    layers, training = _train(data, stats, variant, seed, epochs, directory / "checkpoint.pt")
    cell = {
        "training": training,
        "seconds_this_process": time.perf_counter() - started,
        "predicted_flag": _evaluate(data, stats, variant, layers, masks, False),
    }
    if variant.carry:
        cell["true_flag_diagnostic"] = _evaluate(data, stats, variant, layers, masks, True)
    _write_new(finished, cell)
    return cell, False


def _sweep(args: argparse.Namespace, work: Path, machine: dict[str, Any]) -> dict[str, Any]:
    episodes = load_train(args.manifest, Path())
    holdouts: dict[str, Any] = {}
    reused = 0
    for holdout in args.holdouts.split(","):
        split: Any = split_holdout
        if holdout != SEED_HOLDOUT:
            split = partial(split_family, family=holdout)
        _, held_out = split(episodes)
        data = _Data(args.manifest, args.device, split)
        stats = {**_stats_of(data), "kinematics": _Kinematics(args.device)}
        masks = phase_masks(held_out, len(data.holdout_s), args.device)
        baselines = _baselines(data, stats, masks)
        cells: dict[str, dict[str, Any]] = {}
        for name in args.variants.split(","):
            cells[name] = {}
            for seed in (int(item) for item in args.seeds.split(",")):
                print(f"{holdout} {name} seed {seed}", file=sys.stderr, flush=True)
                directory = work / holdout / name / f"seed-{seed}"
                cell, was_finished = _cell(data, stats, masks, name, seed, args.epochs, directory)
                reused += was_finished
                cells[name][str(seed)] = _with_reductions(cell, baselines)
        holdouts[holdout] = {
            "fit_episodes": data.fit_episodes,
            "holdout_episodes": data.holdout_episodes,
            "windows_per_epoch": len(data.windows_s),
            "holdout_windows": {phase: int(mask.sum().item()) for phase, mask in masks.items()},
            "baselines": baselines,
            "variants": cells,
        }
    return {
        "machine": machine,
        "epochs": args.epochs,
        "seeds": args.seeds,
        "kinematics_gap_m": largest_gap_m(args.device),
        "baselines_in_best": list(BASELINES),
        "resumed_from": str(args.resume_from) if args.resume_from else None,
        "cells_reused": reused,
        "holdouts": holdouts,
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
    parser.add_argument("--holdouts", required=True, help=f"families, or '{SEED_HOLDOUT}'")
    parser.add_argument("--variants", required=True)
    parser.add_argument("--seeds", default=",".join(str(seed) for seed in SEEDS))
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    parser.add_argument("--device", choices=("mps", "cpu"), default="mps")
    parser.add_argument("--resume-from", type=Path, default=None)
    args = parser.parse_args(argv)
    config = {
        "manifest": str(args.manifest),
        "holdouts": args.holdouts,
        "variants": args.variants,
        "seeds": args.seeds,
        "epochs": args.epochs,
        "device": args.device,
    }
    try:
        require_code_root()
        unknown = set(args.variants.split(",")) - set(VARIANTS)
        if unknown:
            raise ValueError(f"unknown variants: {sorted(unknown)}")
        machine = _machine()
        with ledgered_run(
            purpose="WO-004: holdouts on train data, report-only, not an exit test",
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
            with (run.directory / "family_sweep.json").open("x", encoding="utf-8") as stream:
                json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
                stream.write("\n")
            run.note = (
                f"{args.variants} on {args.holdouts}, seeds {args.seeds}, {args.epochs} epochs,"
                f" {report['cells_reused']} cells reused"
            )
            print(run.directory)
    except (ValueError, OSError, KeyError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
