#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT_WAV="${1:-${ROOT_DIR}/sample_audio/demo_cn.wav}"
RUN_TAG="${2:-run_$(date +%Y%m%d_%H%M%S)}"
MODEL_DIR="${3:-${ROOT_DIR}/models/vosk-model-small-cn-0.22}"
GRAMMAR_FILE="${4:-}"
PHRASE_HINTS_FILE="${5:-}"
OUTPUT_DIR="${ROOT_DIR}/artifacts/${RUN_TAG}"

if [ ! -d "${ROOT_DIR}/.venv" ]; then
  echo "请先运行 scripts/setup_pi.sh"
  exit 1
fi

source "${ROOT_DIR}/.venv/bin/activate"
mkdir -p "${OUTPUT_DIR}"

pipeline_cmd=(
  python "${ROOT_DIR}/scripts/run_pipeline.py"
  "${INPUT_WAV}"
  "${OUTPUT_DIR}"
  "${MODEL_DIR}"
)

if [ -n "${GRAMMAR_FILE}" ]; then
  pipeline_cmd+=(--grammar-file "${GRAMMAR_FILE}")
fi

if [ -n "${PHRASE_HINTS_FILE}" ]; then
  pipeline_cmd+=(--phrase-hints-file "${PHRASE_HINTS_FILE}")
fi

"${pipeline_cmd[@]}"

echo "实验结果目录: ${OUTPUT_DIR}"
