#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import add_repo_root

add_repo_root(__file__)

from resp_lanu.features import extract_feature_bundle, save_feature_bundle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract MFCC/filter-bank features from WAV audio."
    )
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
