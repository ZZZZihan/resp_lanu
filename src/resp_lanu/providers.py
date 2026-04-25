from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .asr import recognize_wav
from .schemas import ProviderStatus
from .settings import Settings


class ProviderUnavailableError(RuntimeError):
    """Raised when a provider is configured but not available."""


@dataclass
class RecognizerResult:
    transcript: str
    raw_transcript: str
    corrections: list[dict]
    words: list[dict]
    payload: dict


@dataclass
class DialogueResult:
    assistant_text: str
    provider_name: str
    metadata: dict


@dataclass
class SynthesisResult:
    provider_name: str
    output_path: Path
    media_type: str


class SpeechRecognizer:
    name = "recognizer"

    def status(self) -> ProviderStatus:
        raise NotImplementedError

    def recognize(self, wav_path: Path) -> RecognizerResult:
        raise NotImplementedError


class DialogueEngine:
    name = "dialogue"

    def status(self) -> ProviderStatus:
        raise NotImplementedError

    def generate_reply(self, history: list[dict], user_text: str) -> DialogueResult:
        raise NotImplementedError


class SpeechSynthesizer:
    name = "tts"

    def status(self) -> ProviderStatus:
        raise NotImplementedError

    def synthesize(self, text: str, output_path: Path) -> SynthesisResult:
        raise NotImplementedError


class VoskRecognizer(SpeechRecognizer):
    name = "vosk"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def status(self) -> ProviderStatus:
        model_exists = self.settings.model_dir.exists()
        try:
            __import__("vosk")
            import_ok = True
        except ImportError:
            import_ok = False
        available = model_exists and import_ok
        detail = "ready" if available else "Missing model directory or vosk package."
        return ProviderStatus(
            name=self.name,
            configured=True,
            available=available,
            detail=detail,
        )

    def recognize(self, wav_path: Path) -> RecognizerResult:
        result = recognize_wav(
            model_path=self.settings.model_dir,
            wav_path=wav_path,
            grammar_path=self.settings.grammar_file,
            phrase_hints_path=self.settings.phrase_hints_file,
        )
        return RecognizerResult(
            transcript=result["transcript"],
            raw_transcript=result["raw_transcript"],
            corrections=result["corrections"],
            words=result["words"],
            payload=result,
        )


class RuleBasedDialogueEngine(DialogueEngine):
    name = "rule-based"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            configured=True,
            available=True,
            detail="Built-in offline response templates are available.",
        )

    def generate_reply(self, history: list[dict], user_text: str) -> DialogueResult:
        text = user_text.strip()
        normalized = text.replace(" ", "")
        turn_count = sum(1 for item in history if item.get("role") == "user")

        if any(keyword in normalized for keyword in ("你好", "您好", "hello")):
            reply = (
                "你好，我是运行在树莓派上的离线优先语音助手。"
                "你可以继续说出问题，我会尽量在本地完成响应。"
            )
        elif "状态" in normalized or "health" in normalized.lower():
            reply = (
                "当前系统运行在离线优先模式，本地语音识别链路可用，"
                "对话能力会根据配置自动选择本地规则回复或兼容 OpenAI 的接口。"
            )
        elif "树莓派" in normalized:
            reply = (
                "我识别到了和树莓派相关的内容。当前方案面向 Raspberry Pi 5，"
                "重点是本地服务、浏览器控制台和可回放的任务历史。"
            )
        else:
            reply = (
                f"我听到了：{text}。"
                "当前处于离线优先模式，默认会先完成本地识别和规则回复；"
                "如果你配置了兼容 OpenAI 的对话接口，系统会自动升级到更强的对话能力。"
            )

        if turn_count > 1:
            reply += " 我会继续保留当前会话历史，方便你在浏览器里回看每一轮输入和输出。"

        return DialogueResult(
            assistant_text=reply,
            provider_name=self.name,
            metadata={"history_messages": len(history)},
        )


class OpenAICompatibleDialogueEngine(DialogueEngine):
    name = "openai-compatible"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def status(self) -> ProviderStatus:
        configured = bool(self.settings.openai_base_url)
        detail = "ready" if configured else "RESP_LANU_OPENAI_BASE_URL is not set."
        return ProviderStatus(
            name=self.name,
            configured=configured,
            available=configured,
            detail=detail,
        )

    def generate_reply(self, history: list[dict], user_text: str) -> DialogueResult:
        if not self.settings.openai_base_url:
            raise ProviderUnavailableError("OpenAI-compatible dialogue provider is not configured.")

        messages = [
            {"role": "system", "content": "You are a concise Raspberry Pi speech assistant."}
        ]
        for item in history[-self.settings.max_history_messages :]:
            role = item.get("role", "user")
            content = item.get("content", "")
            if content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_text})

        payload = {
            "model": self.settings.openai_model,
            "messages": messages,
            "temperature": 0.4,
        }
        request = urllib.request.Request(
            self._chat_url(),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **(
                    {"Authorization": f"Bearer {self.settings.openai_api_key}"}
                    if self.settings.openai_api_key
                    else {}
                ),
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderUnavailableError(f"OpenAI-compatible request failed: {exc}") from exc

        choices = body.get("choices") or []
        if not choices:
            raise ProviderUnavailableError("OpenAI-compatible provider returned no choices.")
        message = choices[0].get("message") or {}
        content = str(message.get("content", "")).strip()
        if not content:
            raise ProviderUnavailableError("OpenAI-compatible provider returned an empty response.")
        return DialogueResult(
            assistant_text=content,
            provider_name=self.name,
            metadata={"raw_response": body},
        )

    def _chat_url(self) -> str:
        base_url = self.settings.openai_base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"


class EspeakSynthesizer(SpeechSynthesizer):
    name = "espeak"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def status(self) -> ProviderStatus:
        binary = shutil.which(self.settings.espeak_binary) or shutil.which("espeak")
        return ProviderStatus(
            name=self.name,
            configured=self.settings.enable_tts and self.settings.tts_provider == self.name,
            available=binary is not None,
            detail="ready" if binary else "espeak-ng or espeak is not installed.",
        )

    def synthesize(self, text: str, output_path: Path) -> SynthesisResult:
        binary = shutil.which(self.settings.espeak_binary) or shutil.which("espeak")
        if not binary:
            raise ProviderUnavailableError("espeak-ng/espeak is not installed.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([binary, "-w", str(output_path), text], check=True, capture_output=True)
        return SynthesisResult(
            provider_name=self.name,
            output_path=output_path,
            media_type="audio/wav",
        )


class PiperSynthesizer(SpeechSynthesizer):
    name = "piper"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def status(self) -> ProviderStatus:
        binary = shutil.which(self.settings.piper_binary)
        model_ok = bool(self.settings.piper_model_path and self.settings.piper_model_path.exists())
        available = binary is not None and model_ok
        detail = "ready" if available else "Missing Piper binary or model path."
        return ProviderStatus(
            name=self.name,
            configured=self.settings.enable_tts and self.settings.tts_provider == self.name,
            available=available,
            detail=detail,
        )

    def synthesize(self, text: str, output_path: Path) -> SynthesisResult:
        binary = shutil.which(self.settings.piper_binary)
        if not binary or not self.settings.piper_model_path:
            raise ProviderUnavailableError("Piper binary or model path is not configured.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                binary,
                "--model",
                str(self.settings.piper_model_path),
                "--output_file",
                str(output_path),
            ],
            input=text,
            text=True,
            capture_output=True,
            check=True,
        )
        return SynthesisResult(
            provider_name=self.name,
            output_path=output_path,
            media_type="audio/wav",
        )


class NoopSynthesizer(SpeechSynthesizer):
    name = "none"

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            configured=True,
            available=True,
            detail="Text-only responses are enabled; audio synthesis is skipped.",
        )

    def synthesize(self, text: str, output_path: Path) -> SynthesisResult:
        raise ProviderUnavailableError("TTS is disabled for this profile.")


def build_provider_bundle(settings: Settings) -> dict[str, object]:
    recognizer = VoskRecognizer(settings)
    fallback_dialogue = RuleBasedDialogueEngine(settings)
    if settings.dialogue_provider == "openai-compatible":
        dialogue = OpenAICompatibleDialogueEngine(settings)
    else:
        dialogue = fallback_dialogue

    if not settings.enable_tts or settings.tts_provider == "none":
        synthesizer: SpeechSynthesizer = NoopSynthesizer()
    elif settings.tts_provider == "piper":
        synthesizer = PiperSynthesizer(settings)
    else:
        synthesizer = EspeakSynthesizer(settings)

    return {
        "recognizer": recognizer,
        "dialogue": dialogue,
        "fallback_dialogue": fallback_dialogue,
        "synthesizer": synthesizer,
    }
