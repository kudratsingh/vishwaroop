"""ET-M3-1: the tolerance pilot, then one scoring of the scene-consistency checker.

    python -m vishwaroop.synth.et_m3_1 pilot
    python -m vishwaroop.synth.et_m3_1 score

Run it from the repository root, in the robotics environment, at a clean commit. Both are ledgered
runs and both refuse changed frozen files: ``evals/M3-protocol-4.json``, which replaces ET-M3-1,
and what it builds on (``evals/M3-protocol-3.json``, ``evals/M3-protocol.md``,
``evals/M3-exit-tests.json``, ``evals/M3-protocol-2.json``,
``src/vishwaroop/sim/so100_kinematics.py``), and ``evals/M0-exit-tests.json``.

``pilot`` snapshots and renders block 10 seeds 10940 to 10959 (even seeds nominal, odd seeds the
operators), measures every frame, finds each candidate's size-checkable frames, computes each
scene's goal geometry and the whole-pixel image shifts of a 0.03 m goal move, and writes
``evals/M3-checker-tolerances-p4.json`` once by the frozen rule, printing its sha256 for the
status ledger. If any of the freeze's ten stop conditions holds (``checker.pilot_tolerances``
lists them all), it writes nothing to ``evals/`` and exits 4, so that the owner is told before any
candidate is generated. A snapshot without an exposed render camera refuses the run (exit 2)
before any result is written.

``score`` refuses unless the tolerances file's sha256 is recorded in ``work_orders/STATUS.jsonl``
and no score exists. It builds the 60 controls (seeds 10320 to 10379) and the 60 injections (seeds
10460 to 10519, each into its own unmodified source candidate; a cube-resize source without a
size-checkable frame 1 to T - 1 is replaced from 10260 up to 10299; type 6 uses the render of
seed + 270), runs the checker once on each source, injection and control, applies the threshold
with the injection-credit rule, and writes ``et_m3_1_score_p4.json`` once. For every control and
source it also records, for reporting only, the simulator's final cube position, whether it is over
the table, whether it projects inside the image, and the scene's goal guarantee level. Snapshots
are written once into the run directory; frames stay in memory, one candidate at a time.

Exit codes: 0 done (whatever the verdict), 2 refused, 3 simulator not run, 4 the pilot stopped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

from ..sim.env import ManiSkillPickCube, SimulatorUnavailableError
from ..sim.replay import ReplayInvalidError, require_frozen_file
from ..sim.runlog import ledgered_run, require_code_root
from .checker import (
    CONTROL_SEEDS,
    GOAL_MOVE_MIN_M,
    GOAL_SHIFT_DIRECTIONS_DEG,
    PILOT_SEEDS,
    SMALLEST_DUPLICATE_OFFSET_PX,
    TOLERANCES_PATH,
    PilotCandidate,
    PilotStopError,
    Tolerances,
    camera_position,
    check_candidate,
    first_frame_difference,
    goal_geometry,
    guarantee_level,
    load_tolerances,
    measure,
    pilot_tolerances,
    reference,
    sightline_clearance,
    size_checkable_frames,
    table_placement,
    verdict,
)
from .operators import EpisodeKind, et_m3_1_episodes
from .snapshot import (
    RenderedEpisode,
    RenderingEnv,
    Snapshot,
    SnapshotError,
    projection_matrix,
    render_episode,
    take_snapshot,
    write_snapshot,
)

FROZEN = {
    Path("evals/M3-protocol-4.json"): (
        "52508a87852607ec4431d0bc70c8d36bca6b529b6115270373e769c2401f5c2e"
    ),
    Path("evals/M3-protocol-3.json"): (
        "1671e0597251e0c85b2616bdf333c96d7f8635c526ea88df89dc7564de6c556c"
    ),
    Path("evals/M3-protocol-2.json"): (
        "36b5135a45c645502013c9271cbfe05d030795df631da4c887c4455f4b907a46"
    ),
    Path("src/vishwaroop/sim/so100_kinematics.py"): (
        "c36d06206fa0f0f47ee3f975c79697e44a9f760235ab68a1a32148f853a3ac5f"
    ),
    Path("evals/M3-exit-tests.json"): (
        "2e35a50397b1c97919cb0be7d31b09b374d3fd0f0564741090b93c5e31e8f2d4"
    ),
    Path("evals/M3-protocol.md"): (
        "34ac1338b97d732f3de66f30e83227778af5360117df7674b21dce7dc253ea34"
    ),
}
M0_EXIT_TESTS = Path("evals/M0-exit-tests.json")
STATUS_LEDGER = Path("work_orders/STATUS.jsonl")
RUNS = Path("runs")
PILOT_RESULT = "et_m3_1_pilot_p4.json"
SCORE_RESULT = "et_m3_1_score_p4.json"
SNAPSHOTS = "snapshots"
STOPPED = 4
FIRST_INJECTION_SEED = 10460  # inject.FIRST_SEED; inject needs numpy, so it is imported late


def check_frozen(frozen: dict[Path, str] = FROZEN) -> dict[str, str]:
    """Refuse unless every frozen file has its frozen sha256."""
    for path, expected in frozen.items():
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"{path} has sha256 {actual}, not the frozen {expected}")
    return {str(path): digest for path, digest in frozen.items()}


def check_not_run(runs_root: Path, result: str) -> None:
    """Refuse a second run once a result, or its partial file, exists in any run directory."""
    found = sorted(Path(runs_root).glob(f"*/{result}*"))
    if found:
        raise ValueError(f"already run in {found[0]}; ET-M3-1 allows one {result}")


def check_recorded(digest: str, status_ledger: Path = STATUS_LEDGER) -> None:
    """Refuse unless a status-ledger note records the tolerances file with this sha256."""
    for line in Path(status_ledger).read_text(encoding="utf-8").splitlines():
        note = json.loads(line).get("note", "")
        if TOLERANCES_PATH.name in note and digest in note:
            return
    raise ValueError(
        f"{TOLERANCES_PATH} sha256 {digest} is not recorded in {status_ledger}; record it before "
        "any control or injection is generated"
    )


def _task() -> tuple[str, str, int]:
    require_frozen_file(M0_EXIT_TESTS)
    task = json.loads(M0_EXIT_TESTS.read_text(encoding="utf-8"))["task"]
    return task["env_id"], task["version"], int(task["max_episode_steps"])


def _write_once(path: Path, value: dict[str, Any]) -> None:
    text = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    partial = path.with_name(f"{path.name}.partial")
    with partial.open("x", encoding="utf-8") as stream:
        stream.write(text)
    partial.replace(path)


def _scene(env: RenderingEnv, seed: int, task: tuple[str, str, int], run_dir: Path) -> Snapshot:
    snapshot = take_snapshot(env, seed, task[0], task[1])
    write_snapshot(snapshot, run_dir / SNAPSHOTS / f"seed-{seed:06d}")
    return snapshot


def _size_frames(snapshot: Snapshot, rendered: RenderedEpisode) -> int:
    """The candidate's size-checkable frames, from its scene's initial joint and cube positions,
    the render camera's centre, and its actions; never from a frame."""
    return size_checkable_frames(
        rendered.initial_joints,
        rendered.initial_cube,
        camera_position(snapshot.manifest),
        rendered.actions,
    )


def goal_shifts(snapshot_manifest: dict[str, Any]) -> dict[str, Any]:
    """The image shift of the scene's goal moved 0.03 m in the world xy plane, one per direction
    every 1 degree, from the render camera's projection: as the whole-pixel (row, column) shift a
    type-4 goal-pixel injection applies (``shifts``, rounded half up, as inject.goal_pixel_shift),
    with the smallest whole-pixel and unrounded norms for the record. Refuses a snapshot without
    an exposed camera."""
    from .inject import project

    projection = projection_matrix(snapshot_manifest)
    goal = [float(value) for value in snapshot_manifest["goal_position"]]
    row0, col0 = project(projection, (goal[0], goal[1], goal[2]))
    shifts = []
    exact = []
    for degrees in GOAL_SHIFT_DIRECTIONS_DEG:
        angle = math.radians(degrees)
        moved = (
            goal[0] + GOAL_MOVE_MIN_M * math.cos(angle),
            goal[1] + GOAL_MOVE_MIN_M * math.sin(angle),
            goal[2],
        )
        row1, col1 = project(projection, moved)
        exact.append(math.hypot(row1 - row0, col1 - col0))
        shifts.append((math.floor(row1 - row0 + 0.5), math.floor(col1 - col0 + 0.5)))
    return {
        "shifts": shifts,
        "smallest_whole_pixel_px": min(math.hypot(dr, dc) for dr, dc in shifts),
        "smallest_exact_px": min(exact),
    }


def goal_report(snapshot: Snapshot) -> dict[str, Any]:
    """For reporting only: the scene's projected goal radius, smallest 0.03 m shift and guarantee
    level (``checker.guarantee_level``)."""
    _, radius = goal_geometry(snapshot.manifest)
    smallest = goal_shifts(snapshot.manifest)["smallest_whole_pixel_px"]
    return {
        "goal_radius_px": radius,
        "goal_smallest_shift_px": smallest,
        "goal_guarantee_level": guarantee_level(radius, smallest),
    }


def final_cube(snapshot: Snapshot, rendered: RenderedEpisode) -> dict[str, Any]:
    """For reporting only: the simulator's cube position at frame T, where it is relative to the
    table (``checker.table_placement``), and whether it projects inside the image. It never fails
    a run: an error is recorded in the result instead, since nothing in the verdict reads it."""
    from .inject import InjectionError, project

    try:
        position = [float(value) for value in rendered.cube_positions[-1]]
        placement = table_placement(position, float(snapshot.manifest["cube_half_size_m"]))
        inside = False
        try:
            row, col = project(
                projection_matrix(snapshot.manifest), (position[0], position[1], position[2])
            )
        except InjectionError:
            pixel = None
        else:
            pixel = [row, col]
            height, width = snapshot.render.shape[:2]
            inside = 0 <= row < height and 0 <= col < width
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    return {
        "position_m": position,
        **placement,
        "pixel": pixel,
        "projects_inside_image": inside,
    }


def _episode_note(episode: EpisodeKind, steps: int, planning_error: str | None) -> dict[str, Any]:
    return {**episode.to_json(), "T": steps, "planning_error": planning_error}


def run_pilot(env: RenderingEnv, task: tuple[str, str, int], run_dir: Path) -> dict[str, Any]:
    """Snapshot, render and measure every pilot candidate. Returns the measurements and episodes."""
    candidates = []
    episodes = []
    for episode in et_m3_1_episodes(PILOT_SEEDS):
        print(f"pilot seed {episode.seed} {episode.kind}", file=sys.stderr, flush=True)
        snapshot = _scene(env, episode.seed, task, run_dir)
        camera = camera_position(snapshot.manifest)  # refuses an unexposed camera before simulating
        goal = goal_geometry(snapshot.manifest)
        shift = goal_shifts(snapshot.manifest)
        rendered = render_episode(env, snapshot, episode, task[2])
        start = rendered.initial_cube
        candidates.append(
            PilotCandidate(
                seed=episode.seed,
                snapshot=measure(snapshot.render),
                frames=tuple(measure(frame) for frame in rendered.frames),
                first_difference=first_frame_difference(rendered.frames[0], snapshot.render),
                size_frames=_size_frames(snapshot, rendered),
                cube_displacement_m=tuple(
                    math.dist(cube, start) for cube in rendered.cube_positions
                ),
                actual_clearance_m=tuple(
                    sightline_clearance(joints, camera, start)
                    for joints in rendered.joint_positions
                ),
                goal=goal,
                goal_shifts=tuple(shift["shifts"]),
            )
        )
        episodes.append(
            {
                **_episode_note(episode, rendered.steps, rendered.planning_error),
                "size_checkable_frames": candidates[-1].size_frames,
                "cube_positions": rendered.cube_positions,
                "actual_clearance_m": list(candidates[-1].actual_clearance_m),
                "goal": {
                    "projected_centre": list(goal[0]),
                    "projected_radius_px": goal[1],
                    "smallest_whole_pixel_shift_px": shift["smallest_whole_pixel_px"],
                    "smallest_exact_shift_px": shift["smallest_exact_px"],
                },
                "final_cube": final_cube(snapshot, rendered),
            }
        )
    return {"candidates": candidates, "episodes": episodes}


def _check(
    snapshot: Snapshot,
    manifest: dict[str, Any],
    frames: list[Any],
    tolerances: Tolerances,
    size_frames: int,
) -> dict[str, Any]:
    ref = reference(snapshot.manifest, measure(snapshot.render), snapshot.render.shape, tolerances)
    return check_candidate(
        manifest, frames, ref, snapshot.render, tolerances, size_frames
    ).to_json()


def run_score(
    env: RenderingEnv, task: tuple[str, str, int], run_dir: Path, tolerances: Tolerances
) -> dict[str, Any]:
    """Build and check the 60 controls and 60 injections, one candidate at a time."""
    from .inject import (
        RENDER_SEED_OFFSET,
        RESIZE_REPLACEMENT_SEEDS,
        TYPES,
        InjectionError,
        inject,
        injection_plan,
    )

    controls = []
    for episode in et_m3_1_episodes(CONTROL_SEEDS):
        print(f"control seed {episode.seed} {episode.kind}", file=sys.stderr, flush=True)
        snapshot = _scene(env, episode.seed, task, run_dir)
        rendered = render_episode(env, snapshot, episode, task[2])
        size_frames = _size_frames(snapshot, rendered)
        result = _check(
            snapshot, snapshot.candidate_manifest(), rendered.frames, tolerances, size_frames
        )
        controls.append(
            {
                **_episode_note(episode, rendered.steps, rendered.planning_error),
                **result,
                **goal_report(snapshot),
                "final_cube": final_cube(snapshot, rendered),
            }
        )
    plan = injection_plan()
    sources = {item.seed: item for item in et_m3_1_episodes([seed for _, _, seed in plan])}
    injections = []
    replacements = iter(RESIZE_REPLACEMENT_SEEDS)
    # replacement seeds are one ascending sequence, so F2's lateral-miss count runs over all of them
    replacement_kinds = {item.seed: item for item in et_m3_1_episodes(RESIZE_REPLACEMENT_SEEDS)}
    for t, i, frozen_seed in plan:
        seed: int | None = frozen_seed
        skipped: list[dict[str, Any]] = []
        while seed is not None:
            episode = sources[seed] if seed == frozen_seed else replacement_kinds[seed]
            print(f"injection type {t} i {i} seed {seed}", file=sys.stderr, flush=True)
            snapshot = _scene(env, seed, task, run_dir)
            rendered = render_episode(env, snapshot, episode, task[2])
            size_frames = _size_frames(snapshot, rendered)
            if t != 3 or min(size_frames, rendered.steps) >= 2:
                break
            skipped.append(
                {"seed": seed, "size_checkable_frames": size_frames, "T": rendered.steps}
            )
            seed = next(replacements, None)
        if seed is None:
            injections.append(
                {
                    "type": t,
                    "name": TYPES[t],
                    "i": i,
                    "frozen_seed": frozen_seed,
                    "skipped_seeds": skipped,
                    "seed": None,
                    "source_passed": False,
                    "injected_passed": None,
                    "failed_checks": [],
                    "injection_error": "not built: replacement seeds 10260 to 10299 ran out",
                }
            )
            continue
        manifest = snapshot.candidate_manifest()
        source = _check(snapshot, manifest, rendered.frames, tolerances, size_frames)
        item: dict[str, Any] = {
            "type": t,
            "name": TYPES[t],
            "i": i,
            "frozen_seed": frozen_seed,
            "skipped_seeds": skipped,
            "seed": seed,
            "source": {
                **_episode_note(episode, rendered.steps, rendered.planning_error),
                **source,
                **goal_report(snapshot),
                "final_cube": final_cube(snapshot, rendered),
            },
            "source_passed": source["passed"],
        }
        try:
            other = None
            if t == 6:
                other = _scene(env, seed + RENDER_SEED_OFFSET, task, run_dir).render
            projection = None
            if t == 4:
                try:
                    projection = projection_matrix(snapshot.manifest)
                except SnapshotError as exc:
                    projection = None
                    item["projection_error"] = str(exc)
            injected = inject(
                t,
                i,
                rendered.frames,
                manifest,
                projection=projection,
                other_render=other,
                size_frames=size_frames,
                seed=seed,
            )
        except InjectionError as exc:
            item.update(injected_passed=None, failed_checks=[], injection_error=str(exc))
        else:
            # an injection alters frames and the manifest, never the actions, so n is the source's
            checked = _check(snapshot, injected.manifest, injected.frames, tolerances, size_frames)
            item.update(
                detail=injected.detail,
                injected=checked,
                injected_passed=checked["passed"],
                failed_checks=checked["failed_checks"],
            )
        injections.append(item)
    return {
        "controls": controls,
        "injections": injections,
        "verdict": verdict(controls, injections),
    }


def _pilot(args: argparse.Namespace) -> int:
    frozen = check_frozen()
    if TOLERANCES_PATH.exists():
        raise ValueError(f"{TOLERANCES_PATH} exists; the pilot sets it once")
    check_not_run(RUNS, PILOT_RESULT)
    task = _task()
    env = ManiSkillPickCube(env_id=task[0], max_episode_steps=task[2], render=True)
    with ledgered_run(
        purpose="WO-021: ET-M3-1 tolerance pilot (m3-protocol-4), block 10 seeds 10940-10959",
        config={"frozen": frozen, "pilot_seeds": [PILOT_SEEDS[0], PILOT_SEEDS[-1]]},
        seeds={str(seed): seed for seed in PILOT_SEEDS},
        env_lock={"stack": env.stack_identity()},
    ) as run:
        if run.dirty:
            raise ValueError("commit first, so the code note stays true")
        started = time.perf_counter()
        measured = run_pilot(env, task, run.directory)
        report: dict[str, Any] = {
            "run": run.directory.name,
            "code": run.code_note,
            "frozen": frozen,
            "episodes": measured["episodes"],
        }
        try:
            tolerances = pilot_tolerances(measured["candidates"])
        except PilotStopError as exc:
            report.update(stopped=str(exc), observed=exc.observed)
            report["seconds"] = time.perf_counter() - started
            _write_once(run.directory / PILOT_RESULT, report)
            run.note = f"stopped, tell the owner: {exc}"
            print(f"stopped, tell the owner: {exc}", file=sys.stderr)
            return STOPPED
        tolerances.update(run=run.directory.name, code=run.code_note)
        report.update(tolerances=tolerances, seconds=time.perf_counter() - started)
        _write_once(run.directory / PILOT_RESULT, report)
        text = json.dumps(tolerances, indent=2, sort_keys=True, allow_nan=False) + "\n"
        with TOLERANCES_PATH.open("x", encoding="utf-8") as stream:
            stream.write(text)
        digest = hashlib.sha256(TOLERANCES_PATH.read_bytes()).hexdigest()
        run.note = f"{TOLERANCES_PATH} sha256 {digest}"
        print(f"{TOLERANCES_PATH} sha256 {digest}")
        print(run.directory)
    return 0


def _score(args: argparse.Namespace) -> int:
    frozen = check_frozen()
    digest = hashlib.sha256(TOLERANCES_PATH.read_bytes()).hexdigest()
    check_recorded(digest)
    tolerances = load_tolerances(TOLERANCES_PATH, digest)
    observed = json.loads(TOLERANCES_PATH.read_text(encoding="utf-8"))["observed"]
    check_not_run(RUNS, SCORE_RESULT)
    task = _task()
    env = ManiSkillPickCube(env_id=task[0], max_episode_steps=task[2], render=True)
    with ledgered_run(
        purpose="WO-021: ET-M3-1 (m3-protocol-4) scored once, 60 controls and 60 injections",
        config={"frozen": frozen, "tolerances_sha256": digest},
        seeds={"controls_first": CONTROL_SEEDS[0], "injections_first": FIRST_INJECTION_SEED},
        env_lock={"stack": env.stack_identity()},
    ) as run:
        if run.dirty:
            raise ValueError("commit first, so the code note stays true")
        started = time.perf_counter()
        report: dict[str, Any] = {
            "run": run.directory.name,
            "code": run.code_note,
            "frozen": frozen,
            "tolerances_sha256": digest,
            "pilot_against_stops_8_9_10": {
                "merge_radius_px": tolerances.merge_radius_px,
                "smallest_duplicate_offset_px": SMALLEST_DUPLICATE_OFFSET_PX,
                "goal_max_excess_px": observed["goal_max_excess_px"],
                "goal_final_v_g_min": observed["goal_final_v_g_min"],
                "goal_final_shifted_margin_min_px": observed["goal_final_shifted_margin_min_px"],
            },
            **run_score(env, task, run.directory, tolerances),
        }
        report["seconds"] = time.perf_counter() - started
        _write_once(run.directory / SCORE_RESULT, report)
        result = report["verdict"]
        run.note = (
            f"ET-M3-1 passed {result['passed']}: {result['injections_rejected']}/60 injections "
            f"rejected, {result['false_rejections']}/60 controls falsely rejected"
        )
        print(run.note)
        print(run.directory)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("pilot", help="the tolerance pilot, once")
    commands.add_parser("score", help="ET-M3-1, scored once")
    args = parser.parse_args(argv)
    try:
        require_code_root()
        return _pilot(args) if args.command == "pilot" else _score(args)
    except SimulatorUnavailableError as exc:
        print(f"not run: {exc}", file=sys.stderr)
        return 3
    except (ReplayInvalidError, ValueError, OSError, KeyError) as exc:
        print(f"refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
