#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from resp_lanu.audio import preprocess_audio


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preprocess audio for Raspberry Pi ASR experiments.")
    parser.add_argument("input_wav", type=Path, help="Path to input WAV file.")
    parser.add_argument("output_wav", type=Path, help="Path to output 16 kHz mono PCM WAV.")
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=None,
        help="Optional path to save preprocessing metadata as JSON.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    summary = preprocess_audio(args.input_wav, args.output_wav)
    if args.summary_json is not None:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(summary.to_json(), encoding="utf-8")
    print(summary.to_json())


if __name__ == "__main__":
    main()
