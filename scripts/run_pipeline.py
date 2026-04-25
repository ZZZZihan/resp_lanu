#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import add_repo_root

add_repo_root(__file__)

from resp_lanu.pipeline import run_asr_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the full Raspberry Pi ASR pipeline.")
    parser.add_argument("input_wav", type=Path, help="Path to the input WAV file.")
    parser.add_argument("output_dir", type=Path, help="Directory to save pipeline outputs.")
    parser.add_argument(
        "model_dir", type=Path, help="Directory containing an extracted Vosk model."
    )
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
    result = run_asr_pipeline(
        input_wav=args.input_wav,
        output_dir=args.output_dir,
        model_dir=args.model_dir,
        grammar_file=args.grammar_file,
        phrase_hints_file=args.phrase_hints_file,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("最终识别结果:")
    print(result["asr_result"]["transcript"])
    if result["asr_result"].get("corrections"):
        print("后处理修正:")
        for item in result["asr_result"]["corrections"]:
            avg_conf = item.get("avg_conf")
            suffix = "" if avg_conf is None else f" (avg_conf={avg_conf})"
            print(f"- {item['from']} -> {item['to']} [{item['match_type']}]{suffix}")


if __name__ == "__main__":
    main()
