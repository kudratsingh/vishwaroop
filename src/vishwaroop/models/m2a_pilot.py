"""M2a observation-model pilot on the Mac: does training at the target resolution fit here? (WO-017)

    python -m vishwaroop.models.m2a_pilot                                  # WO-017, the Mac
    python -m vishwaroop.models.m2a_pilot --save-frames frames.pt           # WO-018, on the Mac
    python -m vishwaroop.models.m2a_pilot --frames frames.pt --device cuda  # WO-018, on the GPU

Run it from the repository root, in the robotics environment. It renders real simulator frames
from scripted episodes on train seeds 6000 to 6019 (block 6, never simulated), then trains a
small image tokenizer, a ViT-S/14-shaped encoder with a per-patch pixel decoder, at 224 x 224 on
MPS for a fixed wall-clock budget, and measures images per second, memory and the loss curve. It
is a measurement for an estimate, not a model anyone should use. The whole run stays under 30
minutes, so it is simply repeated if stopped. Results go to ``m2a_pilot.json`` in a new run
directory. Exit codes: 0 measured, 2 refused, 3 simulator not run.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from ..sim.baseline import ScriptedPickPlace
from ..sim.env import ManiSkillPickCube, SimulatorUnavailableError
from ..sim.runlog import ledgered_run, require_code_root
from .compute_pilot import _machine, _peak_tracker, _sync, _torch

SEEDS = range(6000, 6020)
RESOLUTION = 224
PATCH = 14
WIDTH = 384
DEPTH = 12
HEADS = 6
BATCH = 32
TRAIN_SECONDS = 20 * 60
RENDER_LIMIT_SECONDS = 6 * 60
# The estimate this pilot checks (WO-005's plan): 2,000 episodes x 150 steps x 2 cameras,
# 20 epochs, for the encoder alone.
PLANNED_IMAGES = 2000 * 150 * 2
PLANNED_EPOCHS = 20


def render_frames(env: Any, seeds: range, limit_seconds: float) -> tuple[Any, dict[str, Any]]:
    """Every frame of scripted episodes, resized to 224 x 224, as uint8, until the time limit."""
    torch = _torch()
    frames = []
    started = time.perf_counter()
    episodes = 0
    for seed in seeds:
        if time.perf_counter() - started > limit_seconds:
            break
        controller = ScriptedPickPlace()
        packet = env.reset(seed)
        step = 0
        while True:
            image = torch.from_numpy(env.render_rgb()).permute(2, 0, 1).unsqueeze(0).float()
            small = torch.nn.functional.interpolate(
                image, size=(RESOLUTION, RESOLUTION), mode="bilinear", antialias=True
            )
            frames.append(small.clamp(0, 255).to(torch.uint8))
            action = controller(packet, step)
            if action is None:
                break
            packet = env.step(action)
            step += 1
        episodes += 1
    seconds = time.perf_counter() - started
    stacked = torch.cat(frames)
    return stacked, {
        "episodes": episodes,
        "frames": len(stacked),
        "seconds": seconds,
        "frames_per_second": len(stacked) / seconds,
        "native_shape": list(env.render_rgb().shape),
    }


class Tokenizer:
    """A ViT-S/14-shaped encoder and a linear per-patch decoder back to pixels."""

    def __init__(self, device: str) -> None:
        torch = _torch()
        nn = torch.nn
        tokens = (RESOLUTION // PATCH) ** 2
        self.patch = nn.Conv2d(3, WIDTH, kernel_size=PATCH, stride=PATCH)
        self.position = nn.Parameter(torch.zeros(1, tokens, WIDTH))
        layer = nn.TransformerEncoderLayer(
            WIDTH, HEADS, 4 * WIDTH, batch_first=True, norm_first=True, dropout=0.0
        )
        self.encoder = nn.TransformerEncoder(layer, DEPTH)
        self.decoder = nn.Linear(WIDTH, 3 * PATCH * PATCH)
        self.modules = nn.ModuleList([self.patch, self.encoder, self.decoder]).to(device)
        self.position = nn.Parameter(self.position.data.to(device))

    def parameters(self) -> list[Any]:
        return [*self.modules.parameters(), self.position]

    def __call__(self, images: Any) -> Any:
        tokens = self.patch(images).flatten(2).transpose(1, 2) + self.position
        patches = self.decoder(self.encoder(tokens))
        side = RESOLUTION // PATCH
        batch = images.shape[0]
        patches = patches.view(batch, side, side, 3, PATCH, PATCH)
        return patches.permute(0, 3, 1, 4, 2, 5).reshape(batch, 3, RESOLUTION, RESOLUTION)


def train(
    frames: Any, device: str, seconds: float, batch_size: int = BATCH, bf16: bool = False
) -> dict[str, Any]:
    """Train for a fixed wall-clock budget and measure throughput and loss.

    ``bf16`` runs the forward pass under bfloat16 autocast, as a GPU run would in practice.
    """
    torch = _torch()
    torch.manual_seed(0)
    model = Tokenizer(device)
    parameters = model.parameters()
    optimizer = torch.optim.AdamW(parameters, lr=3e-4)
    peak = _peak_tracker(device)
    count = len(frames)
    images = 0
    steps = 0
    losses: list[tuple[float, float]] = []
    step_times: list[float] = []
    started = time.perf_counter()
    while time.perf_counter() - started < seconds:
        index = torch.randint(0, count, (batch_size,))
        batch = frames[index].to(device).float() / 255.0
        mark = time.perf_counter()
        with torch.autocast(device_type=device, dtype=torch.bfloat16, enabled=bf16):
            output = model(batch)
        loss = torch.nn.functional.mse_loss(output.float(), batch)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
        _sync(device)  # MPS is asynchronous: without this a step's time is only its enqueueing
        if steps % 25 == 0:
            losses.append((time.perf_counter() - started, float(loss.item())))
            peak()
        step_times.append(time.perf_counter() - mark)
        images += batch_size
        steps += 1
    _sync(device)
    elapsed = time.perf_counter() - started
    settled = step_times[len(step_times) // 10 :]
    per_second = batch_size / statistics.median(settled)
    return {
        "batch": batch_size,
        "bf16": bf16,
        "parameters": sum(int(item.numel()) for item in parameters),
        "steps": steps,
        "images": images,
        "seconds": elapsed,
        "images_per_second_overall": images / elapsed,
        "images_per_second_median_step": per_second,
        "loss_curve": losses,
        "first_loss": losses[0][1] if losses else math.nan,
        "last_loss": losses[-1][1] if losses else math.nan,
        "metal_driver_peak_bytes": peak(),
    }


def extrapolate(images_per_second: float) -> dict[str, Any]:
    """Hours for the planned encoder-only training at the measured rate; arithmetic only."""
    passes = PLANNED_IMAGES * PLANNED_EPOCHS
    return {
        "planned_images": PLANNED_IMAGES,
        "planned_epochs": PLANNED_EPOCHS,
        "encoder_only_hours": passes / images_per_second / 3600,
        "label": "estimated, from the measured rate; decoder and dynamics not included",
    }


def _device_identity(device: str) -> dict[str, Any]:
    torch = _torch()
    if device == "cuda":
        properties = torch.cuda.get_device_properties(0)
        return {
            "name": properties.name,
            "memory_bytes": int(properties.total_memory),
            "cuda": torch.version.cuda,
            "torch": torch.__version__,
        }
    return {"name": device, "torch": torch.__version__}


def load_frames(path: Path, expected_sha256: str | None) -> Any:
    """Frames saved by ``--save-frames``, checked against their hash when one is given."""
    import hashlib

    torch = _torch()
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and actual != expected_sha256:
        raise ValueError(f"{path} has sha256 {actual}, not {expected_sha256}")
    frames = torch.load(path, weights_only=True)
    if frames.dtype != torch.uint8 or tuple(frames.shape[1:]) != (3, RESOLUTION, RESOLUTION):
        raise ValueError(f"{path} does not hold uint8 frames of 3 x {RESOLUTION} x {RESOLUTION}")
    return frames


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("mps", "cpu", "cuda"), default="mps")
    parser.add_argument("--seconds", type=float, default=TRAIN_SECONDS)
    parser.add_argument("--batch", type=int, default=BATCH)
    parser.add_argument("--bf16", action="store_true")
    parser.add_argument("--save-frames", type=Path, default=None)
    parser.add_argument("--frames", type=Path, default=None)
    parser.add_argument("--frames-sha256", default=None)
    args = parser.parse_args(argv)
    if args.seconds > TRAIN_SECONDS:
        print(
            f"refused: at most {TRAIN_SECONDS} s, so a run stays under 30 minutes", file=sys.stderr
        )
        return 2
    try:
        require_code_root()
        machine = _machine() if args.device != "cuda" else {"host": "gpu vm"}
        env = None if args.frames else ManiSkillPickCube(render=True)
        with ledgered_run(
            purpose="M2a observation-model pilot, a measurement for an estimate (WO-017, WO-018)",
            config={
                "resolution": RESOLUTION,
                "batch": args.batch,
                "train_seconds": args.seconds,
                "bf16": args.bf16,
                "device": args.device,
                "frames": str(args.frames) if args.frames else None,
            },
            seeds={"torch": 0, "first_episode": SEEDS.start},
            env_lock={
                "machine": machine,
                "device": _device_identity(args.device),
                **({"stack": env.stack_identity()} if env else {}),
            },
        ) as run:
            if run.dirty:
                raise ValueError("commit first, so the code note stays true")
            if args.frames:
                frames = load_frames(args.frames, args.frames_sha256)
                rendering: dict[str, Any] = {"loaded_from": str(args.frames), "frames": len(frames)}
            else:
                frames, rendering = render_frames(env, SEEDS, RENDER_LIMIT_SECONDS)
            print(f"{len(frames)} frames", file=sys.stderr, flush=True)
            if args.save_frames:
                _torch().save(frames, args.save_frames)
                import hashlib

                rendering["saved_to"] = str(args.save_frames)
                rendering["saved_sha256"] = hashlib.sha256(
                    args.save_frames.read_bytes()
                ).hexdigest()
            training = train(frames, args.device, args.seconds, args.batch, args.bf16)
            report = {
                "run": run.directory.name,
                "code": run.code_note,
                "machine": machine,
                "device": args.device,
                "device_identity": _device_identity(args.device),
                "rendering": rendering,
                "training": training,
                "extrapolation": extrapolate(training["images_per_second_median_step"]),
            }
            with (run.directory / "m2a_pilot.json").open("x", encoding="utf-8") as stream:
                json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
                stream.write("\n")
            run.note = f"{training['images_per_second_median_step']:.0f} images/s training"
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
