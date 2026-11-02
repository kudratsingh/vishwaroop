"""Score ET-M1-2 and ET-M1-5 on the simulator branches, once (WO-005).

    python -m vishwaroop.scoring.score_branches

Run it from the repository root, in the robotics environment. Rules are frozen in
``evals/M1-planner-scorer.json`` and its amendments. The branch data and the calibration split are
pinned by hash. It refuses anything changed and a second scoring once a result exists. Results go
to ``branch_scores.json`` in a new run directory. Exit codes: 0 scored, pass or fail; 2 refused.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import random
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..models.compute_pilot import (
    HISTORY,
    MEMBERS,
    STREAM_SLICES,
    _Data,
    _machine,
    _stats_of,
    _torch,
)
from ..models.cube_study import EPOCHS, VARIANTS, _Kinematics, _rollout
from ..models.family_sweep import SEED_HOLDOUT
from ..models.m1_evaluate import (
    ENSEMBLE_RUN,
    TRAIN_MANIFEST,
    _ensemble_on,
    _load_ensemble,
    _scales,
    _Windows,
    check_manifests,
)
from ..models.pilot_data import EpisodeArrays, read_episode, split_holdout
from ..sim.runlog import ledgered_run, require_code_root
from ..sim.so100_kinematics import tool_point
from .violations import margins, task_cost

LEARNED = "carry-contact-beta-fall-still-reach"
NOMINAL = "nominal-still-reach"
SEED = 0
PLAN = Path("evals/M1-planner-scorer.json")
PLAN_SHA256 = "88c952ed4ee1ca91db359e5ff964a913f460e6cfc67ef6fdeee79e7a420453bf"
BRANCHES = {
    Path("runs/20261102T091817Z_47852f39/branches.json"): (
        "70362c2c066dd09356cf8fb5d401724338c0a047643934fe39420db441016b72"
    ),
    Path("runs/20261102T092433Z_4ebe32df/branches.json"): (
        "d481008716991765e235404c2912c7ef157b5d49c97b305ed2e08a6108a5eed9"
    ),
}
ET_M1_2_RUN = Path("runs/20261102T091817Z_47852f39/branches.json")
CALIBRATION = {
    Path("artifacts/manifests/m1-calibration-v1.json"): (
        "6051c08e48117d1f92c81bad612a46317ec5060cd3a05e1cf10a901d63e2ad19"
    )
}
RESULT = "branch_scores.json"
SEPARATED_M = 0.005
MIN_ACCURACY = 0.8
MIN_STATES = 50
MIN_AUROC = 0.75
MAX_ABSTENTION = 0.2
MIN_VIOLATIONS = 10
ABSTAIN_QUANTILE = 0.9
Z95 = 1.959964


def check_not_run(runs_root: Path) -> None:
    found = sorted(runs_root.glob(f"*/{RESULT}*"))
    if found:
        raise ValueError(f"already scored in {found[0]}; the rules allow one scoring")


def pair_accuracy(
    states: Sequence[tuple[Sequence[float], Sequence[float]]],
) -> tuple[int, int, int, int]:
    """Right, scored, excluded and contributing states, over (simulated, predicted) cost lists.

    A pair is scored when its simulated costs differ by at least 5 mm, and right when the
    predicted costs differ in the same direction. A predicted tie is wrong.
    """
    right = scored = excluded = contributing = 0
    for simulated, predicted in states:
        if len(simulated) != len(predicted):
            raise ValueError("each chunk needs a simulated and a predicted cost")
        found = 0
        for i, j in itertools.combinations(range(len(simulated)), 2):
            difference = simulated[i] - simulated[j]
            if abs(difference) < SEPARATED_M:
                excluded += 1
                continue
            found += 1
            right += (predicted[i] - predicted[j]) * difference > 0
        scored += found
        contributing += found > 0
    return right, scored, excluded, contributing


def auroc(scores: Sequence[float], labels: Sequence[bool]) -> float:
    """Area under the ROC curve, ties counted as half."""
    positives = [s for s, y in zip(scores, labels, strict=True) if y]
    negatives = [s for s, y in zip(scores, labels, strict=True) if not y]
    if not positives or not negatives:
        raise ValueError("AUROC needs both classes")
    wins = sum((p > n) + 0.5 * (p == n) for p in positives for n in negatives)
    return wins / (len(positives) * len(negatives))


def wilson(right: int, total: int) -> tuple[float, float]:
    if total == 0:
        raise ValueError("no trials")
    share = right / total
    centre = share + Z95 * Z95 / (2 * total)
    spread = Z95 * math.sqrt(share * (1 - share) / total + Z95 * Z95 / (4 * total * total))
    denominator = 1 + Z95 * Z95 / total
    return (centre - spread) / denominator, (centre + spread) / denominator


def bootstrap_auroc(
    groups: Sequence[Sequence[tuple[float, bool]]], seed: int = 0, resamples: int = 2000
) -> tuple[float, float]:
    """A 95% interval resampling whole states; resamples with one class only are skipped."""
    chooser = random.Random(seed)  # noqa: S311 - a reproducible resample, not a secret
    values = []
    for _ in range(resamples):
        picked = [item for group in chooser.choices(groups, k=len(groups)) for item in group]
        labels = [y for _, y in picked]
        if all(labels) or not any(labels):
            continue
        values.append(auroc([s for s, _ in picked], labels))
    values.sort()
    return values[int(0.025 * len(values))], values[int(0.975 * len(values)) - 1]


def _check(path: Path, expected: str) -> bytes:
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise ValueError(f"{path} has sha256 {actual}, not the frozen {expected}")
    return raw


def _calibration(stats: dict[str, Any], layers: list[Any], device: str) -> dict[str, Any]:
    """Interval scales and the abstention threshold, from the calibration split only."""
    torch = _torch()
    episodes: list[EpisodeArrays] = []
    for path in CALIBRATION:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for entry in manifest["episodes"]:
            episode = read_episode(Path(entry["path"]), entry["transitions_sha256"], entry["seed"])
            episodes.append(episode)
    windows = _Windows(sorted(episodes, key=lambda item: item.seed), device)
    truth = windows.states[:, HISTORY + 1 :]
    mean, std = _ensemble_on(stats, VARIANTS[LEARNED], layers, windows.states, windows.actions)
    scales = _scales(mean, std, truth)
    a, b = STREAM_SLICES["object_position"]
    spread = (std[:, -1, a:b] * scales["object_position"][-1]).pow(2).mean(-1).sqrt().cpu()
    threshold = float(torch.quantile(spread.double(), ABSTAIN_QUANTILE).item())
    return {
        "episodes": len(episodes),
        "windows": len(windows.states),
        "scales": scales,
        "abstain_above_cube_std_m": threshold,
    }


def _windows_of(data: list[dict[str, Any]], device: str) -> tuple[Any, Any]:
    torch = _torch()
    states, actions = [], []
    for state in data:
        for chunk in state["chunks"]:
            states.append(state["history_states"] + chunk["states"][1:])
            actions.append(state["history_actions"] + chunk["actions"])
    return (
        torch.tensor(states, dtype=torch.float32, device=device),
        torch.tensor(actions, dtype=torch.float32, device=device),
    )


def _members(
    stats: dict[str, Any], name: str, layers: list[Any], s: Any, a: Any
) -> tuple[Any, Any]:
    """Each member's predicted 10 steps, and the calibrated-ready std of the ensemble."""
    torch = _torch()
    states = s.unsqueeze(0).expand(MEMBERS, -1, -1, -1)
    actions = a.unsqueeze(0).expand(MEMBERS, -1, -1, -1)
    with torch.no_grad():
        means, log_vars = _rollout(stats, VARIANTS[name], layers, states, actions)
    stacked = torch.stack(means, 2)
    variance = (torch.exp(torch.stack(log_vars, 2)) * stats["delta_std"].pow(2)).mean(0)
    variance = variance + stacked.var(0, unbiased=False)
    return stacked, variance.sqrt()


def _clearance(trajectory: Sequence[Sequence[float]]) -> float:
    """The lowest tool-point height over a trajectory, in metres."""
    return min(tool_point(state[:6])[2] for state in trajectory[1:])


def _score(device: str) -> dict[str, Any]:
    data = _Data(TRAIN_MANIFEST, device, split_holdout)
    stats = {**_stats_of(data), "kinematics": _Kinematics(device)}
    path = ENSEMBLE_RUN / "work" / SEED_HOLDOUT / "carry-contact-beta-fall" / f"seed-{SEED}"
    layers = _load_ensemble(path / "checkpoint.pt", device, EPOCHS)
    calibration = _calibration(stats, layers, device)
    parts = {path: json.loads(_check(path, sha)) for path, sha in BRANCHES.items()}
    states = [state for part in parts.values() for state in part["branches"]]
    in_et_m1_2 = [path == ET_M1_2_RUN for path, part in parts.items() for _ in part["branches"]]
    s, a = _windows_of(states, device)
    learned, learned_std = _members(stats, LEARNED, layers, s, a)
    nominal, _ = _members(stats, NOMINAL, layers, s, a)
    cube = slice(*STREAM_SLICES["object_position"])
    spread = (learned_std[:, -1, cube] * calibration["scales"]["object_position"][-1]).pow(2)
    spread = spread.mean(-1).sqrt().cpu().tolist()
    learned_cpu = learned.cpu().tolist()
    nominal_cpu = nominal[0].cpu().tolist()
    rows = []
    index = 0
    for state, counted in zip(states, in_et_m1_2, strict=True):
        start = state["history_states"][-1]
        chunks = []
        for chunk in state["chunks"]:
            members = [[start, *learned_cpu[m][index]] for m in range(MEMBERS)]
            member_margins = [margins(trajectory) for trajectory in members]
            mean_end = [sum(m[-1][k] for m in members) / MEMBERS for k in range(13)]
            plain = [start, *nominal_cpu[index]]
            chunks.append(
                {
                    "simulated_cost": chunk["cost"],
                    "learned_cost": task_cost(mean_end),
                    "nominal_cost": task_cost(plain[-1]),
                    "violated": chunk["violated"],
                    "learned_violation_score": sum(max(m.values()) for m in member_margins)
                    / MEMBERS,
                    "nominal_violation_score": max(margins(plain).values()),
                    "cube_std_calibrated_m": spread[index],
                    "progress_predicted_m": task_cost(start) - task_cost(mean_end),
                    "progress_simulated_m": task_cost(start) - chunk["cost"],
                    "clearance_predicted_m": min(_clearance(m) for m in members),
                    "clearance_simulated_m": _clearance(chunk["states"]),
                }
            )
            index += 1
        rows.append(
            {
                "episode_id": state["episode_id"],
                "step": state["step"],
                "in_et_m1_2": counted,
                "chunks": chunks,
            }
        )
    ranking = [r for r in rows if r["in_et_m1_2"]]
    result: dict[str, Any] = {"calibration": calibration, "states": rows}
    for model in ("learned", "nominal"):
        right, scored, excluded, contributing = pair_accuracy(
            [
                (
                    [c["simulated_cost"] for c in r["chunks"]],
                    [c[f"{model}_cost"] for c in r["chunks"]],
                )
                for r in ranking
            ]
        )
        result[f"et_m1_2_{model}"] = {
            "right": right,
            "scored_pairs": scored,
            "excluded_pairs": excluded,
            "contributing_states": contributing,
            "accuracy": right / scored,
            "wilson_95": wilson(right, scored),
        }
    every = [c for r in rows for c in r["chunks"]]
    threshold = calibration["abstain_above_cube_std_m"]
    kept = [c for c in every if c["cube_std_calibrated_m"] <= threshold]
    groups = [
        [
            (c["learned_violation_score"], c["violated"])
            for c in r["chunks"]
            if c["cube_std_calibrated_m"] <= threshold
        ]
        for r in rows
    ]
    violations = sum(c["violated"] for c in every)
    abstention = 1 - len(kept) / len(every)
    decidable = violations >= MIN_VIOLATIONS
    kept_auroc = auroc([c["learned_violation_score"] for c in kept], [c["violated"] for c in kept])
    result["et_m1_5"] = {
        "states": len(rows),
        "chunks": len(every),
        "violating_chunks": violations,
        "violating_chunks_kept": sum(c["violated"] for c in kept),
        "abstention_rate": abstention,
        "coverage": 1 - abstention,
        "auroc_kept": kept_auroc,
        "auroc_kept_bootstrap_95": bootstrap_auroc([g for g in groups if g]),
        "auroc_all": auroc(
            [c["learned_violation_score"] for c in every], [c["violated"] for c in every]
        ),
        "nominal_auroc_all": auroc(
            [c["nominal_violation_score"] for c in every], [c["violated"] for c in every]
        ),
        "decidable": decidable,
    }
    learned_ranking = result["et_m1_2_learned"]
    result["verdicts"] = {
        "ET-M1-2": learned_ranking["accuracy"] >= MIN_ACCURACY
        and learned_ranking["contributing_states"] >= MIN_STATES,
        "ET-M1-5": (kept_auroc >= MIN_AUROC and abstention <= MAX_ABSTENTION)
        if decidable
        else "not decidable",
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("mps", "cpu"), default="mps")
    args = parser.parse_args(argv)
    try:
        require_code_root()
        _check(PLAN, PLAN_SHA256)
        check_manifests(CALIBRATION)
        check_not_run(Path("runs"))
        machine = _machine()
        with ledgered_run(
            purpose="WO-005: ET-M1-2 and ET-M1-5 on the simulator branches, once",
            config={
                "plan_sha256": PLAN_SHA256,
                "branches": {str(k): v for k, v in BRANCHES.items()},
            },
            seeds={"bootstrap": 0},
            env_lock={"machine": machine},
        ) as run:
            if run.dirty:
                raise ValueError("commit first, so the code note stays true")
            started = time.perf_counter()
            report: dict[str, Any] = {
                "run": run.directory.name,
                "code": run.code_note,
                "machine": machine,
                **_score(args.device),
            }
            report["seconds"] = time.perf_counter() - started
            text = json.dumps(report, sort_keys=True, allow_nan=False) + "\n"
            partial_file = run.directory / f"{RESULT}.partial"
            partial_file.write_text(text, encoding="utf-8")
            partial_file.replace(run.directory / RESULT)
            run.note = f"verdicts {report['verdicts']}"
            print(run.directory)
    except (ValueError, OSError, KeyError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
