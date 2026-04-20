from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, filtfilt, resample_poly


@dataclass
class PreprocessSummary:
    input_path: str
    output_path: str
    input_sample_rate: int
    output_sample_rate: int
    input_channels: int
    output_duration_s: float
    trimmed_seconds: float
    peak_before: float
    peak_after: float
    rms_after: float

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


def _to_float32(data: np.ndarray) -> np.ndarray:
    if data.dtype == np.int16:
        return data.astype(np.float32) / 32768.0
    if data.dtype == np.int32:
        return data.astype(np.float32) / 2147483648.0
    if data.dtype == np.uint8:
        return (data.astype(np.float32) - 128.0) / 128.0
    if np.issubdtype(data.dtype, np.floating):
        return data.astype(np.float32)
    raise TypeError(f"Unsupported audio dtype: {data.dtype}")


def load_audio(path: str | Path) -> tuple[int, np.ndarray, int]:
    sample_rate, data = wavfile.read(str(path))
    channels = 1 if data.ndim == 1 else data.shape[1]
    if data.ndim == 2:
        data = data.mean(axis=1)
    return sample_rate, _to_float32(np.asarray(data)), channels


def save_pcm16_wav(path: str | Path, sample_rate: int, samples: np.ndarray) -> None:
    clipped = np.clip(samples, -1.0, 1.0)
    wavfile.write(str(path), sample_rate, (clipped * 32767.0).astype(np.int16))


def trim_silence(
    samples: np.ndarray,
    sample_rate: int,
    frame_ms: float = 20.0,
    threshold_db: float = -35.0,
    pad_frames: int = 2,
) -> np.ndarray:
    frame_len = max(1, int(sample_rate * frame_ms / 1000.0))
    num_frames = int(np.ceil(len(samples) / frame_len))
    padded = np.pad(samples, (0, num_frames * frame_len - len(samples)))
    frames = padded.reshape(num_frames, frame_len)
    rms = np.sqrt(np.mean(np.square(frames), axis=1) + 1e-10)
    threshold = float(np.max(rms)) * (10.0 ** (threshold_db / 20.0))
    active = np.flatnonzero(rms > threshold)
    if active.size == 0:
        return samples
    start_frame = max(0, int(active[0]) - pad_frames)
    end_frame = min(num_frames, int(active[-1]) + pad_frames + 1)
    start = start_frame * frame_len
    end = min(len(samples), end_frame * frame_len)
    return samples[start:end]


def bandpass_filter(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    nyquist = sample_rate / 2.0
    low = 80.0
    high = min(7600.0, nyquist * 0.95)
    if low >= high:
        return samples
    b, a = butter(4, [low / nyquist, high / nyquist], btype="bandpass")
    return filtfilt(b, a, samples).astype(np.float32)


def pre_emphasis(samples: np.ndarray, alpha: float = 0.97) -> np.ndarray:
    if len(samples) == 0:
        return samples
    emphasized = np.empty_like(samples)
    emphasized[0] = samples[0]
    emphasized[1:] = samples[1:] - alpha * samples[:-1]
    return emphasized


def normalize_peak(samples: np.ndarray, target_peak: float = 0.95) -> np.ndarray:
    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    if peak < 1e-8:
        return samples
    return samples * (target_peak / peak)


def preprocess_audio(
    input_path: str | Path,
    output_path: str | Path,
    target_sample_rate: int = 16000,
) -> PreprocessSummary:
    input_sr, samples, channels = load_audio(input_path)
    peak_before = float(np.max(np.abs(samples))) if len(samples) else 0.0
    original_duration = len(samples) / float(input_sr)

    samples = samples - np.mean(samples)
    samples = trim_silence(samples, input_sr)
    if input_sr != target_sample_rate:
        gcd = np.gcd(input_sr, target_sample_rate)
        up = target_sample_rate // gcd
        down = input_sr // gcd
        samples = resample_poly(samples, up, down).astype(np.float32)

    samples = bandpass_filter(samples, target_sample_rate)
    samples = pre_emphasis(samples)
    samples = normalize_peak(samples)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_pcm16_wav(output_path, target_sample_rate, samples)

    duration = len(samples) / float(target_sample_rate)
    trimmed_seconds = max(0.0, original_duration - duration)
    rms_after = float(np.sqrt(np.mean(np.square(samples)) + 1e-10)) if len(samples) else 0.0
    peak_after = float(np.max(np.abs(samples))) if len(samples) else 0.0
    return PreprocessSummary(
        input_path=str(input_path),
        output_path=str(output_path),
        input_sample_rate=input_sr,
        output_sample_rate=target_sample_rate,
        input_channels=channels,
        output_duration_s=round(duration, 4),
        trimmed_seconds=round(trimmed_seconds, 4),
        peak_before=round(peak_before, 6),
        peak_after=round(peak_after, 6),
        rms_after=round(rms_after, 6),
    )

