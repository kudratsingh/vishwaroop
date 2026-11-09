"""WO-025 workload B: per-call inference latency of ACT, SmolVLA and pi0.5 at batch 1, 4 and 8.

Run from the repository root in the LeRobot environment (``lerobot==0.6.1``), with
``PYTHONPATH=src``. Inputs are synthetic, at the SO-101 shapes: two 480 x 640 RGB cameras (front,
wrist) and a 6-joint state. Batch N repeats one observation N times, as best-of-N candidates do.

What one timed call covers: the policy's ``predict_action_chunk`` on a batch already on the
device, followed by a device sync. The pre-processor (normalisation, tokenisation) is not timed:
both VLAs pad the prompt to a fixed token length, so prompt tokens are random ids at that length
with a full attention mask, which also avoids the gated PaliGemma tokenizer. Camera keys follow
the checkpoint's own config: the first two image keys get the front and wrist frames; a checkpoint
that declares more cameras gets them padded as its own code does.

Pretrained weights are downloaded at a pinned revision, their sha256 is checked against the
revision's LFS id before loading, and they load through safetensors only (AGENTS.md 6.6). ACT has no
SO-101 checkpoint yet; it is randomly initialised, since latency does not depend on the weights.
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

from ..sim.runlog import ledgered_run, require_code_root
from .device import add_device_argument, machine, peak_tracker, require, sync

CHECKPOINTS = {
    "smolvla": ("lerobot/smolvla_base", "5e8d12a6e2975b0e5e5fce7c8caf47c371d257b6"),
    "pi05": ("lerobot/pi05_base", "22c30e5b34f9e7ab738b1b34fc2fc5ecfe2d28f0"),
}
WEIGHTS = "model.safetensors"
# The LFS sha256 of WEIGHTS at each pinned revision (read from the Hub on 2026-11-08); checked
# again against the Hub at run time.
WEIGHTS_SHA256 = {
    "smolvla": "7cd549ac2351fb069c0ddb3c34ad2d09cfc92b56a15dccdfc2e41467aaca01eb",
    "pi05": "0eb11ca9587678c1d2ef8cf32807c29f8ce53a2bfdfc1aa4a4c96f16fca59b0f",
}
POLICIES = ("act", "smolvla", "pi05")
BATCHES = (1, 4, 8)
WARMUP = 20
CALLS = 200
# A call slower than this is reported as a result and larger batches are skipped (WO-025).
SLOW_CALL_S = 10.0
IMAGE_SHAPE = (3, 480, 640)
STATE_DIM = 6
# Prompt token ids are drawn below this bound; an embedding lookup costs the same for any id.
TOKEN_ID_BOUND = 1_000
PRECISION = {"act": "fp32", "smolvla": "fp32", "pi05": "bf16"}


class WeightsMismatchError(ValueError):
    """A checkpoint's weights do not match the pinned sha256 (stop condition 3)."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 24), b""):
            digest.update(block)
    return digest.hexdigest()


def check_weights(name: str, local: Path, hub_sha256: str | None) -> str:
    """Refuse unless the local file, the pinned hash and the Hub's LFS id all agree."""
    pinned = WEIGHTS_SHA256[name]
    if hub_sha256 != pinned:
        raise WeightsMismatchError(f"{name}: the Hub says {hub_sha256}, pinned {pinned}")
    actual = sha256_file(local)
    if actual != pinned:
        raise WeightsMismatchError(f"{name}: {local} has sha256 {actual}, pinned {pinned}")
    return actual


def summarize(milliseconds: list[float], chunk_length: int) -> dict[str, float]:
    """p50, p95 and max per call, and per action step of the chunk."""
    ordered = sorted(milliseconds)
    p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
    p50 = statistics.median(ordered)
    return {
        "p50_ms": p50,
        "p95_ms": p95,
        "max_ms": ordered[-1],
        "mean_ms": statistics.fmean(ordered),
        "p50_ms_per_action_step": p50 / chunk_length,
        "calls": float(len(ordered)),
    }


def _download(name: str) -> tuple[str, str, dict[str, Any]]:  # pragma: no cover - network
    from huggingface_hub import HfApi, hf_hub_download

    repo, revision = CHECKPOINTS[name]
    info = HfApi().model_info(repo, revision=revision, files_metadata=True)
    hub = {s.rfilename: (s.lfs.sha256 if s.lfs else None) for s in info.siblings or []}
    local = Path(hf_hub_download(repo, WEIGHTS, revision=revision))
    actual = check_weights(name, local, hub.get(WEIGHTS))
    return repo, revision, {"repo": repo, "revision": revision, "weights_sha256": actual}


def _load(name: str, device: str) -> tuple[Any, dict[str, Any]]:  # pragma: no cover - lerobot
    import torch

    if name == "act":
        from lerobot.configs.types import FeatureType, PolicyFeature
        from lerobot.policies.act.configuration_act import ACTConfig
        from lerobot.policies.act.modeling_act import ACTPolicy

        config = ACTConfig(
            input_features={
                "observation.images.front": PolicyFeature(FeatureType.VISUAL, IMAGE_SHAPE),
                "observation.images.wrist": PolicyFeature(FeatureType.VISUAL, IMAGE_SHAPE),
                "observation.state": PolicyFeature(FeatureType.STATE, (STATE_DIM,)),
            },
            output_features={"action": PolicyFeature(FeatureType.ACTION, (STATE_DIM,))},
            pretrained_backbone_weights=None,
            device=device,
        )
        torch.manual_seed(0)
        policy = ACTPolicy(config)
        identity: dict[str, Any] = {"repo": None, "revision": None}
        identity["weights"] = "random init, torch seed 0"
    else:
        from lerobot.configs.policies import PreTrainedConfig
        from lerobot.policies.factory import get_policy_class

        repo, revision, identity = _download(name)
        config = PreTrainedConfig.from_pretrained(repo, revision=revision)
        config.device = device
        if PRECISION[name] == "bf16":
            config.dtype = "bfloat16"
        policy = get_policy_class(name).from_pretrained(repo, config=config, revision=revision)
    policy.to(device)
    policy.eval()
    identity["chunk_size"] = int(policy.config.chunk_size)
    identity["image_keys"] = list(policy.config.image_features)
    identity["precision"] = PRECISION[name]
    identity["parameters"] = sum(p.numel() for p in policy.parameters())
    return policy, identity


def _batch(name: str, policy: Any, size: int, device: str) -> dict[str, Any]:  # pragma: no cover
    import torch

    generator = torch.Generator().manual_seed(size)
    keys = list(policy.config.image_features)[:2]
    frame = torch.rand((1, *IMAGE_SHAPE), generator=generator)
    batch: dict[str, Any] = {key: frame.repeat(size, 1, 1, 1).to(device) for key in keys}
    state = torch.rand((1, STATE_DIM), generator=generator).repeat(size, 1)
    if name != "pi05":
        batch["observation.state"] = state.to(device)
    if name != "act":
        length = int(policy.config.tokenizer_max_length)
        tokens = torch.randint(0, TOKEN_ID_BOUND, (1, length), generator=generator)
        tokens = tokens.repeat(size, 1)
        batch["observation.language.tokens"] = tokens.to(device)
        batch["observation.language.attention_mask"] = torch.ones(
            (size, length), dtype=torch.bool, device=device
        )
    return batch


def time_policy(name: str, device: str, calls: int, warmup: int) -> dict[str, Any]:
    """Load one policy and time it at each batch size; a failure is recorded, not raised."""
    import torch

    started = time.perf_counter()
    try:
        policy, identity = _load(name, device)
    except WeightsMismatchError:
        raise
    except Exception as exc:  # out of memory, missing kernels: a result, not a crash
        return {"policy": name, "status": "failed to load", "error": f"{type(exc).__name__}: {exc}"}
    result: dict[str, Any] = {
        "policy": name,
        "status": "measured",
        "identity": identity,
        "load_seconds": time.perf_counter() - started,
        "batches": {},
    }
    peak = peak_tracker(device)
    for size in BATCHES:
        try:
            batch = _batch(name, policy, size, device)
            with torch.inference_mode():
                start = time.perf_counter()
                policy.predict_action_chunk(batch)
                sync(device)
                first = time.perf_counter() - start
                if first > SLOW_CALL_S:
                    result["batches"][str(size)] = {
                        "status": f"above {SLOW_CALL_S:.0f} s per call, not timed further",
                        "first_call_ms": first * 1000.0,
                    }
                    print(f"{name} batch {size}: too slow", file=sys.stderr, flush=True)
                    break
                for _ in range(warmup):
                    policy.predict_action_chunk(batch)
                sync(device)
                times = []
                for _ in range(calls):
                    start = time.perf_counter()
                    policy.predict_action_chunk(batch)
                    sync(device)
                    times.append((time.perf_counter() - start) * 1000.0)
            entry: dict[str, Any] = summarize(times, identity["chunk_size"])
            entry["first_call_ms"] = first * 1000.0
            entry["peak_accelerator_bytes"] = peak()
            result["batches"][str(size)] = entry
        except Exception as exc:
            result["batches"][str(size)] = {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
        print(f"{name} batch {size}: {result['batches'][str(size)]}", file=sys.stderr, flush=True)
    return result


def _library_versions() -> dict[str, str]:  # pragma: no cover - environment
    import importlib.metadata as metadata

    names = ("lerobot", "torch", "transformers", "huggingface-hub", "safetensors")
    return {name: metadata.version(name) for name in names}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_device_argument(parser, default="mps")
    parser.add_argument("--policies", nargs="+", choices=POLICIES, default=list(POLICIES))
    parser.add_argument("--calls", type=int, default=CALLS)
    parser.add_argument("--warmup", type=int, default=WARMUP)
    args = parser.parse_args(argv)
    require(args.device)
    try:
        require_code_root()
        identity = machine()
        with ledgered_run(
            purpose="WO-025 workload B: VLA inference latency (a measurement for an estimate)",
            config={
                "policies": args.policies,
                "batches": list(BATCHES),
                "calls": args.calls,
                "warmup": args.warmup,
                "device": args.device,
                "image_shape": list(IMAGE_SHAPE),
                "checkpoints": CHECKPOINTS,
                "precision": PRECISION,
            },
            seeds={"torch": 0},
            env_lock={"machine": identity, "libraries": _library_versions()},
        ) as run:
            if run.dirty:
                raise ValueError("commit first, so the code note stays true")
            results = [
                time_policy(name, args.device, args.calls, args.warmup) for name in args.policies
            ]
            report = {
                "run": run.directory.name,
                "code": run.code_note,
                "machine": identity,
                "device": args.device,
                "libraries": _library_versions(),
                "results": results,
            }
            with (run.directory / "vla_latency.json").open("x", encoding="utf-8") as stream:
                json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
                stream.write("\n")
            run.note = "; ".join(f"{r['policy']} {r['status']}" for r in results)
            print(run.directory)
    except (ValueError, OSError, KeyError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
