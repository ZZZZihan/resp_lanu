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

python "${ROOT_DIR}/scripts/preprocess_audio.py" \
  "${INPUT_WAV}" \
  "${OUTPUT_DIR}/preprocessed.wav" \
  --summary-json "${OUTPUT_DIR}/preprocess_summary.json"

python "${ROOT_DIR}/scripts/extract_features.py" \
  "${OUTPUT_DIR}/preprocessed.wav" \
  "${OUTPUT_DIR}/features"

asr_cmd=(
  python "${ROOT_DIR}/scripts/run_vosk_asr.py"
  "${MODEL_DIR}"
  "${OUTPUT_DIR}/preprocessed.wav"
  "${OUTPUT_DIR}/asr_result.json"
)

if [ -n "${GRAMMAR_FILE}" ]; then
  asr_cmd+=(--grammar-file "${GRAMMAR_FILE}")
fi

if [ -n "${PHRASE_HINTS_FILE}" ]; then
  asr_cmd+=(--phrase-hints-file "${PHRASE_HINTS_FILE}")
fi

"${asr_cmd[@]}"

python - <<'PY' "${OUTPUT_DIR}/asr_result.json"
from pathlib import Path
import json
import sys

result = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print("最终识别结果:")
print(result["transcript"])
if result.get("corrections"):
    print("后处理修正:")
    for item in result["corrections"]:
        avg_conf = item.get("avg_conf")
        suffix = "" if avg_conf is None else f" (avg_conf={avg_conf})"
        print(f"- {item['from']} -> {item['to']} [{item['match_type']}]{suffix}")
PY

echo "实验结果目录: ${OUTPUT_DIR}"
