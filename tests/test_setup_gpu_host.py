"""The GPU host script, against stubbed system commands. No machine, GPU or install is involved."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "setup_gpu_host.sh"
LOCK = ROOT / "config" / "robotics-requirements.linux.txt"

GOOD_NVIDIA = 'echo "NVIDIA Test GPU, 570.1, 24000, 3"'
GOOD_LDCONFIG = 'echo "libvulkan.so.1 (libc6,x86-64) => /lib/libvulkan.so.1"'


def _stub(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _stubs(
    tmp_path: Path,
    *,
    system: str = "Linux",
    nvidia: str | None = GOOD_NVIDIA,
    ldconfig: str = GOOD_LDCONFIG,
    free_kb: int = 100 * 1048576,
) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    icd = tmp_path / "icd"
    icd.mkdir()
    (icd / "nvidia_icd.json").write_text("{}", encoding="utf-8")
    _stub(bin_dir, "uname", f'case "$1" in -s) echo {system};; -m) echo x86_64;; esac')
    if nvidia is not None:
        _stub(bin_dir, "nvidia-smi", nvidia)
    _stub(bin_dir, "ldconfig", ldconfig)
    _stub(bin_dir, "df", f'echo Header; echo "disk 1 1 {free_kb} 1% /"')
    _stub(bin_dir, "uv", "exit 0")
    return bin_dir, icd


def _run(
    bin_dir: Path, icd: Path, *args: str, tmp_path: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin",
        "VULKAN_ICD_SEARCH_DIRS": str(icd),
    }
    bash = shutil.which("bash")
    assert bash is not None
    return subprocess.run(
        [bash, str(SCRIPT), *args], capture_output=True, text=True, env=env, check=False
    )


def test_a_good_machine_passes_the_check_and_nothing_is_changed(tmp_path: Path) -> None:
    bin_dir, icd = _stubs(tmp_path)
    before = sorted(path.name for path in ROOT.iterdir())
    result = _run(bin_dir, icd, "--check-only")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "nothing was changed" in result.stdout
    assert sorted(path.name for path in ROOT.iterdir()) == before


def test_a_mac_is_refused(tmp_path: Path) -> None:
    bin_dir, icd = _stubs(tmp_path, system="Darwin")
    result = _run(bin_dir, icd, "--check-only")
    assert result.returncode == 2
    assert "need Linux x86_64" in result.stdout


def test_a_missing_driver_is_reported(tmp_path: Path) -> None:
    bin_dir, icd = _stubs(tmp_path, nvidia=None)
    result = _run(bin_dir, icd, "--check-only")
    assert result.returncode == 2
    assert "nvidia driver" in result.stdout


def test_a_driver_that_reports_no_gpu_is_reported(tmp_path: Path) -> None:
    bin_dir, icd = _stubs(tmp_path, nvidia="exit 9")
    result = _run(bin_dir, icd, "--check-only")
    assert result.returncode == 2
    assert "nvidia driver" in result.stdout


def test_a_busy_gpu_is_refused_and_never_reset(tmp_path: Path) -> None:
    bin_dir, icd = _stubs(tmp_path, nvidia='echo "NVIDIA Test GPU, 570.1, 24000, 9000"')
    result = _run(bin_dir, icd, "--check-only")
    assert result.returncode == 2
    assert "9000 MiB in use" in result.stdout


def test_an_unreadable_gpu_memory_figure_is_refused(tmp_path: Path) -> None:
    bin_dir, icd = _stubs(tmp_path, nvidia='echo "NVIDIA Test GPU, 570.1, 24000, [N/A]"')
    result = _run(bin_dir, icd, "--check-only")
    assert result.returncode == 2
    assert "not a number" in result.stdout


def test_a_missing_vulkan_loader_is_reported(tmp_path: Path) -> None:
    bin_dir, icd = _stubs(tmp_path, ldconfig="exit 0")
    result = _run(bin_dir, icd, "--check-only")
    assert result.returncode == 2
    assert "libvulkan.so.1 not found" in result.stdout


def test_a_large_library_cache_does_not_break_the_loader_check(tmp_path: Path) -> None:
    # A grep that stopped early would kill ldconfig and, under pipefail, read as a missing library.
    body = (
        'i=0; while [ $i -lt 5000 ]; do echo "libfiller$i.so"; i=$((i+1)); done; ' + GOOD_LDCONFIG
    )
    bin_dir, icd = _stubs(tmp_path, ldconfig=body)
    assert _run(bin_dir, icd, "--check-only").returncode == 0


def test_no_icd_file_is_fine_when_the_library_exists(tmp_path: Path) -> None:
    body = 'echo "libvulkan.so.1 => x"; echo "libGLX_nvidia.so.0 => y"'
    bin_dir, icd = _stubs(tmp_path, ldconfig=body)
    (icd / "nvidia_icd.json").unlink()
    result = _run(bin_dir, icd, "--check-only")
    assert result.returncode == 0, result.stdout
    assert "will be written inside the venv" in result.stdout


def test_no_icd_at_all_is_reported(tmp_path: Path) -> None:
    bin_dir, icd = _stubs(tmp_path)
    (icd / "nvidia_icd.json").unlink()
    result = _run(bin_dir, icd, "--check-only")
    assert result.returncode == 2
    assert "no nvidia_icd.json" in result.stdout


def test_a_full_disk_is_reported(tmp_path: Path) -> None:
    bin_dir, icd = _stubs(tmp_path, free_kb=1048576)
    result = _run(bin_dir, icd, "--check-only")
    assert result.returncode == 2
    assert "need 20 GB" in result.stdout


@pytest.mark.parametrize("name", ["../escape", ".hidden", "a b", "a/b"])
def test_unsafe_run_ids_are_refused(tmp_path: Path, name: str) -> None:
    bin_dir, icd = _stubs(tmp_path)
    assert _run(bin_dir, icd, "--check-only", "--run-id", name).returncode == 2


def test_unknown_arguments_are_refused(tmp_path: Path) -> None:
    bin_dir, icd = _stubs(tmp_path)
    assert _run(bin_dir, icd, "--yes").returncode == 2


def test_the_script_holds_no_lifecycle_or_system_commands() -> None:
    code = "\n".join(
        line
        for line in SCRIPT.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    forbidden = r"\b(sudo|apt|apt-get|yum|dnf|runpodctl|vastai|shutdown|poweroff|reboot|halt|rm)\b"
    assert re.findall(forbidden, code) == []
    assert "--gpu-reset" not in code
    assert "nvidia-smi -r" not in code
    assert " data/" not in code


def test_the_lock_pins_the_stack_with_hashes() -> None:
    text = LOCK.read_text(encoding="utf-8")
    for pin in (
        "mani-skill==3.0.1",
        "sapien==3.0.3",
        "torch==2.15.0",
        "gymnasium==1.4.0",
        "numpy==2.4.6",
        "jsonschema==4.26.0",
    ):
        assert f"{pin} \\" in text, pin
    pinned = re.findall(r"^[A-Za-z0-9_.-]+==\S+ \\$", text, flags=re.MULTILINE)
    assert len(pinned) == len(re.findall(r"^[A-Za-z0-9_.-]+==", text, flags=re.MULTILINE))
    assert "Status: proposed" in text
