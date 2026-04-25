#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
MODEL_NAME="${MODEL_NAME:-vosk-model-small-cn-0.22}"
MODEL_URL="${MODEL_URL:-https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip}"
PROFILE="${PROFILE:-pi-offline}"

need_install=0
for cmd in python3 curl unzip ffmpeg arecord espeak-ng; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    need_install=1
  fi
done
if ! python3 -c "import tkinter" >/dev/null 2>&1; then
  need_install=1
fi

if [ "$need_install" -eq 1 ]; then
  sudo apt-get update
  sudo apt-get install -y python3-venv python3-tk curl unzip ffmpeg alsa-utils espeak-ng
fi

python3 -m venv "$VENV_DIR"
source "${VENV_DIR}/bin/activate"
python -m pip install -U pip setuptools wheel
python -m pip install "${ROOT_DIR}[pi]"

mkdir -p "${ROOT_DIR}/models"
if [ ! -d "${ROOT_DIR}/models/${MODEL_NAME}" ]; then
  tmp_dir="$(mktemp -d)"
  trap 'rm -rf "${tmp_dir}"' EXIT
  curl -L "${MODEL_URL}" -o "${tmp_dir}/${MODEL_NAME}.zip"
  unzip -q "${tmp_dir}/${MODEL_NAME}.zip" -d "${ROOT_DIR}/models"
fi

echo "环境准备完成。激活命令: source ${VENV_DIR}/bin/activate"
echo "模型目录: ${ROOT_DIR}/models/${MODEL_NAME}"
echo "启动服务示例: RESP_LANU_PROFILE=${PROFILE} ${VENV_DIR}/bin/resp-lanu-serve --profile ${PROFILE} --host 0.0.0.0 --port 8000"
