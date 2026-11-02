"""M2a observation-model pilot on the Mac: does training at the target resolution fit here? (WO-017)

    python -m vishwaroop.models.m2a_pilot

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


def train(frames: Any, device: str, seconds: float) -> dict[str, Any]:
    """Train for a fixed wall-clock budget and measure throughput and loss."""
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
        index = torch.randint(0, count, (BATCH,))
        batch = frames[index].to(device).float() / 255.0
        mark = time.perf_counter()
        loss = torch.nn.functional.mse_loss(model(batch), batch)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
        _sync(device)  # MPS is asynchronous: without this a step's time is only its enqueueing
        if steps % 25 == 0:
            losses.append((time.perf_counter() - started, float(loss.item())))
            peak()
        step_times.append(time.perf_counter() - mark)
        images += BATCH
        steps += 1
    _sync(device)
    elapsed = time.perf_counter() - started
    settled = step_times[len(step_times) // 10 :]
    per_second = BATCH / statistics.median(settled)
    return {
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("mps", "cpu"), default="mps")
    args = parser.parse_args(argv)
    try:
        require_code_root()
        machine = _machine()
        env = ManiSkillPickCube(render=True)
        with ledgered_run(
            purpose="WO-017: M2a observation-model pilot on the Mac, a measurement for an estimate",
            config={"resolution": RESOLUTION, "batch": BATCH, "train_seconds": TRAIN_SECONDS},
            seeds={"torch": 0, "first_episode": SEEDS.start},
            env_lock={"machine": machine, "stack": env.stack_identity()},
        ) as run:
            if run.dirty:
                raise ValueError("commit first, so the code note stays true")
            frames, rendering = render_frames(env, SEEDS, RENDER_LIMIT_SECONDS)
            print(f"rendered {len(frames)} frames", file=sys.stderr, flush=True)
            training = train(frames, args.device, TRAIN_SECONDS)
            report = {
                "run": run.directory.name,
                "code": run.code_note,
                "machine": machine,
                "device": args.device,
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
