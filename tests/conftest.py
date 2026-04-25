from __future__ import annotations

import time
import wave
from pathlib import Path

import numpy as np

from resp_lanu.providers import (
    DialogueEngine,
    DialogueResult,
    ProviderUnavailableError,
    RecognizerResult,
    SpeechRecognizer,
    SpeechSynthesizer,
    SynthesisResult,
)
from resp_lanu.schemas import ProviderStatus
from resp_lanu.settings import Settings


def create_wav_bytes(duration_s: float = 0.5, sample_rate: int = 16000) -> bytes:
    t = np.linspace(0.0, duration_s, int(sample_rate * duration_s), endpoint=False)
    tone = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    scaled = (tone * 32767).astype(np.int16)
    output = Path("/tmp/resp_lanu_test.wav")
    with wave.open(str(output), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(scaled.tobytes())
    data = output.read_bytes()
    output.unlink(missing_ok=True)
    return data


def wait_for_job(runtime, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snapshot = runtime.get_job_snapshot(job_id)
        if snapshot["job"]["status"] in {"completed", "failed"}:
            return snapshot
        time.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for job {job_id}")


def build_settings(tmp_path: Path, **overrides) -> Settings:
    default_model_dir = tmp_path / "models" / "vosk-model-small-cn-0.22"
    default_model_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        workspace_dir=tmp_path,
        data_dir=tmp_path / "data",
        legacy_artifacts_dir=tmp_path / "artifacts",
        model_dir=default_model_dir,
        phrase_hints_file=None,
        grammar_file=None,
        **overrides,
    )
    settings.ensure_directories()
    return settings


class FakeRecognizer(SpeechRecognizer):
    name = "fake-recognizer"

    def status(self) -> ProviderStatus:
        return ProviderStatus(name=self.name, configured=True, available=True, detail="test double")

    def recognize(self, wav_path: Path) -> RecognizerResult:
        payload = {
            "wav_path": str(wav_path),
            "transcript": "你好 树莓派 企业级 重构",
            "raw_transcript": "你好 树莓派 企业级 重构",
            "corrections": [],
            "words": [{"word": "你好", "conf": 0.99}],
        }
        return RecognizerResult(
            transcript=payload["transcript"],
            raw_transcript=payload["raw_transcript"],
            corrections=payload["corrections"],
            words=payload["words"],
            payload=payload,
        )


class FakeDialogueEngine(DialogueEngine):
    name = "fake-dialogue"

    def status(self) -> ProviderStatus:
        return ProviderStatus(name=self.name, configured=True, available=True, detail="test double")

    def generate_reply(self, history: list[dict], user_text: str) -> DialogueResult:
        return DialogueResult(
            assistant_text=f"已收到：{user_text}",
            provider_name=self.name,
            metadata={"history_size": len(history)},
        )


class FailingDialogueEngine(DialogueEngine):
    name = "failing-dialogue"

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name, configured=True, available=False, detail="forced failure"
        )

    def generate_reply(self, history: list[dict], user_text: str) -> DialogueResult:
        raise ProviderUnavailableError("forced fallback for test")


class FakeSynthesizer(SpeechSynthesizer):
    name = "fake-tts"

    def status(self) -> ProviderStatus:
        return ProviderStatus(name=self.name, configured=True, available=True, detail="test double")

    def synthesize(self, text: str, output_path: Path) -> SynthesisResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(create_wav_bytes(duration_s=0.2))
        return SynthesisResult(
            provider_name=self.name, output_path=output_path, media_type="audio/wav"
        )
