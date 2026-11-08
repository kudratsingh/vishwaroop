"""Score ET-M3-6's physics arms once, on the evaluation family and the no-harm holdout (WO-022).

    python -m vishwaroop.models.et_m3_6_score --owner-approval <record_id>

Run it from the repository root, in the robotics environment, at a clean commit, only when the
owner says so. In WO-022 it always refuses: the owner refused scoring on block 16 and on the
no-harm set until F3's protocol is frozen (``approvals-20261108T081923998845Z-b8daa5a7``), so
``et_m3_6_guard.F3_PROTOCOL`` is ``None`` and ``et_m3_6_guard.SCORING`` lists no approval record.
A later reviewed work order names both. Even then it refuses unless ``--owner-approval`` names that
record (``require_owner_approval``: no substring matching), once a score exists, and once a scoring
has started (its start marker is written before any arm is evaluated, so a crashed scoring is never
run again without an owner decision). It needs every arm F0, F_star, F1, F1s and F2 trained on
seeds 0, 1 and 2, all on ``et_m3_6_train.DEVICE``, each checkpoint matching its recorded sha256 and
the shared normalization statistics. Each model is evaluated as its 3-member
ensemble mean under plain A (``carry-contact-beta-fall-still-reach``) with the predicted flag; the
five baselines are computed once with the base statistics and shared by every arm. The arithmetic
is ``et_m3_6_rule``'s. ET-M3-6 itself is F3's, which is out of WO-022's scope, so this decides no
threshold.

Exit codes: 0 scored, 2 refused.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from ..sim.runlog import ledgered_run, require_code_root
from ..synth import et_m3_6_guard as guard
from ..synth.et_m3_6_guard import (
    APPROVALS,
    RUNS,
    SCORING,
    STATUS,
    GuardRefusalError,
    check_f3_protocol_frozen,
    check_frozen,
    check_not_run,
    require_owner_approval,
    write_once,
)
from ..synth.et_m3_6_record import find_result
from .compute_pilot import HISTORY, WINDOW, _Data, _machine, _stats_of
from .et_m3_6_data import ARMS, M0_MANIFEST, base_split, load_m3_eval, m0_train_entries
from .et_m3_6_rule import score
from .et_m3_6_train import DEVICE, EPOCHS, SEEDS, result_name, stats_digest

PLAIN_A = "carry-contact-beta-fall-still-reach"
BASELINES = ("constant", "linear", "nominal_hold", "nominal_carry", "nominal_carry_fall")
RESULT = "et_m3_6_score.json"
PLAN = "et_m3_6_score.plan.json"
STREAMS = ("joint_position", "object_position")


def trained(runs_root: Path = RUNS) -> dict[str, dict[str, dict[str, Any]]]:
    """Every arm's training result on every seed: exactly one each, refused otherwise."""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for arm in ARMS:
        out[arm] = {}
        for seed in SEEDS:
            found = sorted(Path(runs_root).glob(f"*/{result_name(arm, seed)}"))
            if len(found) != 1:
                raise GuardRefusalError(f"{len(found)} trainings of {arm} on seed {seed}, not 1")
            result = json.loads(found[0].read_text(encoding="utf-8"))
            if result.get("device") != DEVICE:
                raise GuardRefusalError(
                    f"{arm} seed {seed} was trained on {result.get('device')!r}, not {DEVICE}; "
                    "arms trained on different devices are not compared"
                )
            out[arm][str(seed)] = result
    return out


def check_checkpoint(result: dict[str, Any]) -> Path:
    path = Path(result["checkpoint"])
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != result["checkpoint_sha256"]:
        raise GuardRefusalError(
            f"{path} sha256 {digest}, not the trained {result['checkpoint_sha256']}"
        )
    return path


def _streams(rmse: dict[str, list[float]]) -> dict[str, list[float]]:
    return {stream: rmse[stream] for stream in STREAMS}


def _evaluate(
    device: str, results: dict[str, Any], eval_kept: list[dict[str, Any]]
) -> dict[str, Any]:
    from .cube_study import VARIANTS, _baseline_predictions, _Kinematics
    from .m1_evaluate import _ensemble_on, _load_ensemble, _stream_rmse, _Windows

    m0_train_entries(M0_MANIFEST)
    data = _Data(M0_MANIFEST, device, base_split)
    stats = {**_stats_of(data), "kinematics": _Kinematics(device)}
    digest = stats_digest(stats)
    for arm, seeds in results.items():
        for seed, result in seeds.items():
            if result["stats_sha256"] != digest:
                raise GuardRefusalError(f"{arm} seed {seed} was trained with other statistics")
    evaluation = _Windows(load_m3_eval(eval_kept), device)
    sets = {
        "evaluation_family": (evaluation.states, evaluation.actions),
        "no_harm": (data.holdout_s, data.holdout_a),
    }
    baselines: dict[str, Any] = {}
    for name, (states, actions) in sets.items():
        view = copy.copy(data)
        view.holdout_s, view.holdout_a = states, actions
        truth = states[:, HISTORY + 1 :]
        predictions = _baseline_predictions(view, stats)
        baselines[name] = {
            base: _streams(_stream_rmse(predictions[base], truth)) for base in BASELINES
        }
    tables: dict[str, dict[str, Any]] = {name: {} for name in sets}
    for arm, seeds in results.items():
        for name in sets:
            tables[name][arm] = {}
        for seed, result in seeds.items():
            print(f"{arm} seed {seed}", file=sys.stderr, flush=True)
            layers = _load_ensemble(check_checkpoint(result), device, EPOCHS)
            for name, (states, actions) in sets.items():
                mean, _ = _ensemble_on(stats, VARIANTS[PLAIN_A], layers, states, actions)
                truth = states[:, HISTORY + 1 :]
                tables[name][arm][seed] = _streams(_stream_rmse(mean, truth))
    return {
        "windows": {"evaluation_family": len(evaluation.states), "no_harm": len(data.holdout_s)},
        "episodes": {"evaluation_family": len(eval_kept), "no_harm": data.holdout_episodes},
        "baselines": baselines,
        "rmse": tables,
        "stats_sha256": digest,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-approval", default=None, help="approvals record id")
    parser.add_argument("--device", choices=("mps", "cpu"), default="mps")
    args = parser.parse_args(argv)
    try:
        require_code_root()
        frozen = check_frozen()
        f3_protocol = check_f3_protocol_frozen(guard.F3_PROTOCOL, STATUS)
        approval = require_owner_approval(args.owner_approval, SCORING, APPROVALS, STATUS)
        check_not_run(RUNS, RESULT)
        started_before = sorted(Path(RUNS).glob(f"*/{PLAN}"))
        if started_before:
            raise GuardRefusalError(
                f"{started_before[0]} exists: a scoring started there; block 16 is evaluated once, "
                "so it is not run again without the owner's decision"
            )
        results = trained(RUNS)
        eval_kept = find_result("eval", RUNS)["kept"]
        machine = _machine()
        with ledgered_run(
            purpose="WO-022: ET-M3-6 physics arms scored once on block 16 (owner-approved)",
            config={
                "frozen": frozen,
                "f3_protocol": f3_protocol,
                "owner_approval": approval["record_id"],
                "device": args.device,
            },
            seeds={"none": 0},
            env_lock={"machine": machine},
        ) as run:
            if run.dirty:
                raise GuardRefusalError("commit first, so the code note stays true")
            # Written before any arm is evaluated: a scoring that stops is not started again.
            write_once(run.directory / PLAN, {"commit": run.commit, "device": args.device})
            started = time.perf_counter()
            measured = _evaluate(args.device, results, eval_kept)
            rmse = measured["rmse"]
            report = {
                "run": run.directory.name,
                "code": run.code_note,
                "machine": machine,
                "frozen": frozen,
                "f3_protocol": f3_protocol,
                "owner_approval": approval["record_id"],
                "training_device": DEVICE,
                "model": f"{PLAIN_A} with the predicted flag, 3-member ensemble mean",
                "window": WINDOW,
                **measured,
                "rule": score(
                    rmse["evaluation_family"], rmse["no_harm"], measured["baselines"]["no_harm"]
                ),
                "training": {
                    arm: {
                        seed: {"run": result["run"], "data": result["data"]}
                        for seed, result in seeds.items()
                    }
                    for arm, seeds in results.items()
                },
                "seconds": time.perf_counter() - started,
            }
            write_once(run.directory / RESULT, report)
            run.note = f"ET-M3-6 physics arms scored; {report['rule']['et_m3_6']}"
            print(run.directory)
    except (ValueError, OSError, KeyError) as exc:
        print(f"refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
