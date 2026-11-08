"""WO-024: the device module, with torch mocked for CUDA (no CUDA machine has run this code)."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from vishwaroop.models import device

SRC = Path(__file__).resolve().parents[1] / "src" / "vishwaroop"
# Every entry point and the default its --device had before WO-024 (unchanged).
PORTABLE = {
    "planning/suite.py": "cpu",
    "models/m1_confirm.py": "mps",
    "models/m1_followups.py": "mps",
    "models/family_sweep.py": "mps",
    "models/cube_study.py": "mps",
    "models/latent_predictor.py": "mps",
    "models/m1_evaluate.py": "mps",
    "models/m3_remeasure.py": "mps",
    "scoring/score_branches.py": "mps",
    "scoring/score_et5_retest.py": "mps",
    "models/m2a_pilot.py": "mps",
}
# Kept Mac-only by design (WO-024 scope 4 and 6).
MAC_ONLY = {"models/compute_pilot.py": "cpu", "models/et_m3_6_score.py": "mps"}


class FakeCuda:
    def __init__(self, available: bool) -> None:
        self.available = available
        self.calls: list[str] = []
        self.rng = "cuda-state"

    def is_available(self) -> bool:
        return self.available

    def synchronize(self) -> None:
        self.calls.append("synchronize")

    def max_memory_allocated(self) -> int:
        return 7_000

    def get_rng_state(self) -> str:
        return self.rng

    def set_rng_state(self, state: Any) -> None:
        self.calls.append(f"set_rng_state:{state}")

    def get_device_properties(self, index: int) -> Any:
        return SimpleNamespace(name="FAKE GPU", major=8, minor=9, total_memory=24 * 2**30)

    def device_count(self) -> int:
        return 1


class FakeTensor:
    def __init__(self, value: str) -> None:
        self.value = value

    def cpu(self) -> str:
        return self.value


def fake_torch(cuda: bool, mps: bool = False) -> Any:
    deterministic: list[tuple[bool, bool]] = []
    torch = SimpleNamespace(
        __version__="0.0-fake",
        cuda=FakeCuda(cuda),
        backends=SimpleNamespace(
            mps=SimpleNamespace(is_available=lambda: mps),
            cudnn=SimpleNamespace(deterministic=False, benchmark=True, version=lambda: 90100),
        ),
        version=SimpleNamespace(cuda="12.8"),
        get_num_threads=lambda: 4,
        use_deterministic_algorithms=lambda flag, warn_only: deterministic.append(
            (flag, warn_only)
        ),
    )
    torch.deterministic_calls = deterministic
    return torch


@pytest.fixture
def cuda_torch(monkeypatch: pytest.MonkeyPatch) -> Any:
    torch = fake_torch(cuda=True)
    monkeypatch.setattr(device, "_torch", lambda: torch)
    monkeypatch.delenv("CUBLAS_WORKSPACE_CONFIG", raising=False)
    return torch


def test_add_device_argument_offers_three_devices_and_keeps_the_default() -> None:
    parser = argparse.ArgumentParser()
    device.add_device_argument(parser, default="mps")
    assert parser.parse_args([]).device == "mps"
    assert parser.parse_args(["--device", "cuda"]).device == "cuda"
    with pytest.raises(SystemExit):
        parser.parse_args(["--device", "tpu"])
    with pytest.raises(ValueError, match="default device"):
        device.add_device_argument(argparse.ArgumentParser(), default="gpu")


def test_cpu_needs_no_torch(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_torch() -> Any:
        raise AssertionError("torch imported for cpu")

    monkeypatch.setattr(device, "_torch", no_torch)
    assert device.require("cpu") == "cpu"


def test_cuda_is_refused_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(device, "_torch", lambda: fake_torch(cuda=False))
    with pytest.raises(device.DeviceUnavailableError, match="CUDA is not available"):
        device.require("cuda")


def test_mps_is_refused_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(device, "_torch", lambda: fake_torch(cuda=False, mps=False))
    with pytest.raises(device.DeviceUnavailableError, match="MPS is not available"):
        device.require("mps")


def test_cuda_turns_on_deterministic_kernels(cuda_torch: Any) -> None:
    import os

    assert device.require("cuda") == "cuda"
    assert cuda_torch.backends.cudnn.deterministic is True
    assert cuda_torch.backends.cudnn.benchmark is False
    assert cuda_torch.deterministic_calls == [(True, True)]
    assert os.environ["CUBLAS_WORKSPACE_CONFIG"] == device.CUBLAS_WORKSPACE


def test_mps_leaves_the_cuda_settings_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    torch = fake_torch(cuda=True, mps=True)
    monkeypatch.setattr(device, "_torch", lambda: torch)
    device.require("mps")
    assert torch.backends.cudnn.benchmark is True
    assert torch.deterministic_calls == []


def test_cuda_sync_peak_and_rng(cuda_torch: Any) -> None:
    device.sync("cuda")
    assert cuda_torch.cuda.calls == ["synchronize"]
    assert device.peak_tracker("cuda")() == 7_000.0
    assert device.peak_tracker("cpu")() == 0.0
    saved = device.accelerator_rng_state("cuda")
    assert saved == {"cuda_rng": "cuda-state"}
    device.set_accelerator_rng_state("cuda", {"cuda_rng": FakeTensor("restored")})
    assert cuda_torch.cuda.calls[-1] == "set_rng_state:restored"
    assert device.accelerator_rng_state("cpu") == {}


def test_a_checkpoint_without_cuda_state_restores_nothing(cuda_torch: Any) -> None:
    device.set_accelerator_rng_state("cuda", {"rng": FakeTensor("cpu only")})
    assert cuda_torch.cuda.calls == []


def test_machine_on_linux_reads_proc_and_never_asks_sysctl(
    cuda_torch: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "cpuinfo").write_text("processor\t: 0\nmodel name\t: FAKE EPYC 9654\n")
    (tmp_path / "meminfo").write_text("MemTotal:       65536000 kB\nMemFree: 1 kB\n")
    monkeypatch.setattr(device.sys, "platform", "linux")

    def no_sysctl() -> Any:
        raise AssertionError("sysctl was asked on Linux")

    monkeypatch.setattr(device, "_darwin_host", no_sysctl)
    identity = device.machine(proc=tmp_path)
    assert identity["chip"] == "FAKE EPYC 9654"
    assert identity["memory_bytes"] == 65536000 * 1024
    assert identity["cuda"]["name"] == "FAKE GPU"
    assert identity["cuda"]["capability"] == "8.9"
    assert identity["cuda_available"] is True


def test_machine_on_linux_without_proc_files(
    cuda_torch: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(device.sys, "platform", "linux")
    identity = device.machine(proc=tmp_path / "absent")
    assert identity["chip"] == "unknown"
    assert identity["memory_bytes"] == 0


@pytest.mark.parametrize(("path", "default"), sorted(PORTABLE.items()))
def test_entry_point_accepts_cuda_and_keeps_its_default(path: str, default: str) -> None:
    text = (SRC / path).read_text()
    assert f'add_device_argument(parser, default="{default}")' in text
    assert "choices=(" not in text.split("add_device_argument(parser")[1].split("\n")[0]
    assert re.search(r"args = parser\.parse_args\(argv\)\n\s+require\(args\.device\)", text)


@pytest.mark.parametrize(("path", "default"), sorted(MAC_ONLY.items()))
def test_mac_only_entry_points_stay_mac_only(path: str, default: str) -> None:
    text = (SRC / path).read_text()
    assert f'parser.add_argument("--device", choices=("mps", "cpu"), default="{default}")' in text


def test_no_other_entry_point_has_a_device_list_of_its_own() -> None:
    lists = {
        str(p.relative_to(SRC))
        for p in SRC.rglob("*.py")
        if 'parser.add_argument("--device", choices=' in p.read_text() and p.name != "device.py"
    }
    assert lists == set(MAC_ONLY)


def test_torch_mps_resume_matches_an_unbroken_run(tmp_path: Path) -> None:
    """On MPS (run by `make torch-test` on the Mac): resume restores MPS's generator too."""
    torch = pytest.importorskip("torch")
    if not torch.backends.mps.is_available():
        pytest.skip("MPS is not available on this machine")
    from test_family_sweep import _fake_data
    from vishwaroop.models.cube_study import VARIANTS, _Kinematics, _train

    data, stats = _fake_data(torch)
    data.device = "mps"
    data.windows_s = data.windows_s.to("mps")
    data.windows_a = data.windows_a.to("mps")
    data.delta_std = data.delta_std.to("mps")
    stats = {k: v.to("mps") if hasattr(v, "to") else v for k, v in stats.items()}
    stats["kinematics"] = _Kinematics("mps")
    variant = VARIANTS["carry-contact-beta-fall"]
    unbroken, _ = _train(data, stats, variant, 3, 3)
    path = tmp_path / "checkpoint.pt"
    _train(data, stats, variant, 3, 2, path)
    saved = torch.load(path, map_location="cpu", weights_only=True)
    assert "mps_rng" in saved
    resumed, training = _train(data, stats, variant, 3, 3, path)
    assert training["resumed_at_epoch"] == 2
    for layer, other in zip(unbroken, resumed, strict=True):
        for item, value in zip(layer, other, strict=True):
            assert torch.equal(item.cpu(), value.cpu())
