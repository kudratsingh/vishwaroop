"""WO-005 stage 0: the owner's two follow-ups to WO-004, frozen in ``evals/M1-followups.json``.

    python -m vishwaroop.models.m1_followups

Run it from the repository root, in the robotics environment. It checks on train data that a free
cube never does worse than staying put, then reports dev numbers for information only: before and
after on ``dev-grasp-offset``, and coverage with scales fitted on one half of dev and applied to
the other. It changes no exit-test result. It refuses a changed plan or dev manifest, and a second
run once a result exists. Exit codes: 0 measured, 2 refused.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import time
from collections.abc import Sequence
from functools import partial
from pathlib import Path
from typing import Any

from ..sim.runlog import ledgered_run, require_code_root
from .compute_pilot import HISTORY, STREAM_SLICES, _Data, _machine, _stats_of, _torch
from .cube_study import (
    CALIBRATED_STREAMS,
    EPOCHS,
    GRASP_REACH_M,
    SEEDS,
    VARIANTS,
    _baseline_predictions,
    _Kinematics,
    phase_masks,
)
from .family_sweep import BASELINES, SEED_HOLDOUT
from .m1_evaluate import (
    ENSEMBLE_RUN,
    FROZEN_DEV_MANIFESTS,
    TRAIN_MANIFEST,
    _check_reproduces,
    _ensemble_on,
    _load_ensemble,
    _phase_rmse,
    _scales,
    _stream_rmse,
    _Windows,
    check_manifests,
    load_dev,
)
from .m1_scoring import reductions_at_each_horizon
from .pilot_data import EpisodeArrays, load_train, split_family, split_holdout

PLAN_PATH = Path("evals/M1-followups.json")
PLAN_SHA256 = "c642b66b183590d3f50c12a89fa3bda8c2e73e7a5c79975879cb082cadb59c71"
RESULT = "m1_followups.json"
PURPOSE = "WO-005 stage 0: free cube and calibration split, information only on dev"
FAMILY_RUN = Path("runs/20261102T041509Z_93dd348c")
BEFORE = "carry-contact-beta-fall"
AFTER = "carry-contact-beta-fall-still"
# Each frozen design: plan file, its hash, the result it writes, and the variant it checks.
DESIGNS = {
    "first": (PLAN_PATH, PLAN_SHA256, RESULT, AFTER),
    "second": (
        Path("evals/M1-followups-v2.json"),
        "68640c492592cd7f678ec1121e169282b782c8e24184210b2cc5581416efc617",
        "m1_followups_v2.json",
        "carry-contact-beta-fall-still-reach",
    ),
}
NEVER_HELD = ("resting", "moved_before_grasp", "moved_after_grasp")
STAYS_PUT = "constant"  # holds the whole state, so its cube stays where it was
CHECKED_FAMILY = "m0-scripted-dev-grasp-offset"
TRAIN_FAMILIES = (
    "m0-scripted-early-release",
    "m0-scripted-missed-grasp",
    "m0-scripted-no-release",
    "m0-scripted-noisy-actions",
    "m0-scripted-nominal",
    "m0-scripted-timeout",
    "m0-scripted-wrong-place",
)


def check_plan(path: Path, expected: str = PLAN_SHA256) -> dict[str, Any]:
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise ValueError(f"{path} has sha256 {actual}, and the frozen plan is {expected}")
    plan: dict[str, Any] = json.loads(raw)
    return plan


def check_not_run(runs_root: Path, result: str = RESULT) -> None:
    found = sorted(runs_root.glob(f"*/{result}*"))
    if found:
        raise ValueError(f"already run in {found[0]}; another run needs a new work order")


def folds(episodes: Sequence[EpisodeArrays]) -> list[int]:
    """Fold 0 or 1 for each episode: within a family, by seed, alternating, the first to fold 0."""
    rank: dict[tuple[str, int], int] = {}
    for family in sorted({item.family for item in episodes}):
        seeds = sorted(item.seed for item in episodes if item.family == family)
        rank.update({(family, seed): index % 2 for index, seed in enumerate(seeds)})
    return [rank[(item.family, item.seed)] for item in episodes]


def never_worse(after: Sequence[float], stays_put: Sequence[float]) -> bool:
    """At every horizon, at most the stays-put error. Equal counts as not worse."""
    if len(after) != len(stays_put):
        raise ValueError("horizons differ")
    return all(a <= b for a, b in zip(after, stays_put, strict=True))


def _never_held_mask(masks: dict[str, Any]) -> Any:
    torch = _torch()
    chosen = [masks[name] for name in NEVER_HELD]
    return torch.stack(chosen).any(0)


def _cube_by_phase(mean: Any, truth: Any, masks: dict[str, Any]) -> dict[str, list[float]]:
    every = {**masks, "never_held": _never_held_mask(masks)}
    return {
        phase: values["object_position"]
        for phase, values in _phase_rmse(mean, truth, every).items()
    }


def worse_windows(after: Any, truth: Any, start: Any, never_held: Any, tool: Any) -> dict[str, int]:
    """Never-held windows worse than stays-put at the last horizon, and how many began in reach."""
    cube = slice(*STREAM_SLICES["object_position"])
    own = (after[:, -1, cube] - truth[:, -1, cube]).pow(2).sum(-1)
    put = (start[:, cube] - truth[:, -1, cube]).pow(2).sum(-1)
    worse = (own > put) & never_held
    near = (start[:, cube] - tool).norm(dim=-1) <= GRASP_REACH_M
    return {
        "never_held_windows": int(never_held.sum().item()),
        "worse_at_last_horizon": int(worse.sum().item()),
        "of_which_began_within_reach": int((worse & near).sum().item()),
    }


def _compare(
    before: Any,
    after: Any,
    truth: Any,
    baselines: dict[str, Any],
    masks: dict[str, Any],
    start: Any = None,
    tool: Any = None,
) -> dict[str, Any]:
    put = _cube_by_phase(baselines[STAYS_PUT], truth, masks)
    after_cube = _cube_by_phase(after, truth, masks)
    rmse = {name: _stream_rmse(value, truth) for name, value in baselines.items()}
    reductions = {
        label: {
            stream: reductions_at_each_horizon(
                _stream_rmse(value, truth)[stream],
                {name: rmse[name][stream] for name in BASELINES},
            )
            for stream in CALIBRATED_STREAMS
        }
        for label, value in (("before", before), ("after", after))
    }
    checked = [phase for phase in (*NEVER_HELD, "never_held") if phase in after_cube]
    return {
        "cube_rmse_by_phase": {
            "before": _cube_by_phase(before, truth, masks),
            "after": after_cube,
            "stays_put": put,
        },
        "joint_rmse_by_phase": {
            label: {
                phase: values["joint_position"]
                for phase, values in _phase_rmse(value, truth, masks).items()
            }
            for label, value in (("before", before), ("after", after))
        },
        "reductions": reductions,
        "never_worse_than_stays_put": {
            phase: never_worse(after_cube[phase], put[phase]) for phase in checked
        },
        **(
            {}
            if start is None
            else {
                "worse_windows": worse_windows(after, truth, start, _never_held_mask(masks), tool)
            }
        ),
    }


def _train_side(device: str, after_name: str) -> dict[str, Any]:
    episodes = load_train(TRAIN_MANIFEST, Path())
    results: dict[str, Any] = {}
    for holdout in (SEED_HOLDOUT, *TRAIN_FAMILIES):
        split: Any = split_holdout
        run = ENSEMBLE_RUN
        if holdout != SEED_HOLDOUT:
            split = partial(split_family, family=holdout)
            run = FAMILY_RUN
        _, held_out = split(episodes)
        data = _Data(TRAIN_MANIFEST, device, split)
        stats = {**_stats_of(data), "kinematics": _Kinematics(device)}
        masks = phase_masks(held_out, len(data.holdout_s), device)
        truth = data.holdout_s[:, HISTORY + 1 :]
        baselines = {
            name: value
            for name, value in _baseline_predictions(data, stats).items()
            if name in BASELINES
        }
        recorded = json.loads((run / "family_sweep.json").read_text(encoding="utf-8"))
        cells: dict[str, Any] = {}
        for seed in SEEDS:
            print(f"{holdout} seed {seed}", file=sys.stderr, flush=True)
            path = run / "work" / holdout / BEFORE / f"seed-{seed}" / "checkpoint.pt"
            layers = _load_ensemble(path, device, EPOCHS)
            before, _ = _ensemble_on(
                stats, VARIANTS[BEFORE], layers, data.holdout_s, data.holdout_a
            )
            _check_reproduces(
                before,
                truth,
                recorded["holdouts"][holdout]["variants"][BEFORE][str(seed)]["predicted_flag"][
                    "streams_own_units"
                ],
                f"{holdout} seed {seed}",
            )
            after, _ = _ensemble_on(
                stats, VARIANTS[after_name], layers, data.holdout_s, data.holdout_a
            )
            start = data.holdout_s[:, HISTORY]
            tool = stats["kinematics"](start[:, :6])
            cells[str(seed)] = _compare(before, after, truth, baselines, masks, start, tool)
        results[holdout] = {
            "windows_by_phase": {name: int(mask.sum().item()) for name, mask in masks.items()},
            "seeds": cells,
            "never_worse_everywhere": all(
                all(cell["never_worse_than_stays_put"].values()) for cell in cells.values()
            ),
        }
    return results


def _coverage(mean: Any, std: Any, truth: Any, scales: dict[str, list[float]]) -> dict[str, Any]:
    error = (mean - truth).abs()
    result = {}
    for stream in CALIBRATED_STREAMS:
        a, b = STREAM_SLICES[stream]
        result[stream] = [
            float((error[:, h, a:b] <= k * std[:, h, a:b]).cpu().double().mean().item())
            for h, k in enumerate(scales[stream])
        ]
    return result


def _cross_fitted(mean: Any, std: Any, truth: Any, fold: Any) -> dict[str, Any]:
    """Scales from one fold, coverage on the other, both ways, and over both."""
    halves = [fold == 0, fold == 1]
    scales = [_scales(mean[part], std[part], truth[part]) for part in halves]
    by_fold = [
        _coverage(mean[halves[1 - i]], std[halves[1 - i]], truth[halves[1 - i]], scales[i])
        for i in range(2)
    ]
    counts = [int(part.sum().item()) for part in halves]
    pooled = {
        stream: [
            (by_fold[0][stream][h] * counts[1] + by_fold[1][stream][h] * counts[0])
            / (counts[0] + counts[1])
            for h in range(len(by_fold[0][stream]))
        ]
        for stream in CALIBRATED_STREAMS
    }
    return {
        "scales_fitted_on_fold_a": scales[0],
        "scales_fitted_on_fold_b": scales[1],
        "coverage_on_fold_b": by_fold[0],
        "coverage_on_fold_a": by_fold[1],
        "coverage_over_both": pooled,
        "windows_by_fold": {"a": counts[0], "b": counts[1]},
    }


def _dev_side(device: str, after_name: str) -> dict[str, Any]:
    torch = _torch()
    data = _Data(TRAIN_MANIFEST, device, split_holdout)
    stats = {**_stats_of(data), "kinematics": _Kinematics(device)}
    episodes = load_dev(tuple(FROZEN_DEV_MANIFESTS), Path())
    windows = _Windows(episodes, device)
    view = copy.copy(data)
    view.holdout_s, view.holdout_a = windows.states, windows.actions
    truth = windows.states[:, HISTORY + 1 :]
    masks = phase_masks(episodes, len(windows.states), device)
    with torch.no_grad():
        baselines = {
            name: value
            for name, value in _baseline_predictions(view, stats).items()
            if name in BASELINES
        }
    labels = windows.episode.cpu().tolist()
    family = torch.tensor([windows.families[i] == CHECKED_FAMILY for i in labels], device=device)
    fold_of = folds(episodes)
    fold = torch.tensor([fold_of[i] for i in labels], device=device)
    family_masks = {name: mask & family for name, mask in masks.items()}
    cells: dict[str, Any] = {}
    for seed in SEEDS:
        print(f"dev seed {seed}", file=sys.stderr, flush=True)
        path = ENSEMBLE_RUN / "work" / SEED_HOLDOUT / BEFORE / f"seed-{seed}" / "checkpoint.pt"
        layers = _load_ensemble(path, device, EPOCHS)
        before, before_std = _ensemble_on(
            stats, VARIANTS[BEFORE], layers, windows.states, windows.actions
        )
        after, after_std = _ensemble_on(
            stats, VARIANTS[after_name], layers, windows.states, windows.actions
        )
        cells[str(seed)] = {
            "all_dev": _compare(
                before,
                after,
                truth,
                baselines,
                masks,
                windows.states[:, HISTORY],
                stats["kinematics"](windows.states[:, HISTORY, :6]),
            ),
            CHECKED_FAMILY: _compare(
                before[family],
                after[family],
                truth[family],
                {name: value[family] for name, value in baselines.items()},
                {name: mask[family] for name, mask in family_masks.items()},
            ),
            "calibration_split": {
                BEFORE: _cross_fitted(before, before_std, truth, fold),
                after_name: _cross_fitted(after, after_std, truth, fold),
            },
        }
    return {
        "dev_episodes": len(episodes),
        "dev_windows": len(windows.states),
        "episodes_by_fold": {"a": fold_of.count(0), "b": fold_of.count(1)},
        "checked_family_windows": int(family.sum().item()),
        "seeds": cells,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("mps", "cpu"), default="mps")
    parser.add_argument("--design", choices=tuple(DESIGNS), default="first")
    args = parser.parse_args(argv)
    plan_path, plan_sha256, result, after_name = DESIGNS[args.design]
    try:
        require_code_root()
        check_plan(plan_path, plan_sha256)
        check_manifests(FROZEN_DEV_MANIFESTS)
        check_not_run(Path("runs"), result)
        machine = _machine()
        with ledgered_run(
            purpose=PURPOSE,
            config={"plan_sha256": plan_sha256, "device": args.device, "design": args.design},
            seeds={"none": 0},
            env_lock={"machine": machine},
        ) as run:
            if run.dirty:
                raise ValueError("commit first, so the code note stays true")
            started = time.perf_counter()
            report: dict[str, Any] = {
                "run": run.directory.name,
                "code": run.code_note,
                "machine": machine,
                "design": args.design,
                "variant": after_name,
                "plan_sha256": plan_sha256,
                "train_side": _train_side(args.device, after_name),
                "dev_information_only": _dev_side(args.device, after_name),
            }
            report["seconds"] = time.perf_counter() - started
            write_result_named(run.directory, report, result)
            run.note = f"free cube, {args.design} design, and calibration split"
            print(run.directory)
    except (ValueError, OSError, KeyError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


def write_result_named(directory: Path, report: dict[str, Any], result: str) -> None:
    """Write the whole result or nothing, under this design's file name."""
    text = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    partial_file = directory / f"{result}.partial"
    partial_file.write_text(text, encoding="utf-8")
    partial_file.replace(directory / result)


if __name__ == "__main__":
    raise SystemExit(main())
