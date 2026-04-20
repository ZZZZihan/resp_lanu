#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_WAV="${1:-$ROOT_DIR/sample_audio/live_record.wav}"
DURATION_SECONDS="${2:-5}"
ARECORD_DEVICE="${ARECORD_DEVICE:-}"

if ! command -v arecord >/dev/null 2>&1; then
  echo "arecord 未安装，请先安装 alsa-utils。"
  exit 1
fi

if ! arecord -l 2>/dev/null | grep -q 'card'; then
  echo "没有检测到录音设备。当前机器上可以先使用 sample_audio/demo_cn.wav 跑通完整流程。"
  exit 1
fi

if [ -z "$ARECORD_DEVICE" ]; then
  first_capture_line="$(arecord -l 2>/dev/null | awk '/^card [0-9]+:.*device [0-9]+:/ {print; exit}')"
  if [ -z "$first_capture_line" ]; then
    echo "检测到了录音设备列表，但无法解析出可用的采集卡。"
    exit 1
  fi

  card_num="$(printf '%s\n' "$first_capture_line" | sed -E 's/^card ([0-9]+):.*/\1/')"
  device_num="$(printf '%s\n' "$first_capture_line" | sed -E 's/.*device ([0-9]+):.*/\1/')"
  ARECORD_DEVICE="plughw:${card_num},${device_num}"
fi

mkdir -p "$(dirname "$OUTPUT_WAV")"
echo "使用录音设备: $ARECORD_DEVICE"
arecord -D "$ARECORD_DEVICE" -r 16000 -c 1 -f S16_LE -d "$DURATION_SECONDS" -t wav "$OUTPUT_WAV"
echo "录音完成: $OUTPUT_WAV"
