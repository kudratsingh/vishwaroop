"""The GPU host script, against stubbed commands. No machine, GPU or real install is involved."""

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
NVIDIA_ICD = '{"ICD": {"library_path": "libGLX_nvidia.so.0"}}'

# Stands in for the venv's Python. FAIL names the step that should fail.
FAKE_PYTHON = r"""
case "$1 $2" in
  "- "*)
    body="$(cat)"
    case "$body" in
      *physx_cuda*)
        [ "$FAIL" = gpu ] && { echo "torch cannot use the GPU"; exit 1; }
        echo gpu ok
        ;;
      *) [ "$FAIL" = import ] && { echo "ImportError"; exit 1; }; echo versions ok ;;
    esac
    ;;
  "-m vishwaroop.sim.record")
    [ "$FAIL" = record ] && { echo "refused: recording"; exit 2; }
    echo recorded
    ;;
  "-m vishwaroop.sim.replay")
    [ "$FAIL" = replay ] && { echo "REFUSED: replay reason"; exit 2; }
    echo replayed
    ;;
  "contracts/v1/validate.py "*)
    [ "$FAIL" = validate ] && { echo "contract rejected"; exit 2; }
    echo contract_valid
    ;;
esac
exit 0
"""

FAKE_UV = r"""
case "$1 $2" in
  "venv "*)
    [ "$FAIL" = venv ] && { echo "no python here"; exit 1; }
    target="$(echo "$@" | awk '{print $NF}')"
    mkdir -p "$target/bin"
    cp "$FAKE_PYTHON_FILE" "$target/bin/python"
    ;;
  "pip install")
    [ "$FAIL" = install ] && { echo "hash mismatch"; exit 1; }
    case "$*" in *--require-hashes*--no-deps*) echo installed ;; *) exit 9 ;; esac
    ;;
  "pip freeze") echo "mani-skill==3.0.1" ;;
esac
"""


def _stub(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


class Host:
    """A FABRICATED machine: stubbed commands on PATH, and run output kept in a temporary folder."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        system: str = "Linux",
        nvidia: str | None = GOOD_NVIDIA,
        ldconfig: str = GOOD_LDCONFIG,
        free_kb: int = 100 * 1048576,
        uv: bool = True,
        python311: str | None = None,
        timeout: bool = True,
    ) -> None:
        self.tmp = tmp_path
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.icd = tmp_path / "icd"
        self.icd.mkdir()
        (self.icd / "nvidia_icd.json").write_text(NVIDIA_ICD, encoding="utf-8")
        self.venv = tmp_path / "new-venv"
        self.runs = tmp_path / "new-runs"
        self.python_file = _stub(tmp_path, "fake-python", FAKE_PYTHON)
        _stub(
            self.bin,
            "uname",
            f'case "$1" in -s) echo {system};; -m) echo x86_64;; *) echo x;; esac',
        )
        if nvidia is not None:
            _stub(self.bin, "nvidia-smi", nvidia)
        _stub(self.bin, "ldconfig", ldconfig)
        _stub(self.bin, "df", f'echo Header; echo "disk 1 1 {free_kb} 1% /"')
        if uv:
            _stub(self.bin, "uv", FAKE_UV)
        if python311 is not None:
            _stub(self.bin, "python3.11", python311)
        if timeout:
            _stub(self.bin, "timeout", 'shift; exec "$@"')

    def run(self, *args: str, fail: str = "", **env_extra: str) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": f"{self.bin}{os.pathsep}/usr/bin{os.pathsep}/bin",
            "VULKAN_ICD_SEARCH_DIRS": str(self.icd),
            "FAKE_PYTHON_FILE": str(self.python_file),
            "FAIL": fail,
            **env_extra,
        }
        bash = shutil.which("bash")
        assert bash is not None
        return subprocess.run(
            [bash, str(SCRIPT), "--venv", str(self.venv), "--run-root", str(self.runs), *args],
            capture_output=True,
            text=True,
            env=env,
            check=False,
            cwd=self.tmp,
        )

    def run_dir(self, name: str = "t") -> Path:
        return self.runs / name


def test_a_good_machine_passes_the_check_and_nothing_is_changed(tmp_path: Path) -> None:
    host = Host(tmp_path)
    before = sorted(path.name for path in ROOT.iterdir())
    result = host.run("--check-only")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "nothing was changed" in result.stdout
    assert sorted(path.name for path in ROOT.iterdir()) == before
    assert not host.venv.exists()
    assert not host.runs.exists()


def test_a_mac_is_refused(tmp_path: Path) -> None:
    result = Host(tmp_path, system="Darwin").run("--check-only")
    assert result.returncode == 2
    assert "need Linux x86_64" in result.stdout


def test_a_missing_driver_is_reported(tmp_path: Path) -> None:
    result = Host(tmp_path, nvidia=None).run("--check-only")
    assert result.returncode == 2
    assert "nvidia driver" in result.stdout


def test_a_driver_that_reports_no_gpu_is_reported(tmp_path: Path) -> None:
    result = Host(tmp_path, nvidia="exit 9").run("--check-only")
    assert result.returncode == 2
    assert "nvidia driver" in result.stdout


def test_a_busy_gpu_is_refused_and_never_reset(tmp_path: Path) -> None:
    result = Host(tmp_path, nvidia='echo "NVIDIA Test GPU, 570.1, 24000, 9000"').run("--check-only")
    assert result.returncode == 2
    assert "9000 MiB in use" in result.stdout


def test_a_busy_second_gpu_is_refused_too(tmp_path: Path) -> None:
    both = 'echo "GPU A, 570.1, 24000, 3"; echo "GPU B, 570.1, 24000, 23000"'
    result = Host(tmp_path, nvidia=both).run("--check-only")
    assert result.returncode == 2
    assert "23000 MiB in use" in result.stdout


def test_an_unreadable_gpu_memory_figure_is_refused(tmp_path: Path) -> None:
    result = Host(tmp_path, nvidia='echo "NVIDIA Test GPU, 570.1, 24000, [N/A]"').run(
        "--check-only"
    )
    assert result.returncode == 2
    assert "not a number" in result.stdout


def test_a_missing_vulkan_loader_is_reported(tmp_path: Path) -> None:
    result = Host(tmp_path, ldconfig="exit 0").run("--check-only")
    assert result.returncode == 2
    assert "libvulkan.so.1 not found" in result.stdout


def test_a_large_library_cache_does_not_break_the_loader_check(tmp_path: Path) -> None:
    # A grep that stopped early would kill ldconfig and, under pipefail, read as a missing library.
    body = (
        'i=0; while [ $i -lt 5000 ]; do echo "libfiller$i.so"; i=$((i+1)); done; ' + GOOD_LDCONFIG
    )
    assert Host(tmp_path, ldconfig=body).run("--check-only").returncode == 0


def test_no_icd_file_is_fine_when_the_library_exists(tmp_path: Path) -> None:
    body = 'echo "libvulkan.so.1 => x"; echo "libGLX_nvidia.so.0 => y"'
    host = Host(tmp_path, ldconfig=body)
    (host.icd / "nvidia_icd.json").unlink()
    result = host.run("--check-only")
    assert result.returncode == 0, result.stdout
    assert "will be written inside the venv" in result.stdout


def test_no_icd_at_all_is_reported(tmp_path: Path) -> None:
    host = Host(tmp_path)
    (host.icd / "nvidia_icd.json").unlink()
    result = host.run("--check-only")
    assert result.returncode == 2
    assert "no nvidia_icd.json" in result.stdout


def test_a_preset_icd_path_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    result = Host(tmp_path).run("--check-only", VK_ICD_FILENAMES="/does/not/exist.json")
    assert result.returncode == 2
    assert "does not exist" in result.stdout


def test_a_preset_icd_for_another_driver_is_refused(tmp_path: Path) -> None:
    lavapipe = tmp_path / "lvp_icd.json"
    lavapipe.write_text('{"ICD": {"library_path": "libvulkan_lvp.so"}}', encoding="utf-8")
    result = Host(tmp_path).run("--check-only", VK_ICD_FILENAMES=str(lavapipe))
    assert result.returncode == 2
    assert "does not name NVIDIA" in result.stdout


def test_a_full_disk_is_reported(tmp_path: Path) -> None:
    result = Host(tmp_path, free_kb=1048576).run("--check-only")
    assert result.returncode == 2
    assert "need 20 GB" in result.stdout


def test_a_broken_python311_does_not_count_as_an_installer(tmp_path: Path) -> None:
    result = Host(tmp_path, uv=False, python311="exit 1").run("--check-only")
    assert result.returncode == 2
    assert "installer" in result.stdout


def test_a_working_python311_counts_as_an_installer(tmp_path: Path) -> None:
    assert Host(tmp_path, uv=False, python311="exit 0").run("--check-only").returncode == 0


def test_a_machine_without_timeout_is_reported(tmp_path: Path) -> None:
    host = Host(tmp_path, timeout=False)
    if shutil.which("timeout", path=f"{os.pathsep}/usr/bin{os.pathsep}/bin"):
        pytest.skip("this machine has a real timeout in /usr/bin")
    result = host.run("--check-only")
    assert result.returncode == 2
    assert "timeout" in result.stdout


def test_an_existing_venv_is_reported_by_the_check(tmp_path: Path) -> None:
    host = Host(tmp_path)
    host.venv.mkdir()
    result = host.run("--check-only")
    assert result.returncode == 2
    assert "replaces nothing" in result.stdout


def test_an_existing_run_directory_is_reported_by_the_check(tmp_path: Path) -> None:
    host = Host(tmp_path)
    host.run_dir().mkdir(parents=True)
    result = host.run("--check-only", "--run-id", "t")
    assert result.returncode == 2
    assert "write-once" in result.stdout


@pytest.mark.parametrize("name", ["../escape", ".hidden", "a b", "a/b", ""])
def test_unsafe_run_ids_are_refused(tmp_path: Path, name: str) -> None:
    assert Host(tmp_path).run("--check-only", "--run-id", name).returncode == 2


@pytest.mark.parametrize("flag", ["--venv", "--run-id", "--run-root"])
def test_a_flag_without_a_value_is_exit_two(tmp_path: Path, flag: str) -> None:
    host = Host(tmp_path)
    result = host.run(flag)
    assert result.returncode == 2
    assert "needs a" in result.stderr


def test_unknown_arguments_are_refused(tmp_path: Path) -> None:
    assert Host(tmp_path).run("--yes").returncode == 2


@pytest.mark.parametrize("protected", ["data", "runs", "ledgers", "reports", "artifacts"])
def test_a_venv_inside_an_append_only_directory_is_refused(tmp_path: Path, protected: str) -> None:
    bash = shutil.which("bash")
    assert bash is not None
    done = subprocess.run(
        [bash, str(SCRIPT), "--check-only", "--venv", str(ROOT / protected / "x")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 2
    assert "append-only" in done.stderr
    assert not (ROOT / protected / "x").exists()


def test_a_full_run_leaves_its_evidence_and_says_the_machine_is_still_running(
    tmp_path: Path,
) -> None:
    host = Host(tmp_path)
    result = host.run("--run-id", "t")
    assert result.returncode == 0, result.stdout + result.stderr
    run = host.run_dir()
    assert (run / "freeze.txt").read_text(encoding="utf-8").strip() == "mani-skill==3.0.1"
    for name in ("install.log", "gpu.txt", "uname.txt", "versions.txt", "gpu-check.log"):
        assert (run / name).is_file(), name
    assert "contract_valid" in (run / "validate.json").read_text(encoding="utf-8")
    assert "smoke passed" in result.stdout
    assert "does not stop it" in result.stdout


def test_a_relative_venv_still_works_after_changing_directory(tmp_path: Path) -> None:
    host = Host(tmp_path)
    bash = shutil.which("bash")
    assert bash is not None
    done = subprocess.run(
        [
            bash,
            str(SCRIPT),
            "--venv",
            "relative-venv",
            "--run-root",
            "relative-runs",
            "--run-id",
            "t",
        ],
        capture_output=True,
        text=True,
        env={
            "PATH": f"{host.bin}{os.pathsep}/usr/bin{os.pathsep}/bin",
            "VULKAN_ICD_SEARCH_DIRS": str(host.icd),
            "FAKE_PYTHON_FILE": str(host.python_file),
            "FAIL": "",
        },
        check=False,
        cwd=tmp_path,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert (tmp_path / "relative-venv" / "bin" / "python").is_file()
    assert (tmp_path / "relative-runs" / "t" / "replay.stdout").is_file()


@pytest.mark.parametrize(
    ("fail", "code", "evidence", "text"),
    [
        ("venv", 3, "install.log", "no python here"),
        ("install", 3, "install.log", "hash mismatch"),
        ("import", 3, "versions.txt", "ImportError"),
        ("gpu", 4, "gpu-check.log", "torch cannot use the GPU"),
        ("record", 4, "record.log", "refused: recording"),
        ("validate", 4, "validate.json", "contract rejected"),
        ("replay", 4, "replay.stdout", "REFUSED: replay reason"),
    ],
)
def test_each_failure_has_its_exit_code_keeps_its_reason_and_reminds_about_the_machine(
    tmp_path: Path, fail: str, code: int, evidence: str, text: str
) -> None:
    host = Host(tmp_path)
    result = host.run("--run-id", "t", fail=fail)
    assert result.returncode == code, result.stdout + result.stderr
    assert text in (host.run_dir() / evidence).read_text(encoding="utf-8")
    assert "smoke passed" not in result.stdout
    assert "does not stop it" in result.stdout


def test_an_icd_is_written_inside_the_venv_only_when_needed(tmp_path: Path) -> None:
    body = 'echo "libvulkan.so.1 => x"; echo "libGLX_nvidia.so.0 => y"'
    host = Host(tmp_path, ldconfig=body)
    (host.icd / "nvidia_icd.json").unlink()
    assert host.run("--run-id", "t").returncode == 0
    assert "libGLX_nvidia" in (host.venv / "nvidia_icd.json").read_text(encoding="utf-8")


def test_the_gpu_check_fails_the_run_rather_than_only_printing(tmp_path: Path) -> None:
    result = Host(tmp_path).run("--run-id", "t", fail="gpu")
    assert result.returncode == 4
    assert "gpu check failed" in result.stderr


def test_the_script_holds_no_lifecycle_or_system_commands() -> None:
    code = "\n".join(
        line
        for line in SCRIPT.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    forbidden = (
        r"\b(sudo|apt|apt-get|yum|dnf|runpodctl|runpod|vastai|aws|gcloud|az|docker|systemctl|"
        r"service|pkill|killall|kill|curl|wget|shutdown|poweroff|reboot|halt|rm)\b"
    )
    stripped = code.replace("Debian/Ubuntu package libvulkan1", "")
    assert re.findall(forbidden, stripped) == []
    assert "--gpu-reset" not in code
    assert "nvidia-smi -r" not in code


def test_every_lock_entry_is_pinned_and_followed_by_a_hash() -> None:
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
    lines = text.splitlines()
    pins = [i for i, line in enumerate(lines) if re.match(r"^[A-Za-z0-9_.-]+==\S+ \\$", line)]
    assert len(pins) == len([line for line in lines if re.match(r"^[A-Za-z0-9_.-]+==", line)])
    assert len(pins) > 50
    for index in pins:
        assert re.match(r"^ +--hash=sha256:[0-9a-f]{64}", lines[index + 1]), lines[index]
    assert "Status: proposed" in text
