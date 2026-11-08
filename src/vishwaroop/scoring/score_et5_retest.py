"""Score ET-M1-5 once more, on fresh states, with calibration from perturbed chunks (WO-016).

    python -m vishwaroop.scoring.score_et5_retest

Run it from the repository root, in the robotics environment. Rules: ``evals/M1-et5-retest.json``,
which changes only where the scales and the abstention threshold come from: branches of the
calibration split, every chunk kind included. The scorer, violation rule and verdict are WO-005's.
It refuses changed inputs and a second scoring. Results go to ``et5_retest.json`` in a new run
directory. Exit codes: 0 scored, pass or fail; 2 refused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from ..models.compute_pilot import MEMBERS, STREAM_SLICES, _Data, _machine, _stats_of, _torch
from ..models.cube_study import EPOCHS, _Kinematics
from ..models.device import add_device_argument, require
from ..models.family_sweep import SEED_HOLDOUT
from ..models.m1_evaluate import ENSEMBLE_RUN, TRAIN_MANIFEST, _load_ensemble, _scales
from ..models.pilot_data import split_holdout
from ..sim.runlog import ledgered_run, require_code_root
from .score_branches import (
    ABSTAIN_QUANTILE,
    LEARNED,
    MAX_ABSTENTION,
    MIN_AUROC,
    MIN_VIOLATIONS,
    NOMINAL,
    SEED,
    _members,
    _windows_of,
    auroc,
    bootstrap_auroc,
)
from .violations import margins

RULES = Path("evals/M1-et5-retest.json")
RULES_SHA256 = "aa9c128a46be3219d5194bef3a65969689537b8a8779944a860f18baeff7ebcb"
CALIBRATION_BRANCHES = Path("runs/20261102T120807Z_2f1c5a1b/branches.json")
CALIBRATION_SHA256 = "cb76b15d4ec43f3fb3503d0440b50f887f6c6f56d89e50add7556987bbfeaefe"
EVALUATION_BRANCHES = Path("runs/20261102T120907Z_a102fd9a/branches.json")
EVALUATION_SHA256 = "0121862d2f2720d13a209af8a7e70c92935363fe784f08fe80a308cc100b8d36"
RESULT = "et5_retest.json"


def check_not_run(runs_root: Path) -> None:
    found = sorted(runs_root.glob(f"*/{RESULT}*"))
    if found:
        raise ValueError(f"already scored in {found[0]}; the rules allow one scoring")


def load_checked(path: Path, expected: str) -> dict[str, Any]:
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise ValueError(f"{path} has sha256 {actual}, not the frozen {expected}")
    loaded: dict[str, Any] = json.loads(raw)
    return loaded


def cube_spread(std: Any, scale: float) -> list[float]:
    """Calibrated cube std at the last step: root mean square over x, y, z, times the scale."""
    a, b = STREAM_SLICES["object_position"]
    values: list[float] = (std[:, -1, a:b] * scale).pow(2).mean(-1).sqrt().cpu().tolist()
    return values


def calibrate(
    stats: dict[str, Any], layers: list[Any], states: list[Any], device: str
) -> dict[str, Any]:
    """Scales and the abstention threshold from the calibration branches, every chunk kind."""
    torch = _torch()
    s, a = _windows_of(states, device)
    predicted, std = _members(stats, LEARNED, layers, s, a)
    scales = _scales(predicted.mean(0), std, s[:, 4:])
    spread = cube_spread(std, scales["object_position"][-1])
    threshold = float(torch.quantile(torch.tensor(spread, dtype=torch.float64), ABSTAIN_QUANTILE))
    return {
        "states": len(states),
        "chunks": len(spread),
        "scales": scales,
        "abstain_above_cube_std_m": threshold,
    }


def _score(device: str) -> dict[str, Any]:
    data = _Data(TRAIN_MANIFEST, device, split_holdout)
    stats = {**_stats_of(data), "kinematics": _Kinematics(device)}
    path = ENSEMBLE_RUN / "work" / SEED_HOLDOUT / "carry-contact-beta-fall" / f"seed-{SEED}"
    layers = _load_ensemble(path / "checkpoint.pt", device, EPOCHS)
    calibration_states = load_checked(CALIBRATION_BRANCHES, CALIBRATION_SHA256)["branches"]
    calibration = calibrate(stats, layers, calibration_states, device)
    states = load_checked(EVALUATION_BRANCHES, EVALUATION_SHA256)["branches"]
    s, a = _windows_of(states, device)
    learned, learned_std = _members(stats, LEARNED, layers, s, a)
    nominal, _ = _members(stats, NOMINAL, layers, s, a)
    spread = cube_spread(learned_std, calibration["scales"]["object_position"][-1])
    learned_cpu = learned.cpu().tolist()
    nominal_cpu = nominal[0].cpu().tolist()
    threshold = calibration["abstain_above_cube_std_m"]
    chunks: list[dict[str, Any]] = []
    groups: list[list[tuple[float, bool]]] = []
    index = 0
    for state in states:
        start = state["history_states"][-1]
        group = []
        for number, chunk in enumerate(state["chunks"]):
            members = [[start, *learned_cpu[m][index]] for m in range(MEMBERS)]
            score = sum(max(margins(m).values()) for m in members) / MEMBERS
            row = {
                "episode_id": state["episode_id"],
                "chunk": number,
                "violated": chunk["violated"],
                "learned_violation_score": score,
                "nominal_violation_score": max(margins([start, *nominal_cpu[index]]).values()),
                "cube_std_calibrated_m": spread[index],
                "kept": spread[index] <= threshold,
            }
            chunks.append(row)
            if row["kept"]:
                group.append((score, chunk["violated"]))
            index += 1
        groups.append(group)
    kept = [c for c in chunks if c["kept"]]
    labels = [c["violated"] for c in chunks]
    kept_labels = [c["violated"] for c in kept]
    violations = sum(labels)
    abstention = 1 - len(kept) / len(chunks)
    decidable = violations >= MIN_VIOLATIONS and any(kept_labels) and not all(kept_labels)
    kept_auroc = (
        auroc([c["learned_violation_score"] for c in kept], kept_labels) if decidable else None
    )
    by_kind = {
        str(k): sum(not c["kept"] for c in chunks if c["chunk"] == k)
        / sum(c["chunk"] == k for c in chunks)
        for k in range(4)
    }
    return {
        "calibration": calibration,
        "states": len(states),
        "chunks": len(chunks),
        "violating_chunks": violations,
        "violating_chunks_kept": sum(kept_labels),
        "abstention_rate": abstention,
        "abstention_by_chunk_kind": by_kind,
        "auroc_kept": kept_auroc,
        "auroc_kept_bootstrap_95": bootstrap_auroc([g for g in groups if g]) if decidable else None,
        "auroc_all": auroc([c["learned_violation_score"] for c in chunks], labels),
        "nominal_auroc_kept": (
            auroc([c["nominal_violation_score"] for c in kept], kept_labels) if decidable else None
        ),
        "nominal_auroc_all": auroc([c["nominal_violation_score"] for c in chunks], labels),
        "per_chunk": chunks,
        "verdict": (
            (kept_auroc is not None and kept_auroc >= MIN_AUROC and abstention <= MAX_ABSTENTION)
            if decidable
            else "not decidable"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_device_argument(parser, default="mps")
    args = parser.parse_args(argv)
    require(args.device)
    try:
        require_code_root()
        load_checked(RULES, RULES_SHA256)
        check_not_run(Path("runs"))
        machine = _machine()
        with ledgered_run(
            purpose="WO-016: ET-M1-5 retest, scored once",
            config={"rules_sha256": RULES_SHA256},
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
            run.note = f"ET-M1-5 retest: {report['verdict']}"
            print(run.directory)
    except (ValueError, OSError, KeyError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
