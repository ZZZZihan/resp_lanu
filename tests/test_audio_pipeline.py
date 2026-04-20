from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np
from scipy.io import wavfile

from resp_lanu.audio import preprocess_audio
from resp_lanu.features import extract_feature_bundle


class AudioPipelineTests(unittest.TestCase):
    def test_preprocess_audio_resamples_to_16k_and_mono(self) -> None:
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

            self.assertEqual(out_sr, 16000)
            self.assertEqual(out_data.ndim, 1)
            self.assertGreater(summary.output_duration_s, 0.2)
            self.assertLessEqual(np.max(np.abs(out_data)), 32767)

    def test_extract_feature_bundle_returns_expected_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            sr = 16000
            t = np.linspace(0.0, 1.0, sr, endpoint=False)
            tone = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
            wav_path = tmp_path / "tone.wav"
            wavfile.write(wav_path, sr, (tone * 32767).astype(np.int16))

            bundle, summary = extract_feature_bundle(wav_path)

            self.assertEqual(bundle["mfcc"].shape[1], 13)
            self.assertEqual(bundle["delta"].shape, bundle["mfcc"].shape)
            self.assertEqual(bundle["delta2"].shape, bundle["mfcc"].shape)
            self.assertIn("zero_crossing_rate", summary)
            self.assertGreater(summary["duration_s"], 0.9)


if __name__ == "__main__":
    unittest.main()
