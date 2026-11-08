"""Run a planner on m1-suite-1 for ET-M1-4, or on tuning seeds, resumable by episode (WO-005).

    python -m vishwaroop.planning.suite --planner learned          # the frozen suite
    python -m vishwaroop.planning.suite --planner nominal --tuning --settings <file> \
        --seeds 5000:5010

Run it from the repository root, in the robotics environment. The suite uses the frozen settings
in ``evals/M1-planner-settings.json`` and seeds 9100 to 9299; tuning uses train seeds 5000 to 5049
only. Each episode's result is saved as it finishes. After a stop, commit the run ledger and pass
the stopped run to ``--resume-from``: finished episodes are reused and the rest run. Results go to
``suite.json`` in a new run directory. Exit codes: 0 done, 2 refused, 3 simulator not run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from ..models.compute_pilot import _Data, _machine, _stats_of, _torch
from ..models.cube_study import EPOCHS, _Kinematics
from ..models.device import add_device_argument, require
from ..models.family_sweep import PLAN_FILE, SEED_HOLDOUT, _code_changed, _write_new, check_resume
from ..models.m1_evaluate import ENSEMBLE_RUN, TRAIN_MANIFEST, _load_ensemble
from ..models.pilot_data import split_holdout, state_vector
from ..outcome.pickplace import assess, samples_from_records
from ..scoring.score_branches import _calibration
from ..sim.baseline import ScriptedPickPlace
from ..sim.env import ManiSkillPickCube, Packet, SimulatorUnavailableError
from ..sim.replay import load_frozen
from ..sim.runlog import Run, ledgered_run, require_code_root
from ..sim.so100_kinematics import tool_point
from .cem import Planner, Settings

SUITE_SEEDS = range(9100, 9300)
TUNING_SEEDS = range(5000, 5050)
SETTINGS = Path("evals/M1-planner-settings.json")
SETTINGS_SHA256 = "e5354588f554f966a205f153933d56b27c87ec6e987030750a573a01b7af8f96"
TOLERANCE_FILE = Path("evals/M0-exit-tests.json")
MAX_STEPS = 200
SEED = 0
MODELS = {"learned": "carry-contact-beta-fall-still-reach", "nominal": "nominal-still-reach"}


def parse_seeds(text: str, tuning: bool) -> list[int]:
    """``first:last`` (last excluded) inside the allowed range, or the whole range."""
    allowed = TUNING_SEEDS if tuning else SUITE_SEEDS
    if not text:
        return list(allowed)
    first, last = (int(part) for part in text.split(":"))
    seeds = list(range(first, last))
    if not seeds or seeds[0] not in allowed or seeds[-1] not in allowed:
        raise ValueError(f"seeds {text} are outside {allowed.start} to {allowed.stop - 1}")
    return seeds


def _packets(packet: Packet) -> list[dict[str, Any]]:
    return [{"stream": name, "valid": True, "value": value} for name, value in packet.items()]


def _state(packet: Packet) -> list[float]:
    return state_vector(_packets(packet))


def run_episode(env: Any, seed: int, act: Any) -> dict[str, Any]:
    """One episode: ``act(states, actions, packet, step, seed)`` gives the next action and its
    notes, or ``None`` to stop."""
    packet = env.reset(seed)
    states = [_state(packet)]
    actions: list[list[float]] = []
    records = []
    times = []
    stages: dict[str, int] = {}
    for step in range(MAX_STEPS):
        started = time.perf_counter()
        decided = act(states, actions, packet, step, seed)
        times.append(time.perf_counter() - started)
        if decided is None:
            break
        action, info = decided
        if "stage" in info:
            stages[info["stage"]] = stages.get(info["stage"], 0) + 1
        before = packet
        packet = env.step(action)
        records.append({"observations": _packets(before), "next_observations": _packets(packet)})
        actions.append(list(action))
        states.append(_state(packet))
    _, rubric = load_frozen(TOLERANCE_FILE)
    outcome = assess(samples_from_records(records), rubric)
    return {
        "seed": seed,
        "steps": len(records),
        "success": outcome.success,
        "label": outcome.label,
        "decision_ms_median": 1000 * statistics.median(times) if times else None,
        "decision_ms_max": 1000 * max(times) if times else None,
        "stages": stages,
    }


def _model_actor(planner: Planner) -> Any:
    def act(
        states: list[list[float]],
        actions: list[list[float]],
        _packet: Packet,
        step: int,
        seed: int,
    ) -> Any:
        if step == 0:
            planner.reset(seed)
        last = states[-1]
        history = ([states[0]] * 4 + states)[-4:]
        padded = ([last[:6]] * 3 + actions)[-3:]
        return planner.decide(history, padded, tool_point(last[:6]))

    return act


def _scripted_actor() -> Any:
    controller = ScriptedPickPlace()

    def act(_states: Any, _actions: Any, packet: Packet, step: int, _seed: int) -> Any:
        action = controller(packet, step)
        return None if action is None else (action, {})

    return act


def _settings(args: argparse.Namespace) -> tuple[Settings, str]:
    path = args.settings if args.tuning else SETTINGS
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if not args.tuning and digest != SETTINGS_SHA256:
        raise ValueError(f"{path} has sha256 {digest}, not the frozen {SETTINGS_SHA256}")
    loaded = json.loads(raw)
    values = loaded.get("settings", loaded)
    return Settings(**values), hashlib.sha256(raw).hexdigest()


def _work(args: argparse.Namespace, run: Run, config: dict[str, Any]) -> Path:
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


def _suite(args: argparse.Namespace, env: Any, work: Path, seeds: list[int]) -> dict[str, Any]:
    torch = _torch()
    torch.manual_seed(SEED)
    settings, settings_sha = _settings(args)
    if args.planner == "scripted":
        act = _scripted_actor()
        calibration = None
    else:
        data = _Data(TRAIN_MANIFEST, args.device, split_holdout)
        stats = {**_stats_of(data), "kinematics": _Kinematics(args.device)}
        path = ENSEMBLE_RUN / "work" / SEED_HOLDOUT / "carry-contact-beta-fall" / f"seed-{SEED}"
        layers = _load_ensemble(path / "checkpoint.pt", args.device, EPOCHS)
        calibration = _calibration(stats, layers, args.device)
        scales = calibration["scales"]["object_position"] if args.planner == "learned" else None
        if args.no_penalty:
            scales = None
        planner = Planner(
            stats,
            layers,
            MODELS[args.planner],
            settings,
            env.action_spec.lower,
            env.action_spec.upper,
            scales,
            args.device,
            SEED,
        )
        act = _model_actor(planner)
    episodes = []
    reused = 0
    for seed in seeds:
        finished = work / f"episode-{seed}.json"
        if finished.exists():
            episodes.append(json.loads(finished.read_text(encoding="utf-8")))
            reused += 1
            continue
        print(f"{args.planner} seed {seed}", file=sys.stderr, flush=True)
        if args.planner == "scripted":
            act = _scripted_actor()
        result = run_episode(env, seed, act)
        _write_new(finished, result)
        episodes.append(result)
    successes = sum(item["success"] is True for item in episodes)
    return {
        "planner": args.planner,
        "uncertainty_penalty": args.planner == "learned" and not args.no_penalty,
        "tuning": args.tuning,
        "settings": settings.to_dict(),
        "settings_sha256": settings_sha,
        "calibration": None
        if calibration is None
        else {k: v for k, v in calibration.items() if k != "scales"},
        "episodes": episodes,
        "count": len(episodes),
        "successes": successes,
        "episodes_reused": reused,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--planner", choices=("learned", "nominal", "scripted"), required=True)
    parser.add_argument("--tuning", action="store_true")
    parser.add_argument("--settings", type=Path, default=SETTINGS)
    parser.add_argument("--seeds", default="")
    parser.add_argument("--no-penalty", action="store_true")
    add_device_argument(parser, default="cpu")
    parser.add_argument("--resume-from", type=Path, default=None)
    args = parser.parse_args(argv)
    require(args.device)
    try:
        require_code_root()
        seeds = parse_seeds(args.seeds, args.tuning)
        config = {
            "planner": args.planner,
            "tuning": args.tuning,
            "settings": str(args.settings if args.tuning else SETTINGS),
            "seeds": args.seeds,
            "no_penalty": args.no_penalty,
            "device": args.device,
        }
        env = ManiSkillPickCube(max_episode_steps=MAX_STEPS)
        with ledgered_run(
            purpose=f"WO-005: {'tuning' if args.tuning else 'm1-suite-1, ET-M1-4'}, {args.planner}",
            config={**config, "resume_from": str(args.resume_from)},
            seeds={"torch": SEED},
            env_lock={"machine": _machine(), "stack": env.stack_identity()},
        ) as run:
            if run.dirty:
                raise ValueError("commit first, so the code note stays true")
            work = _work(args, run, config)
            report = {
                "run": run.directory.name,
                "code": run.code_note,
                **_suite(args, env, work, seeds),
            }
            with (run.directory / "suite.json").open("x", encoding="utf-8") as stream:
                json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
                stream.write("\n")
            run.note = f"{args.planner}: {report['successes']} of {report['count']} succeeded"
            print(run.directory)
    except SimulatorUnavailableError as exc:
        print(f"not run: {exc}", file=sys.stderr)
        return 3
    except (ValueError, OSError, KeyError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
