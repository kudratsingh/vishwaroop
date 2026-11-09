"""Devices for every training, scoring and planning entry point (WO-024): CPU, MPS and CUDA.

The Mac path (``cpu`` and ``mps``) behaves as before this module existed. CUDA support is written
and tested with torch mocked; it has not run on a CUDA machine until a report says it has.

- ``add_device_argument`` gives an entry point its ``--device`` option, with the entry point's own
  default.
- ``require`` refuses a device this machine lacks and, on CUDA only, turns on deterministic
  kernels. MPS and CPU settings are left untouched.
- ``sync``, ``peak_tracker`` and ``machine`` time, measure and identify a run on any of the three.
- ``accelerator_rng_state`` and ``set_accelerator_rng_state`` carry an accelerator's random-number
  state through a checkpoint, so a resumed run continues the same stream (AGENTS.md section 13.9).

torch is imported only inside the functions, so the CPU tier (no torch) can import this module.
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

DEVICES = ("cpu", "mps", "cuda")
# cuBLAS needs this for deterministic matrix products (NVIDIA's cuBLAS reproducibility notes).
CUBLAS_WORKSPACE = ":4096:8"


class DeviceUnavailableError(RuntimeError):
    """The requested device is not present on this machine."""


def _torch() -> Any:
    import torch

    return torch


def add_device_argument(parser: argparse.ArgumentParser, default: str) -> None:
    """Add ``--device`` with the three devices and the entry point's existing default."""
    if default not in DEVICES:
        raise ValueError(f"default device {default!r} is not one of {DEVICES}")
    parser.add_argument("--device", choices=DEVICES, default=default)


def arch_supported(capability: tuple[int, int], arch_list: list[str]) -> bool:
    """Whether a torch build's architecture list can run on a GPU of this compute capability.

    A binary (``sm_XY``) runs on the same major version at the same or a higher minor version, so
    ``sm_86`` serves an 8.9 card such as the L40S. PTX (``compute_XY``) is compiled for any
    capability at or above it. A 12.0 card (RTX 5090) needs ``sm_120`` or older-major PTX.
    """
    major, minor = capability
    for arch in arch_list:
        kind, _, digits = arch.partition("_")
        if not digits.isdigit() or len(digits) < 2:
            continue
        arch_major, arch_minor = int(digits[:-1]), int(digits[-1])
        if kind == "sm" and arch_major == major and arch_minor <= minor:
            return True
        if kind == "compute" and (arch_major, arch_minor) <= (major, minor):
            return True
    return False


def require(device: str) -> str:
    """Refuse an unavailable device; on CUDA, make kernels deterministic. Returns ``device``."""
    if device not in DEVICES:
        raise DeviceUnavailableError(f"device {device!r} is not one of {DEVICES}")
    if device == "cpu":
        return device
    torch = _torch()
    if device == "mps":
        if not torch.backends.mps.is_available():
            raise DeviceUnavailableError("--device mps, but MPS is not available here")
        return device
    if not torch.cuda.is_available():
        raise DeviceUnavailableError("--device cuda, but CUDA is not available here")
    capability = tuple(torch.cuda.get_device_capability(0))
    arch_list = list(torch.cuda.get_arch_list())
    if not arch_supported(capability, arch_list):
        name = torch.cuda.get_device_name(0)
        raise DeviceUnavailableError(
            f"{name} is compute capability {capability[0]}.{capability[1]}, which this torch build "
            f"cannot run: it was built for {arch_list}"
        )
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", CUBLAS_WORKSPACE)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.use_deterministic_algorithms(True, warn_only=True)
    return device


def sync(device: str) -> None:
    """Wait for queued work: MPS and CUDA are asynchronous, so a timing needs this."""
    if device == "mps":
        _torch().mps.synchronize()
    elif device == "cuda":
        _torch().cuda.synchronize()


def peak_tracker(device: str) -> Callable[[], float]:
    """A function that samples the accelerator's allocation and returns the highest, in bytes.

    MPS reports the Metal driver's allocation; CUDA its own running maximum of allocated memory.
    On CPU it returns 0.
    """
    torch = _torch()
    peak = [0.0]

    def sample() -> float:
        if device == "mps":
            peak[0] = max(peak[0], float(torch.mps.driver_allocated_memory()))
        elif device == "cuda":
            peak[0] = max(peak[0], float(torch.cuda.max_memory_allocated()))
        return peak[0]

    return sample


def accelerator_rng_state(device: str) -> dict[str, Any]:
    """The accelerator's random-number state, keyed for a checkpoint; empty on CPU."""
    torch = _torch()
    if device == "mps":
        return {"mps_rng": torch.mps.get_rng_state()}
    if device == "cuda":
        return {"cuda_rng": torch.cuda.get_rng_state()}
    return {}


def set_accelerator_rng_state(device: str, saved: dict[str, Any]) -> None:
    """Restore what ``accelerator_rng_state`` saved, if the checkpoint holds it for ``device``."""
    torch = _torch()
    if device == "mps" and "mps_rng" in saved:
        torch.mps.set_rng_state(saved["mps_rng"].cpu())
    elif device == "cuda" and "cuda_rng" in saved:
        torch.cuda.set_rng_state(saved["cuda_rng"].cpu())


def machine(proc: Path = Path("/proc")) -> dict[str, Any]:
    """Identify the host: chip, memory, cores, platform, torch, and the accelerators present.

    macOS asks ``sysctl``, as every earlier run did; Linux reads ``/proc``. Nothing here needs a
    command that exists on only one of the two.
    """
    torch = _torch()
    if sys.platform == "darwin":
        host = _darwin_host()
    else:
        host = _linux_host(proc)
    identity: dict[str, Any] = {
        **host,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "torch": str(torch.__version__),
        "mps_available": bool(torch.backends.mps.is_available()),
        "cuda_available": bool(torch.cuda.is_available()),
        "torch_threads": int(torch.get_num_threads()),
    }
    if identity["cuda_available"]:
        properties = torch.cuda.get_device_properties(0)
        identity["cuda"] = {
            "name": str(properties.name),
            "capability": f"{properties.major}.{properties.minor}",
            "memory_bytes": int(properties.total_memory),
            "device_count": int(torch.cuda.device_count()),
            "cuda_version": str(torch.version.cuda),
            "cudnn_version": torch.backends.cudnn.version(),
        }
    return identity


def _darwin_host() -> dict[str, Any]:
    chip = subprocess.run(
        [
            "/usr/sbin/sysctl",
            "-n",
            "machdep.cpu.brand_string",
            "hw.memsize",
            "hw.perflevel0.physicalcpu",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\n")
    return {
        "chip": chip[0],
        "memory_bytes": int(chip[1]),
        "performance_cores": int(chip[2]),
    }


def _linux_host(proc: Path) -> dict[str, Any]:
    chip = "unknown"
    try:
        for line in (proc / "cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                chip = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    memory = 0
    try:
        for line in (proc / "meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                memory = int(line.split()[1]) * 1024
                break
    except OSError:
        pass
    return {
        "chip": chip,
        "memory_bytes": memory,
        # Linux does not separate performance from efficiency cores; this is the logical count.
        "logical_cores": os.cpu_count() or 0,
    }
