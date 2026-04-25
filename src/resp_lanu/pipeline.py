from __future__ import annotations

import json
from pathlib import Path

from .asr import recognize_wav
from .audio import preprocess_audio
from .features import extract_feature_bundle, save_feature_bundle


def _write_json(path: str | Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_asr_pipeline(
    input_wav: str | Path,
    output_dir: str | Path,
    model_dir: str | Path,
    grammar_file: str | Path | None = None,
    phrase_hints_file: str | Path | None = None,
) -> dict:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    preprocessed_wav = output_dir / "preprocessed.wav"
    preprocess_summary = preprocess_audio(input_wav, preprocessed_wav)
    preprocess_summary_dict = json.loads(preprocess_summary.to_json())
    _write_json(output_dir / "preprocess_summary.json", preprocess_summary_dict)

    feature_bundle, feature_summary = extract_feature_bundle(preprocessed_wav)
    save_feature_bundle(output_dir / "features", feature_bundle, feature_summary)

    asr_result = recognize_wav(
        model_path=model_dir,
        wav_path=preprocessed_wav,
        grammar_path=grammar_file,
        phrase_hints_path=phrase_hints_file,
    )
    _write_json(output_dir / "asr_result.json", asr_result)

    return {
        "output_dir": str(output_dir),
        "preprocessed_wav": str(preprocessed_wav),
        "preprocess_summary": preprocess_summary_dict,
        "feature_summary": feature_summary,
        "asr_result": asr_result,
    }
