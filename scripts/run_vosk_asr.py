#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import add_repo_root

add_repo_root(__file__)

from resp_lanu.asr import recognize_wav


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run offline ASR with a Vosk model.")
    parser.add_argument(
        "model_dir", type=Path, help="Directory containing an extracted Vosk model."
    )
    parser.add_argument("input_wav", type=Path, help="Path to preprocessed 16 kHz mono PCM WAV.")
    parser.add_argument("output_json", type=Path, help="Path to save ASR result JSON.")
    parser.add_argument(
        "--grammar-file",
        type=Path,
        default=None,
        help="Optional JSON list of allowed phrases for grammar-constrained decoding.",
    )
    parser.add_argument(
        "--phrase-hints-file",
        type=Path,
        default=None,
        help="Optional JSON phrase hints for post-processing merges and domain-term corrections.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = recognize_wav(
        args.model_dir,
        args.input_wav,
        args.grammar_file,
        args.phrase_hints_file,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
