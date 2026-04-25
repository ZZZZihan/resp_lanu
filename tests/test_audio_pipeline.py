from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from resp_lanu.audio import preprocess_audio
from resp_lanu.features import extract_feature_bundle, save_feature_bundle
from resp_lanu.pipeline import run_asr_pipeline


def test_preprocess_audio_resamples_to_16k_and_mono() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        sr = 22050
        t = np.linspace(0.0, 1.0, sr, endpoint=False)
        tone = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        stereo = np.column_stack([tone, tone])
        input_wav = tmp_path / "input.wav"
        output_wav = tmp_path / "output.wav"
        wavfile.write(input_wav, sr, (stereo * 32767).astype(np.int16))

        summary = preprocess_audio(input_wav, output_wav)
        out_sr, out_data = wavfile.read(output_wav)

        assert out_sr == 16000
        assert out_data.ndim == 1
        assert summary.output_duration_s > 0.2
        assert np.max(np.abs(out_data)) <= 32767


def test_extract_feature_bundle_returns_expected_shapes() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        sr = 16000
        t = np.linspace(0.0, 1.0, sr, endpoint=False)
        tone = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        wav_path = tmp_path / "tone.wav"
        wavfile.write(wav_path, sr, (tone * 32767).astype(np.int16))

        bundle, summary = extract_feature_bundle(wav_path)

        assert bundle["mfcc"].shape[1] == 13
        assert bundle["delta"].shape == bundle["mfcc"].shape
        assert bundle["delta2"].shape == bundle["mfcc"].shape
        assert "zero_crossing_rate" in summary
        assert summary["duration_s"] > 0.9


def test_save_feature_bundle_writes_expected_files() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        output_dir = Path(tmp_dir) / "features"
        bundle = {
            "mfcc": np.ones((3, 13), dtype=np.float32),
            "delta": np.zeros((3, 13), dtype=np.float32),
            "delta2": np.full((3, 13), 2.0, dtype=np.float32),
            "fbank": np.ones((3, 26), dtype=np.float32),
            "frame_energy": np.array([0.1, 0.2, 0.3], dtype=np.float32),
        }
        summary = {"sample_rate": 16000, "mfcc_shape": [3, 13]}

        save_feature_bundle(output_dir, bundle, summary)

        assert (output_dir / "mfcc.npy").exists()
        assert (output_dir / "delta.npy").exists()
        assert (output_dir / "delta2.npy").exists()
        assert (output_dir / "fbank.npy").exists()
        assert (output_dir / "frame_energy.npy").exists()
        saved_summary = json.loads(
            (output_dir / "feature_summary.json").read_text(encoding="utf-8")
        )
        assert saved_summary["sample_rate"] == 16000
        assert saved_summary["mfcc_shape"] == [3, 13]


def test_run_asr_pipeline_creates_artifacts() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        sr = 16000
        t = np.linspace(0.0, 1.0, sr, endpoint=False)
        tone = (0.15 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        input_wav = tmp_path / "input.wav"
        wavfile.write(input_wav, sr, (tone * 32767).astype(np.int16))

        fake_model_dir = tmp_path / "mock_model"
        fake_model_dir.mkdir()
        output_dir = tmp_path / "artifacts"

        import resp_lanu.pipeline as pipeline_module

        original_recognize = pipeline_module.recognize_wav

        def fake_recognize_wav(
            *, model_path: Path, wav_path: Path, grammar_path=None, phrase_hints_path=None
        ) -> dict:
            return {
                "model_path": str(model_path),
                "wav_path": str(wav_path),
                "grammar_path": str(grammar_path) if grammar_path else None,
                "phrase_hints_path": str(phrase_hints_path) if phrase_hints_path else None,
                "num_chunks": 1,
                "raw_transcript": "你好 树莓派",
                "transcript": "你好 树莓派",
                "corrections": [],
                "words": [{"word": "你好", "conf": 0.99}],
            }

        pipeline_module.recognize_wav = fake_recognize_wav
        try:
            result = run_asr_pipeline(
                input_wav=input_wav,
                output_dir=output_dir,
                model_dir=fake_model_dir,
            )
        finally:
            pipeline_module.recognize_wav = original_recognize

        assert result["asr_result"]["transcript"] == "你好 树莓派"
        assert (output_dir / "preprocess_summary.json").exists()
        assert (output_dir / "asr_result.json").exists()
        assert (output_dir / "features" / "feature_summary.json").exists()
