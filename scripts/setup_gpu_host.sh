#!/usr/bin/env bash
# Prepare an owner-provided Linux GPU machine, so the first paid hour is not spent installing.
#
#   scripts/setup_gpu_host.sh --check-only     # read-only: what this machine has and lacks
#   scripts/setup_gpu_host.sh                  # checks, pinned install, smoke episode
#
# It works inside this checkout only: a new venv (default venv/, which git ignores) and a new run directory
# under runs/. It never starts, stops or resizes a machine, installs system packages, uses sudo,
# resets a GPU, or spends anything. The owner starts and stops the machine. It never touches data/.
#
# Exit codes: 0 ok, 2 this machine lacks something, 3 install failed, 4 smoke failed.
set -euo pipefail

# ldconfig is often outside an ordinary user's PATH.
PATH="$PATH:/sbin:/usr/sbin"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK="$REPO/config/robotics-requirements.linux.txt"
FROZEN="$REPO/evals/M0-exit-tests.json"
ICD_DIRS="${VULKAN_ICD_SEARCH_DIRS:-/usr/share/vulkan/icd.d /etc/vulkan/icd.d}"
MIN_DISK_GB=20
MAX_GPU_MEMORY_USED_MIB=500
INSTALL_LIMIT_S=1800
SMOKE_LIMIT_S=600
SMOKE_SEED=12

VENV="$REPO/venv"
RUN_ID="gpu-smoke-$(date -u +%Y%m%dT%H%M%SZ)"
CHECK_ONLY=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --check-only) CHECK_ONLY=1 ;;
    --venv) shift; VENV="${1:?--venv needs a path}" ;;
    --run-id)
      shift
      RUN_ID="${1:?--run-id needs a name}"
      case "$RUN_ID" in
        *[!A-Za-z0-9._-]*|.*) echo "--run-id may hold letters, digits, dot, dash, underscore" >&2; exit 2 ;;
      esac
      ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

FAILED=0
ok() { echo "ok      $1"; }
lacks() { echo "LACKS   $1"; FAILED=1; }

echo "== checks (read-only)"
SYSTEM="$(uname -s)"
MACHINE="$(uname -m)"
if [ "$SYSTEM" = "Linux" ] && [ "$MACHINE" = "x86_64" ]; then
  ok "platform: $SYSTEM $MACHINE"
else
  lacks "platform: need Linux x86_64 for the pinned lock, found $SYSTEM $MACHINE"
fi

GPU_LINE=""
if command -v nvidia-smi >/dev/null 2>&1; then
  GPU_OUTPUT="$(nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used \
    --format=csv,noheader,nounits 2>/dev/null || true)"
  GPU_LINE="${GPU_OUTPUT%%$'\n'*}"
fi
if [ -n "$GPU_LINE" ]; then
  USED="$(echo "$GPU_LINE" | cut -d, -f4 | tr -d ' ')"
  ok "gpu and driver: $GPU_LINE (name, driver, MiB total, MiB used)"
  case "$USED" in
    ''|*[!0-9]*) lacks "gpu memory: nvidia-smi gave '$USED', not a number" ;;
    *)
      if [ "$USED" -gt "$MAX_GPU_MEMORY_USED_MIB" ]; then
        lacks "idle gpu: ${USED} MiB in use, above ${MAX_GPU_MEMORY_USED_MIB}; another job may be here (never reset it)"
      else
        ok "idle gpu: ${USED} MiB in use"
      fi
      ;;
  esac
else
  lacks "nvidia driver: nvidia-smi is missing or reports no GPU"
fi

# Read the whole cache first: with pipefail, an early-exiting grep would fail the pipeline.
LIBRARIES=""
if command -v ldconfig >/dev/null 2>&1; then
  LIBRARIES="$(ldconfig -p 2>/dev/null || true)"
fi
if [[ "$LIBRARIES" == *libvulkan.so.1* ]]; then
  ok "vulkan loader: libvulkan.so.1"
else
  lacks "vulkan loader: libvulkan.so.1 not found. Choose an image with it (Debian/Ubuntu package libvulkan1); this script installs no system packages"
fi

ICD_FILE="${VK_ICD_FILENAMES:-}"
NEED_WRITTEN_ICD=0
if [ -z "$ICD_FILE" ]; then
  for dir in $ICD_DIRS; do
    if [ -f "$dir/nvidia_icd.json" ]; then
      ICD_FILE="$dir/nvidia_icd.json"
      break
    fi
  done
fi
if [ -n "$ICD_FILE" ]; then
  ok "vulkan nvidia icd: $ICD_FILE"
elif [[ "$LIBRARIES" == *libGLX_nvidia.so.0* ]]; then
  NEED_WRITTEN_ICD=1
  ok "vulkan nvidia icd: none on disk, but libGLX_nvidia.so.0 exists; one will be written inside the venv"
else
  lacks "vulkan nvidia icd: no nvidia_icd.json and no libGLX_nvidia.so.0"
fi

FREE_KB="$(df -Pk "$REPO" | awk 'NR==2 {print $4}')"
if [ "$((FREE_KB / 1048576))" -ge "$MIN_DISK_GB" ]; then
  ok "disk: $((FREE_KB / 1048576)) GB free"
else
  lacks "disk: $((FREE_KB / 1048576)) GB free, need ${MIN_DISK_GB} GB"
fi

UV=""
if command -v uv >/dev/null 2>&1; then
  UV="uv"
  ok "installer: uv"
elif command -v python3.11 >/dev/null 2>&1; then
  ok "installer: python3.11 with venv and pip"
else
  lacks "installer: need uv, or python3.11 with venv"
fi

if [ -f "$LOCK" ] && [ -f "$FROZEN" ]; then
  ok "lock and frozen protocol present"
else
  lacks "this checkout lacks config/robotics-requirements.linux.txt or evals/M0-exit-tests.json"
fi

if [ "$FAILED" -ne 0 ]; then
  echo "== this machine is not ready; nothing was changed"
  exit 2
fi
if [ "$CHECK_ONLY" -eq 1 ]; then
  echo "== ready; nothing was changed (--check-only)"
  exit 0
fi

STARTED="$(date +%s)"
RUN_DIR="$REPO/runs/$RUN_ID"
if [ -e "$RUN_DIR" ]; then
  echo "refused: $RUN_DIR exists; runs are write-once" >&2
  exit 2
fi
if [ -e "$VENV" ]; then
  echo "refused: $VENV exists; pass a new --venv path, this script replaces nothing" >&2
  exit 2
fi
mkdir -p "$RUN_DIR"

echo "== install (pinned, hash-checked, at most ${INSTALL_LIMIT_S}s)"
if [ -n "$UV" ]; then
  uv venv --python 3.11 "$VENV"
  timeout "$INSTALL_LIMIT_S" uv pip install --python "$VENV/bin/python" --require-hashes \
    --no-deps -r "$LOCK" || { echo "install failed" >&2; exit 3; }
  uv pip freeze --python "$VENV/bin/python" > "$RUN_DIR/freeze.txt"
else
  python3.11 -m venv "$VENV"
  timeout "$INSTALL_LIMIT_S" "$VENV/bin/python" -m pip install --require-hashes --no-deps \
    -r "$LOCK" || { echo "install failed" >&2; exit 3; }
  "$VENV/bin/python" -m pip freeze > "$RUN_DIR/freeze.txt"
fi

if [ "$NEED_WRITTEN_ICD" -eq 1 ]; then
  ICD_FILE="$VENV/nvidia_icd.json"
  cat > "$ICD_FILE" <<'JSON'
{"file_format_version": "1.0.0", "ICD": {"library_path": "libGLX_nvidia.so.0", "api_version": "1.3"}}
JSON
  echo "wrote $ICD_FILE"
fi
export VK_ICD_FILENAMES="$ICD_FILE"
export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"
PY="$VENV/bin/python"

echo "== host record"
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader > "$RUN_DIR/gpu.txt"
uname -a > "$RUN_DIR/uname.txt"
timeout 120 "$PY" - <<'PYTHON' | tee "$RUN_DIR/versions.txt" || { echo "the pinned stack will not import" >&2; exit 3; }
import gymnasium, jsonschema, mani_skill, numpy, sapien, sys, torch
print("python", sys.version.split()[0])
for module in (mani_skill, sapien, torch, gymnasium, numpy, jsonschema):
    print(module.__name__, module.__version__)
print("torch.cuda.is_available", torch.cuda.is_available())
print("torch.version.cuda", torch.version.cuda)
PYTHON

echo "== smoke episode (at most ${SMOKE_LIMIT_S}s)"
cd "$REPO"
EPISODE="$RUN_DIR/episodes/m0-scripted-nominal-seed-$(printf '%06d' "$SMOKE_SEED")"
mkdir -p "$RUN_DIR/episodes"
timeout "$SMOKE_LIMIT_S" "$PY" -m vishwaroop.sim.record --seed "$SMOKE_SEED" --variant nominal \
  --run-id "$RUN_ID" --tolerance-file "$FROZEN" --out "$RUN_DIR/episodes" \
  || { echo "smoke: recording failed" >&2; exit 4; }
timeout "$SMOKE_LIMIT_S" "$PY" contracts/v1/validate.py "$EPISODE/episode.json" \
  > "$RUN_DIR/validate.json" || { echo "smoke: the contract rejected the episode" >&2; exit 4; }
timeout "$SMOKE_LIMIT_S" "$PY" -m vishwaroop.sim.replay --episode "$EPISODE" \
  --tolerance-file "$FROZEN" --repeats 3 --out "$RUN_DIR/replay.json" > /dev/null \
  || { echo "smoke: replay did not hold (see $RUN_DIR/replay.json)" >&2; exit 4; }

echo "== done in $(($(date +%s) - STARTED))s; evidence in $RUN_DIR"
echo "   Measured on this machine only. Send $RUN_DIR back, and leave stopping the machine to the owner."
