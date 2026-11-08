"""ET-M3-6's physics recordings (WO-022): the evaluation family, F2 and F1s, each gated.

    python -m vishwaroop.synth.et_m3_6_record eval --owner-approval <record_id>
    python -m vishwaroop.synth.et_m3_6_record f2 --owner-approval <record_id>
    python -m vishwaroop.synth.et_m3_6_record f1s --owner-approval <record_id>

Run each from the repository root, in the robotics environment, at a clean commit. Each refuses
unless ``--owner-approval`` names the owner's record that ``et_m3_6_guard.RECORDING`` lists
(``approvals-20261108T081923998845Z-b8daa5a7``), checked by ``require_owner_approval``; unless the
frozen files have their frozen sha256s; and once its result exists. A command that stopped is
resumed with ``--resume-from <its first run>``: seeds already gated are not repeated, and an
episode recorded but not yet gated is gated, not recorded again, once its saved initial state is
checked against its scene snapshot. Every episode is replayed 3 times by the protocol section 4
gate (``m3_gate``) right after it is recorded. A recorded ``insufficient_evidence`` label fails the
gate (the owner vetoed agent detail 1); every skipped seed is listed with its reason, and the
result counts the skipped by reason. Definite failures, planning failures included, are kept when
they pass the replay.

``eval``: ``m3-eval-missed-grasp`` on block 16, ascending from 16000 with exactly
``VARIANTS['missed-grasp']``, until 60 episodes pass the gate, at most to 16099; planning failures
are kept; skipped seeds are listed. Refused once any arm's training has started. If fewer than 60
pass, the run stops (exit 4). Nothing about the kept episodes is printed.

``f2``: from 11000 ascending, one operator episode per scene, alternating lateral-miss, close-high,
lateral-miss, and so on; the lateral-miss sign counts lateral-miss episodes; each episode's
parameters come from ``random.Random(seed)`` (``operators``). Under WO-022's agent detail 2, a
scene that fails the gate adds no episode, and the alternation and the sign count advance over kept
episodes only. Recording stops once the kept episodes' windows reach W* = 4,161; data assembly
drops the last episode's windows past W* from its end. If block 11 runs out first, the run stops
(exit 4).

``f1s``: the nominal scripted demo (``VARIANTS['nominal']``, family ``m3-synth-nominal``) of each of
F2's kept scenes, in F2's order, until the windows reach W*. Under agent detail 3, a scene whose
nominal demo fails the gate is skipped and listed; if F2's scenes run out first, F1s is reported as
unmatched (exit 0; F1s is reported only and is not in the threshold). As the owner asked when
approving detail 3, the result reports F1s's scene overlap with F2 (F2's scenes that F1s used,
skipped and never reached) and F1s's window counts beside F2's.

Exit codes: 0 done, 2 refused, 3 simulator not run, 4 stopped: a WO-022 stop condition, or an
episode whose scene differs from its saved snapshot (``SceneMismatchError``; the seed is named).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..outcome.pickplace import PlaceRubric
from ..sim.baseline import VARIANTS, PlanSettings
from ..sim.env import SimEnv, SimulatorUnavailableError
from ..sim.replay import ReplayInvalidError, ReplayTolerance
from ..sim.runlog import ledgered_run, require_code_root
from .et_m3_6_guard import (
    APPROVALS,
    M0_EXIT_TESTS,
    RECORDING,
    RUNS,
    STATUS,
    GuardRefusalError,
    append_line,
    check_frozen,
    check_not_run,
    check_not_started,
    check_resume,
    code_changed,
    read_lines,
    require_owner_approval,
    write_once,
)
from .m3_gate import UNDECIDED_POLICY, GateResult, gate_tolerance, run_gate
from .m3_record import (
    CLOSE_HIGH_FAMILY,
    EVAL_FAMILY,
    LATERAL_FAMILY,
    NOMINAL_FAMILY,
    Recorded,
    SceneMismatchError,
    Task,
    check_initial_state,
    check_seed,
    episode_id,
    record,
)
from .operators import (
    CLOSE_HIGH_RANGE_M,
    LATERAL_MISS_RANGE_M,
    close_high,
    lateral_miss,
    lateral_sign,
)
from .snapshot import RenderingEnv

HISTORY, HORIZON = 3, 10
WINDOW = HISTORY + HORIZON + 1  # models.compute_pilot.WINDOW; a test checks they agree
W_STAR = 4161
EVAL_SEEDS = range(16000, 16100)
EVAL_COUNT = 60
F2_SEEDS = range(11000, 12000)
EVAL_SETTINGS = VARIANTS["missed-grasp"]
NOMINAL_SETTINGS = VARIANTS["nominal"]
KINDS = ("eval", "f2", "f1s")
STOPPED = 4
OUT = Path("data/derived/m3")
TRAIN_STARTED = "et_m3_6_train_*.plan.json"  # models.et_m3_6_train's start markers


def result_name(kind: str) -> str:
    return f"et_m3_6_{kind}.json"


def plan_name(kind: str) -> str:
    return f"et_m3_6_{kind}.plan.json"


def progress_name(kind: str) -> str:
    return f"et_m3_6_{kind}.progress.jsonl"


def windows_of(steps: int) -> int:
    """Stride-1 windows of ``WINDOW`` states in an episode of ``steps`` actions."""
    return max(steps + 1 - WINDOW + 1, 0)


Choice = tuple[str, PlanSettings, dict[str, Any]]


@dataclass(frozen=True)
class Recording:
    """What one command records: its seeds in order, what runs on each, and when it is done."""

    kind: str
    seeds: Sequence[int]
    choose: Callable[[int, list[dict[str, Any]]], Choice]
    done: Callable[[list[dict[str, Any]]], bool]


def kept_windows(kept: list[dict[str, Any]]) -> int:
    return sum(int(item["windows"]) for item in kept)


def eval_choice(seed: int, _kept: list[dict[str, Any]]) -> Choice:
    return EVAL_FAMILY, EVAL_SETTINGS, {"variant": "missed-grasp"}


def f2_choice(seed: int, kept: list[dict[str, Any]]) -> Choice:
    """The next F2 operator on ``seed``, from the kept episodes so far (agent detail 2)."""
    if len(kept) % 2 == 0:
        k = 1 + sum(1 for item in kept if item["family"] == LATERAL_FAMILY)
        settings = lateral_miss(seed, k)
        d = random.Random(seed).uniform(*LATERAL_MISS_RANGE_M)  # noqa: S311 - the frozen draw
        info = {"operator": "lateral-miss", "k": k, "s": lateral_sign(k), "d_m": d}
        return LATERAL_FAMILY, settings, info
    d = random.Random(seed).uniform(*CLOSE_HIGH_RANGE_M)  # noqa: S311 - the frozen draw
    return CLOSE_HIGH_FAMILY, close_high(seed), {"operator": "close-high", "d_m": d}


def nominal_choice(seed: int, _kept: list[dict[str, Any]]) -> Choice:
    return NOMINAL_FAMILY, NOMINAL_SETTINGS, {"variant": "nominal"}


def eval_sequence() -> Recording:
    return Recording("eval", EVAL_SEEDS, eval_choice, lambda kept: len(kept) >= EVAL_COUNT)


def f2_sequence() -> Recording:
    return Recording("f2", F2_SEEDS, f2_choice, lambda kept: kept_windows(kept) >= W_STAR)


def f1s_sequence(f2_seeds: Sequence[int]) -> Recording:
    return Recording(
        "f1s", list(f2_seeds), nominal_choice, lambda kept: kept_windows(kept) >= W_STAR
    )


def _settings_note(settings: PlanSettings, info: dict[str, Any]) -> str:
    return (
        f"settings {json.dumps(info, sort_keys=True)}; grasp_offset_xy_m "
        f"{list(settings.grasp_offset_xy_m)}, grasp_height_m {settings.grasp_height_m}; "
        "ScriptedPickPlace noise_seed = seed."
    )


def recorded_from_disk(path: Path, family: str, seed: int, note: str, out: Path) -> Recorded:
    """An episode recorded before a stop but not yet gated, read back. Stops (SceneMismatchError)
    if it is not the one this step would record, or if its saved initial state is not its scene
    snapshot's: the check ``m3_record.record`` makes after recording is made again here, so a
    resume never keeps an episode that stopped the first run."""
    manifest = json.loads((path / "episode.json").read_text(encoding="utf-8"))
    if manifest["episode_id"] != episode_id(family, seed) or note not in manifest["notes"]:
        raise SceneMismatchError(f"{path} is not the episode this step records")
    state = (path / manifest["simulator"]["initial_state_artifact"]["path"]).read_bytes()
    state_sha = hashlib.sha256(state).hexdigest()
    check_initial_state(path, seed, state_sha, out)
    notes = str(manifest["notes"])
    error = notes.split("planning_failed: ", 1)[1] if "planning_failed: " in notes else None
    return Recorded(
        path,
        manifest["episode_id"],
        seed,
        family,
        int(manifest["data"]["record_count"]),
        str(manifest["outcome"]["reason"]).split(":", 1)[0],
        error,
        state_sha,
        None,
    )


Recorder = Callable[..., Recorded]
Gate = Callable[[Path, SimEnv, ReplayTolerance, PlaceRubric], GateResult]


def run_sequence(
    sequence: Recording,
    env: RenderingEnv,
    out: Path,
    run_id: str,
    task: Task,
    rubric: PlaceRubric,
    tolerance: ReplayTolerance,
    progress: Path,
    recorder: Recorder = record,
    gate: Gate = run_gate,
) -> dict[str, Any]:
    """Record and gate seed by seed until ``done``, appending one progress line per seed.

    Resumes from ``progress``: its seeds must be the sequence's first seeds, in order, and are not
    repeated. Returns the kept and skipped lines and whether the sequence is complete.
    """
    lines = read_lines(progress)
    seeds = list(sequence.seeds)
    if [line["seed"] for line in lines] != seeds[: len(lines)]:
        raise GuardRefusalError(f"{progress} is not a prefix of the {sequence.kind} seed order")
    kept = [line for line in lines if line["kept"]]
    skipped = [line for line in lines if not line["kept"]]
    for seed in seeds[len(lines) :]:
        if sequence.done(kept):
            break
        family, settings, info = sequence.choose(seed, kept)
        check_seed(family, seed)
        note = _settings_note(settings, info)
        path = Path(out) / episode_id(family, seed)
        print(f"{sequence.kind} seed {seed}", file=sys.stderr, flush=True)
        if path.exists():
            recorded = recorded_from_disk(path, family, seed, note, out)
        else:
            recorded = recorder(env, family, seed, settings, run_id, out, task, rubric, note)
        result = gate(recorded.path, env, tolerance, rubric)
        line = {
            "seed": seed,
            "family": family,
            "settings": info,
            "recorded": recorded.to_json(),
            "gate": result.to_json(),
            "kept": result.passed,
            "windows": windows_of(recorded.steps),
            # The gated bytes: training refuses an episode.json that differs from these.
            "episode_json_sha256": hashlib.sha256(
                (recorded.path / "episode.json").read_bytes()
            ).hexdigest(),
        }
        append_line(progress, line)
        (kept if result.passed else skipped).append(line)
    return {"kept": kept, "skipped": skipped, "complete": sequence.done(kept)}


def windows_used(kept: list[dict[str, Any]], target: int = W_STAR) -> list[int]:
    """Each kept episode's windows that enter the arm: all, but the last episode's past ``target``
    are dropped from its end."""
    used = []
    total = 0
    for item in kept:
        take = max(min(int(item["windows"]), target - total), 0)
        used.append(take)
        total += take
    return used


def f1s_overlap(
    f2: dict[str, Any], kept: list[dict[str, Any]], skipped: list[dict[str, Any]]
) -> dict[str, Any]:
    """How closely F1s matches F2 (owner, 2026-11-08, approving detail 3): F2's kept scenes that
    F1s used, skipped and never reached, and both arms' window counts, reported separately."""
    f2_seeds = [int(item["seed"]) for item in f2["kept"]]
    used = windows_used(kept)
    used_seeds = [int(line["seed"]) for line, take in zip(kept, used, strict=True) if take > 0]
    skipped_seeds = [int(line["seed"]) for line in skipped]
    tried = {int(line["seed"]) for line in kept} | set(skipped_seeds)
    unreached = [seed for seed in f2_seeds if seed not in tried]
    return {
        "f2_scene_count": len(f2_seeds),
        "f1s_scenes_used": used_seeds,
        "f1s_scenes_used_count": len(used_seeds),
        "f1s_scenes_skipped": skipped_seeds,
        "f1s_scenes_skipped_count": len(skipped_seeds),
        "f1s_scenes_unreached": unreached,
        "f1s_scenes_unreached_count": len(unreached),
        "scene_overlap_fraction": len(used_seeds) / len(f2_seeds) if f2_seeds else 0.0,
        "f2_windows_total": f2.get("windows_total"),
        "f2_windows_used_total": f2.get("windows_used_total"),
        "f1s_windows_total": kept_windows(kept),
        "f1s_windows_used_total": sum(used),
        "w_star": W_STAR,
        "f1s_matched": sum(used) == W_STAR,
    }


def summary(kind: str, outcome: dict[str, Any], f2: dict[str, Any] | None = None) -> dict[str, Any]:
    """The result's lists: kept episodes in order with the windows each adds, skipped seeds with
    their reasons and a count by reason; for F1s, its overlap with ``f2``, F2's result."""
    kept, skipped = outcome["kept"], outcome["skipped"]
    out: dict[str, Any] = {
        "kind": kind,
        "complete": outcome["complete"],
        "kept_count": len(kept),
        "skipped_count": len(skipped),
        "skipped": [
            {
                "seed": item["seed"],
                "family": item["family"],
                "reason": item["gate"]["reason"],
                "category": item["gate"].get("category", ""),
            }
            for item in skipped
        ],
        "skipped_by_reason": dict(
            sorted(Counter(item["gate"].get("category", "") for item in skipped).items())
        ),
        "kept": [
            {
                "seed": item["seed"],
                "family": item["family"],
                "episode_id": item["recorded"]["episode_id"],
                "path": item["recorded"]["path"],
                "episode_json_sha256": item["episode_json_sha256"],
                "settings": item["settings"],
            }
            for item in kept
        ],
    }
    if kind != "eval":
        # The evaluation family's labels, lengths and windows stay in its progress log only, unread
        # until scoring; the training families' are listed (labels reported, ET-M3-6 F2).
        for item, line in zip(out["kept"], kept, strict=True):
            item.update(
                label=line["recorded"]["label"],
                planning_error=line["recorded"]["planning_error"],
                steps=line["recorded"]["steps"],
                windows=line["windows"],
            )
        used = windows_used(kept)
        for item, take in zip(out["kept"], used, strict=True):
            item["windows_used"] = take
        out["windows_total"] = kept_windows(kept)
        out["windows_used_total"] = sum(used)
        out["w_star"] = W_STAR
    if kind == "f1s":
        if f2 is None:
            raise GuardRefusalError("F1s's result reports its overlap with F2, so needs F2's")
        out["overlap_with_f2"] = f1s_overlap(f2, kept, skipped)
    return out


def find_result(kind: str, runs_root: Path = RUNS) -> dict[str, Any]:
    """The one completed result of ``kind``; refused if absent, duplicated or incomplete."""
    found = sorted(Path(runs_root).glob(f"*/{result_name(kind)}"))
    if len(found) != 1:
        raise GuardRefusalError(f"{len(found)} {result_name(kind)} results under {runs_root}")
    result: dict[str, Any] = json.loads(found[0].read_text(encoding="utf-8"))
    if kind != "f1s" and not result["complete"]:
        raise GuardRefusalError(f"{found[0]} is a stopped {kind} recording")
    return result


def check_no_training(runs_root: Path = RUNS) -> None:
    """The evaluation family is recorded before any arm is trained."""
    found = sorted(Path(runs_root).glob(f"*/{TRAIN_STARTED}"))
    if found:
        raise GuardRefusalError(
            f"training started in {found[0]}; the evaluation family comes first"
        )


def sequence_for(kind: str, runs_root: Path = RUNS) -> Recording:
    if kind == "eval":
        check_no_training(runs_root)
        return eval_sequence()
    if kind == "f2":
        return f2_sequence()
    f2 = find_result("f2", runs_root)
    return f1s_sequence([item["seed"] for item in f2["kept"]])


def check_f1s_out(f2: dict[str, Any], out: Path) -> None:
    """F1s records on F2's scenes, so it writes where F2 wrote: refuse another ``--out``, whose
    missing snapshots would be taken afresh instead of checked against F2's."""
    for item in f2["kept"]:
        if Path(item["path"]).parent.resolve() != out.resolve():
            raise GuardRefusalError(
                f"F1s --out {out} is not F2's ({Path(item['path']).parent}); F1s must check "
                "F2's scene snapshots"
            )


def _run(args: argparse.Namespace) -> int:
    from ..sim.env import ManiSkillPickCube

    frozen = check_frozen()
    approval = require_owner_approval(args.owner_approval, RECORDING, APPROVALS, STATUS)
    check_not_run(RUNS, result_name(args.kind))
    check_not_started(RUNS, plan_name(args.kind), args.resume_from)
    sequence = sequence_for(args.kind, RUNS)
    f2 = find_result("f2", RUNS) if args.kind == "f1s" else None
    if f2 is not None:
        check_f1s_out(f2, Path(args.out))
    task = Task.from_frozen(json.loads(M0_EXIT_TESTS.read_text(encoding="utf-8")))
    tolerance, rubric = gate_tolerance(M0_EXIT_TESTS)
    config = {"kind": args.kind, "out": str(args.out), "frozen": frozen}
    env = ManiSkillPickCube(
        env_id=task.env_id, max_episode_steps=task.max_episode_steps, render=True
    )
    with ledgered_run(
        purpose=f"WO-022: ET-M3-6 {args.kind} recording, gated (protocol section 4)",
        config={
            **config,
            "owner_approval": approval["record_id"],
            "resume_from": str(args.resume_from),
        },
        seeds={"first": int(sequence.seeds[0]) if len(sequence.seeds) else -1},
        env_lock={"stack": env.stack_identity()},
    ) as run:
        if run.dirty:
            raise GuardRefusalError("commit first, so the code note stays true")
        if args.resume_from is None:
            home = run.directory
            write_once(home / plan_name(args.kind), {"config": config, "commit": run.commit})
        else:
            home = Path(args.resume_from)
            plan = json.loads((home / plan_name(args.kind)).read_text(encoding="utf-8"))
            check_resume(plan, config, code_changed(plan["commit"]))
        started = time.perf_counter()
        outcome = run_sequence(
            sequence, env, args.out, run.directory.name, task, rubric, tolerance,
            home / progress_name(args.kind),
        )  # fmt: skip
        report = {
            "run": run.directory.name,
            "started_in": home.name,
            "code": run.code_note,
            "frozen": frozen,
            "owner_approval": approval["record_id"],
            "undecided_policy": UNDECIDED_POLICY,
            **summary(args.kind, outcome, f2),
            "seconds_this_process": time.perf_counter() - started,
        }
        write_once(run.directory / result_name(args.kind), report)
        stopped = not outcome["complete"] and args.kind != "f1s"
        run.note = (
            f"{args.kind}: {report['kept_count']} kept, {report['skipped_count']} skipped"
            + (", stopped: WO-022 stop condition" if stopped else "")
            + (", unmatched" if args.kind == "f1s" and not outcome["complete"] else "")
        )
        print(run.note)
        print(run.directory)
    return STOPPED if stopped else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=KINDS)
    parser.add_argument("--owner-approval", default=None, help="approvals record id")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--resume-from", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        require_code_root()
        return _run(args)
    except SimulatorUnavailableError as exc:
        print(f"not run: {exc}", file=sys.stderr)
        return 3
    except SceneMismatchError as exc:
        # A designed stop, not a refusal: the run is recorded as failed by ledgered_run, its
        # progress log ends before the seed named here, and nothing about that seed was kept.
        print(f"stopped: SceneMismatchError: {exc}", file=sys.stderr)
        return STOPPED
    except (ReplayInvalidError, ValueError, OSError, KeyError) as exc:
        print(f"refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
