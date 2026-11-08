"""WO-020: family-holdout gaps under plain A, reproduced under a frozen protocol, and M3's target.

    python -m vishwaroop.models.m3_remeasure

Run it from the repository root, in the robotics environment, at a clean commit. The protocol is
``evals/M3-remeasure.json``. It re-evaluates WO-004's family-holdout ensembles with plain A, checks
every reduction against WO-005 stage 0's within 1e-6, and only then applies the frozen target rule.
It refuses a changed protocol and a second run once a result exists. Exit codes: 0 done, 2 refused
or the reproduction check failed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from ..sim.runlog import ledgered_run, require_code_root
from .compute_pilot import _machine
from .device import add_device_argument, require
from .m1_followups import TRAIN_FAMILIES, _train_side

PROTOCOL = Path("evals/M3-remeasure.json")
PROTOCOL_SHA256 = "133ae3c484868b4747ecc42d639a23c4d9b6f6bd7abe982ff857f373a9deada7"
REFERENCE = Path("runs/20261102T085542Z_4764e650/m1_followups_v2.json")
PLAIN_A = "carry-contact-beta-fall-still-reach"
RESULT = "m3_remeasure.json"
FAILURE = "m3_remeasure_failed.json"
STREAMS = ("joint_position", "object_position")
CANDIDATES = ("m0-scripted-missed-grasp", "m0-scripted-early-release")
TOLERANCE = 1e-6
TIE = 1e-9
BAR = 0.20


def check_protocol(path: Path = PROTOCOL, expected: str = PROTOCOL_SHA256) -> None:
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f"{path} has sha256 {actual}, not the frozen {expected}")


def check_not_run(runs_root: Path) -> None:
    found = sorted(runs_root.glob(f"*/{RESULT}*"))
    if found:
        raise ValueError(f"already run in {found[0]}; the protocol allows one result")


def mismatches(new: dict[str, Any], reference: dict[str, Any]) -> list[str]:
    """Every (family, seed, stream, horizon) whose plain A reduction moved by more than 1e-6."""
    out = []
    for family in TRAIN_FAMILIES:
        for seed, cell in reference[family]["seeds"].items():
            for stream in STREAMS:
                old = cell["reductions"]["after"][stream]
                now = new[family]["seeds"][seed]["reductions"]["after"][stream]
                if len(old) != len(now):
                    out.append(f"{family} seed {seed} {stream}: horizons differ")
                    continue
                for h, (a, b) in enumerate(zip(old, now, strict=True)):
                    if abs(a - b) > TOLERANCE:
                        out.append(f"{family} seed {seed} {stream} h{h + 1}: {a} then {b}")
    return out


def worst(family: dict[str, Any]) -> dict[str, Any]:
    """W(F): the minimum reduction over seeds, streams and horizons, and where it is."""
    best: dict[str, Any] = {"value": float("inf")}
    for seed, cell in sorted(family["seeds"].items()):
        for stream in STREAMS:
            for h, value in enumerate(cell["reductions"]["after"][stream]):
                if value < best["value"]:
                    best = {"value": value, "seed": seed, "stream": stream, "horizon": h + 1}
    return best


def target(w: dict[str, float]) -> str:
    """The frozen rule: lower W wins; both at least 20% means weaker motivation; ties to missed."""
    missed, early = w[CANDIDATES[0]], w[CANDIDATES[1]]
    if missed >= BAR and early >= BAR:
        return "weaker motivation: both families clear 20%"
    if abs(missed - early) <= TIE:
        return CANDIDATES[0]
    return CANDIDATES[0] if missed < early else CANDIDATES[1]


def where(family: dict[str, Any], spot: dict[str, Any]) -> dict[str, Any]:
    """The worst value's stream by phase, at its horizon and seed: model RMSE per phase."""
    cell = family["seeds"][spot["seed"]]
    table = cell[
        "joint_rmse_by_phase" if spot["stream"] == "joint_position" else "cube_rmse_by_phase"
    ]
    by_phase = table["after"]
    h = spot["horizon"] - 1
    return {
        "unit": "rad, per coordinate"
        if spot["stream"] == "joint_position"
        else "m, per coordinate",
        "model_rmse_by_phase": {phase: values[h] for phase, values in by_phase.items()},
        "windows_by_phase": family["windows_by_phase"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_device_argument(parser, default="mps")
    args = parser.parse_args(argv)
    require(args.device)
    try:
        require_code_root()
        check_protocol()
        check_not_run(Path("runs"))
        reference = json.loads(REFERENCE.read_text(encoding="utf-8"))["train_side"]
        machine = _machine()
        with ledgered_run(
            purpose="WO-020: family-holdout gaps under plain A, reproduced, and M3's target",
            config={"protocol_sha256": PROTOCOL_SHA256, "device": args.device},
            seeds={"none": 0},
            env_lock={"machine": machine},
        ) as run:
            if run.dirty:
                raise ValueError("commit first, so the code note stays true")
            started = time.perf_counter()
            new = _train_side(args.device, PLAIN_A)
            moved = mismatches(new, reference)
            if moved:
                failure = {"run": run.directory.name, "mismatches": moved[:50], "count": len(moved)}
                (run.directory / FAILURE).write_text(json.dumps(failure, indent=2) + "\n")
                raise ValueError(f"reproduction check failed on {len(moved)} values")
            spots = {family: worst(new[family]) for family in TRAIN_FAMILIES}
            chosen = target({family: spots[family]["value"] for family in CANDIDATES})
            report = {
                "run": run.directory.name,
                "code": run.code_note,
                "machine": machine,
                "protocol_sha256": PROTOCOL_SHA256,
                "reproduced_values": 7 * 3 * 2 * 10,
                "worst_by_family": spots,
                "target": chosen,
                "where_the_target_error_sits": where(new[chosen], spots[chosen])
                if chosen in CANDIDATES
                else None,
                "train_side": {family: new[family] for family in TRAIN_FAMILIES},
                "seconds": time.perf_counter() - started,
            }
            text = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
            partial = run.directory / f"{RESULT}.partial"
            partial.write_text(text, encoding="utf-8")
            partial.replace(run.directory / RESULT)
            run.note = f"target {chosen}"
            print(run.directory)
    except (ValueError, OSError, KeyError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
