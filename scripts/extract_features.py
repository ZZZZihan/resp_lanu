#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import json
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from resp_lanu.features import extract_feature_bundle, save_feature_bundle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract MFCC/filter-bank features from WAV audio.")
    parser.add_argument("input_wav", type=Path, help="Path to preprocessed 16 kHz WAV.")
    parser.add_argument("output_dir", type=Path, help="Directory to save features and summary.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    bundle, summary = extract_feature_bundle(args.input_wav)
    save_feature_bundle(args.output_dir, bundle, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
