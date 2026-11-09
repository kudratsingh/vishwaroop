"""WO-025 workload A: ManiSkill3 step and render throughput (SO-101 required, SO-100 reference).

Run from the repository root in the robotics environment (``PYTHONPATH=src``; on the Mac with
``VK_ICD_FILENAMES`` pointing at MoltenVK). Each configuration runs in its own child process, so
an out-of-memory failure or a GPU PhysX restriction in one cannot spoil the next, and a failure is
recorded as a result. The parent opens one ledgered run and writes ``sim_throughput.json``.

Scenes:
- ``so101`` (required): ``so101_scene``'s SO-101 (TheRobotStudio URDF, pinned) with a cube and a
  bin, two cameras (front, wrist).
- ``so100`` (reference only): upstream ``PickCubeSO100-v1``, one camera. Its numbers are labelled
  reference in every output and are never quoted as SO-101 throughput.

Per configuration: environment creation and reset time, first-step time, then ``warmup`` steps and
``steps`` timed steps with pre-drawn random actions. Reported: control steps per second, environment
steps per second (times ``num_envs``), rendered camera frames per second, and peak memory.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ..sim.runlog import ledgered_run, require_code_root
from .device import machine

SCENES = {"so101": "required", "so100": "reference"}
OBS = (("state", None), ("rgb", "128x128"), ("rgb", "480x640"))
BACKENDS = {"cpu": ("physx_cpu", "cpu"), "cuda": ("physx_cuda", "gpu")}
CAMERAS = {"so101": 2, "so100": 1}
NUM_ENVS = {"cpu": (1,), "cuda": (1, 64, 256, 1024)}
WARMUP = 50
STEPS = 1000
ACTION_POOL = 64
CHILD_TIMEOUT_S = 900


def configurations(backend: str, scenes: list[str]) -> list[dict[str, Any]]:
    """Every (scene, observation, camera, num_envs) cell for one backend, in run order."""
    cells = []
    for scene in scenes:
        for obs_mode, camera in OBS:
            for num_envs in NUM_ENVS[backend]:
                cells.append(
                    {
                        "scene": scene,
                        "label": SCENES[scene],
                        "obs_mode": obs_mode,
                        "camera": camera,
                        "num_envs": num_envs,
                        "backend": backend,
                    }
                )
    return cells


def rates(cell: dict[str, Any], seconds: float, steps: int) -> dict[str, float]:
    """Throughput from a timed loop; rendered frames count every camera of every environment."""
    control = steps / seconds
    env_steps = control * cell["num_envs"]
    frames = env_steps * CAMERAS[cell["scene"]] if cell["obs_mode"] == "rgb" else 0.0
    return {
        "control_steps_per_second": control,
        "env_steps_per_second": env_steps,
        "rendered_frames_per_second": frames,
    }


def _make(cell: dict[str, Any]) -> Any:  # pragma: no cover - needs ManiSkill
    import gymnasium as gym

    sim_backend, render_backend = BACKENDS[cell["backend"]]
    common = {
        "obs_mode": cell["obs_mode"],
        "num_envs": cell["num_envs"],
        "sim_backend": sim_backend,
        "render_backend": render_backend,
        "control_mode": "pd_joint_pos",
    }
    if cell["scene"] == "so101":
        from ..sim import so101_scene

        so101_scene.register()
        camera = cell["camera"] or "128x128"
        return gym.make(so101_scene.ENV_ID, camera=camera, **common)
    import mani_skill.envs  # noqa: F401  (registers PickCubeSO100-v1)

    extra: dict[str, Any] = {}
    if cell["camera"]:
        from ..sim.so101_scene import CAMERA_SHAPES

        height, width = CAMERA_SHAPES[cell["camera"]]
        extra["sensor_configs"] = {"width": width, "height": height}
    return gym.make("PickCubeSO100-v1", **common, **extra)


def _peak_bytes(backend: str) -> float:  # pragma: no cover - platform
    if backend == "cuda":
        import torch

        return float(torch.cuda.max_memory_allocated())
    import resource

    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return float(usage if sys.platform == "darwin" else usage * 1024)


def measure(cell: dict[str, Any], warmup: int, steps: int) -> dict[str, Any]:  # pragma: no cover
    """Run one configuration in this process."""
    import torch

    started = time.perf_counter()
    env = _make(cell)
    env.reset(seed=0)
    created = time.perf_counter() - started
    env.action_space.seed(0)
    pool = [env.action_space.sample() for _ in range(ACTION_POOL)]
    if cell["backend"] == "cuda":
        pool = [torch.as_tensor(a, device="cuda") for a in pool]
    start = time.perf_counter()
    env.step(pool[0])
    first = time.perf_counter() - start
    for index in range(warmup):
        env.step(pool[index % ACTION_POOL])
    if cell["backend"] == "cuda":
        torch.cuda.synchronize()
    start = time.perf_counter()
    for index in range(steps):
        obs, *_ = env.step(pool[index % ACTION_POOL])
    if cell["backend"] == "cuda":
        torch.cuda.synchronize()
    seconds = time.perf_counter() - start
    shapes = {}
    if cell["obs_mode"] == "rgb":
        shapes = {name: list(data["rgb"].shape) for name, data in obs["sensor_data"].items()}
    env.close()
    return {
        **cell,
        "status": "measured",
        "create_and_reset_seconds": created,
        "first_step_seconds": first,
        "timed_steps": steps,
        "timed_seconds": seconds,
        **rates(cell, seconds, steps),
        "camera_shapes": shapes,
        "peak_bytes": _peak_bytes(cell["backend"]),
        "peak_bytes_kind": "cuda max allocated" if cell["backend"] == "cuda" else "process max RSS",
    }


def _child(cell: dict[str, Any], warmup: int, steps: int, out: Path) -> dict[str, Any]:
    """Run one configuration in a child process; a crash or timeout becomes a failed result."""
    command = [
        sys.executable,
        "-m",
        "vishwaroop.models.wo025_sim_throughput",
        "--worker",
        json.dumps(cell),
        "--warmup",
        str(warmup),
        "--steps",
        str(steps),
        "--result",
        str(out),
    ]
    try:
        done = subprocess.run(
            command, capture_output=True, text=True, timeout=CHILD_TIMEOUT_S, env=os.environ.copy()
        )
    except subprocess.TimeoutExpired:
        return {**cell, "status": "failed", "error": f"timed out after {CHILD_TIMEOUT_S} s"}
    if done.returncode == 0 and out.is_file():
        result: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
        return result
    tail = (done.stderr or "").strip().splitlines()[-3:]
    return {**cell, "status": "failed", "returncode": done.returncode, "error": " | ".join(tail)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=sorted(BACKENDS), default="cpu")
    parser.add_argument("--scenes", nargs="+", choices=sorted(SCENES), default=["so101", "so100"])
    parser.add_argument("--warmup", type=int, default=WARMUP)
    parser.add_argument("--steps", type=int, default=STEPS)
    parser.add_argument("--worker", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--result", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        result = measure(json.loads(args.worker), args.warmup, args.steps)
        with args.result.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, allow_nan=False)
        return 0
    if "so101" not in args.scenes:
        print("refused: SO-101 throughput is the required workload", file=sys.stderr)
        return 2
    try:
        require_code_root()
        identity = machine()
        from ..sim import so101_scene

        assets = so101_scene.register()
        cells = configurations(args.backend, args.scenes)
        with ledgered_run(
            purpose="WO-025 workload A: simulator throughput (a measurement for an estimate)",
            config={
                "backend": args.backend,
                "scenes": SCENES,
                "cells": cells,
                "warmup": args.warmup,
                "steps": args.steps,
            },
            seeds={"reset": 0, "actions": 0},
            env_lock={
                "machine": identity,
                "so101_assets": {"commit": so101_scene.SO_ARM100_COMMIT, "files": assets},
            },
        ) as run:
            if run.dirty:
                raise ValueError("commit first, so the code note stays true")
            results = []
            for index, cell in enumerate(cells):
                out = run.directory / f"cell-{index:02d}.json"
                result = _child(cell, args.warmup, args.steps, out)
                results.append(result)
                print(json.dumps(result), file=sys.stderr, flush=True)
            report = {
                "run": run.directory.name,
                "code": run.code_note,
                "machine": identity,
                "so100_is_reference_only": True,
                "results": results,
            }
            with (run.directory / "sim_throughput.json").open("x", encoding="utf-8") as stream:
                json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
                stream.write("\n")
            failed = sum(r["status"] != "measured" for r in results)
            run.note = f"{len(results) - failed} cells measured, {failed} failed"
            print(run.directory)
    except (ValueError, OSError, KeyError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
