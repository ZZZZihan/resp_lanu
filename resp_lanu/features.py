from __future__ import annotations

from pathlib import Path
import json

import numpy as np
from python_speech_features import delta, fbank, mfcc

from .audio import load_audio


def zero_crossing_rate(samples: np.ndarray) -> float:
    if len(samples) < 2:
        return 0.0
    signs = np.signbit(samples)
    return float(np.mean(signs[:-1] != signs[1:]))


def frame_energy(samples: np.ndarray, frame_len: int, frame_step: int) -> np.ndarray:
    if len(samples) < frame_len:
        return np.array([float(np.mean(np.square(samples)) + 1e-10)])
    energies = []
    for start in range(0, len(samples) - frame_len + 1, frame_step):
        frame = samples[start : start + frame_len]
        energies.append(float(np.mean(np.square(frame)) + 1e-10))
    return np.asarray(energies, dtype=np.float32)


def extract_feature_bundle(input_wav: str | Path) -> tuple[dict, dict]:
    sample_rate, samples, _ = load_audio(input_wav)
    if sample_rate != 16000:
        raise ValueError(f"Expected a 16 kHz WAV after preprocessing, got {sample_rate} Hz.")

    samples64 = samples.astype(np.float64)
    mfcc_feat = mfcc(
        samples64,
        samplerate=sample_rate,
        winlen=0.025,
        winstep=0.01,
        numcep=13,
        nfilt=26,
        nfft=512,
        preemph=0.0,
        appendEnergy=True,
    )
    delta_feat = delta(mfcc_feat, 2)
    delta2_feat = delta(delta_feat, 2)
    fbank_feat, frame_energies = fbank(
        samples64,
        samplerate=sample_rate,
        winlen=0.025,
        winstep=0.01,
        nfilt=26,
        nfft=512,
        preemph=0.0,
    )

    frame_len = int(sample_rate * 0.025)
    frame_step = int(sample_rate * 0.01)
    energies = frame_energy(samples, frame_len, frame_step)
    voice_threshold = max(float(np.percentile(energies, 30)), 1e-6)
    voiced_ratio = float(np.mean(energies > voice_threshold))

    summary = {
        "sample_rate": sample_rate,
        "duration_s": round(len(samples) / float(sample_rate), 4),
        "num_samples": int(len(samples)),
        "rms": round(float(np.sqrt(np.mean(np.square(samples)) + 1e-10)), 6),
        "zero_crossing_rate": round(zero_crossing_rate(samples), 6),
        "voiced_frame_ratio": round(voiced_ratio, 6),
        "mfcc_shape": list(mfcc_feat.shape),
        "delta_shape": list(delta_feat.shape),
        "delta2_shape": list(delta2_feat.shape),
        "fbank_shape": list(fbank_feat.shape),
        "mfcc_mean_first5": [round(float(x), 6) for x in np.mean(mfcc_feat, axis=0)[:5]],
        "mfcc_std_first5": [round(float(x), 6) for x in np.std(mfcc_feat, axis=0)[:5]],
        "frame_energy_db_first5": [
            round(float(10.0 * np.log10(x + 1e-10)), 6) for x in frame_energies[:5]
        ],
    }
    bundle = {
        "mfcc": mfcc_feat,
        "delta": delta_feat,
        "delta2": delta2_feat,
        "fbank": fbank_feat,
        "frame_energy": frame_energies,
    }
    return bundle, summary


def save_feature_bundle(output_dir: str | Path, bundle: dict, summary: dict) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    np.save(output_dir / "mfcc.npy", bundle["mfcc"])
    np.save(output_dir / "delta.npy", bundle["delta"])
    np.save(output_dir / "delta2.npy", bundle["delta2"])
    np.save(output_dir / "fbank.npy", bundle["fbank"])
    np.save(output_dir / "frame_energy.npy", bundle["frame_energy"])
    (output_dir / "feature_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

