#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${1:-pi-offline}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

if [ ! -d "${ROOT_DIR}/.venv" ]; then
  echo "请先运行 scripts/setup_pi.sh"
  exit 1
fi

source "${ROOT_DIR}/.venv/bin/activate"
export RESP_LANU_PROFILE="${PROFILE}"
resp-lanu-serve --profile "${PROFILE}" --host "${HOST}" --port "${PORT}"
