from __future__ import annotations

from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RESP_LANU_",
        extra="ignore",
    )

    DEFAULT_ADMIN_TOKEN: ClassVar[str] = "resp-lanu-admin"
    DEFAULT_SESSION_SECRET: ClassVar[str] = "resp-lanu-session-secret"
    LOOPBACK_HOSTS: ClassVar[frozenset[str]] = frozenset({"localhost"})

    app_name: str = "resp-lanu"
    profile: Literal["dev-mac", "pi-offline", "pi-connected"] = "dev-mac"
    workspace_dir: Path = Field(default_factory=lambda: Path.cwd())
    data_dir: Path = Path("data")
    legacy_artifacts_dir: Path = Path("artifacts")
    bind_host: str = "127.0.0.1"
    bind_port: int = 8000
    log_level: str = "INFO"
    admin_token: str = DEFAULT_ADMIN_TOKEN
    session_secret: str = DEFAULT_SESSION_SECRET
    max_history_messages: int = 12
    max_upload_bytes: int = 26_214_400
    generate_feature_artifacts: bool = False

    recognizer_provider: Literal["vosk"] = "vosk"
    dialogue_provider: Literal["rule-based", "openai-compatible"] = "rule-based"
    tts_provider: Literal["espeak", "piper", "none"] = "espeak"
    enable_tts: bool = True

    model_dir: Path = Path("models/vosk-model-small-cn-0.22")
    grammar_file: Path | None = None
    phrase_hints_file: Path | None = Path("sample_audio/demo_cn_phrase_hints.json")
    recording_device: str | None = None

    openai_base_url: str | None = None
    openai_api_key: str | None = None
    openai_model: str = "assistant-model"

    espeak_binary: str = "espeak-ng"
    piper_binary: str = "piper"
    piper_model_path: Path | None = None

    def model_post_init(self, __context: object) -> None:
        explicitly_set_fields = set(self.model_fields_set)
        self.workspace_dir = self.workspace_dir.resolve()
        self.data_dir = self._resolve_under_workspace(self.data_dir)
        self.legacy_artifacts_dir = self._resolve_under_workspace(self.legacy_artifacts_dir)
        self.model_dir = self._resolve_under_workspace(self.model_dir)
        if self.grammar_file is not None:
            self.grammar_file = self._resolve_under_workspace(self.grammar_file)
        if self.phrase_hints_file is not None:
            self.phrase_hints_file = self._resolve_under_workspace(self.phrase_hints_file)
        if self.piper_model_path is not None:
            self.piper_model_path = self._resolve_under_workspace(self.piper_model_path)
        self._apply_profile_defaults(explicitly_set_fields)

    def _resolve_under_workspace(self, path: Path) -> Path:
        return path if path.is_absolute() else (self.workspace_dir / path).resolve()

    def _apply_profile_defaults(self, explicitly_set_fields: set[str]) -> None:
        if "bind_host" not in explicitly_set_fields:
            if self.profile == "dev-mac":
                self.bind_host = "127.0.0.1"
            else:
                self.bind_host = "0.0.0.0"

        if "dialogue_provider" not in explicitly_set_fields:
            if self.profile == "pi-connected" and self.openai_base_url:
                self.dialogue_provider = "openai-compatible"
            else:
                self.dialogue_provider = "rule-based"

        if self.tts_provider == "none" and "enable_tts" not in explicitly_set_fields:
            self.enable_tts = False

    def is_loopback_bind(self) -> bool:
        normalized_host = self.bind_host.strip().lower()
        if normalized_host in self.LOOPBACK_HOSTS:
            return True
        try:
            return ip_address(normalized_host).is_loopback
        except ValueError:
            return False

    def admin_token_is_default(self) -> bool:
        return self.admin_token == self.DEFAULT_ADMIN_TOKEN

    def session_secret_is_default(self) -> bool:
        return self.session_secret == self.DEFAULT_SESSION_SECRET

    def service_security_issues(self) -> list[str]:
        if self.is_loopback_bind():
            return []
        issues = []
        if self.admin_token_is_default():
            issues.append("admin token is still the default value")
        if self.session_secret_is_default():
            issues.append("session secret is still the default value")
        return issues

    def validate_service_security(self) -> None:
        issues = self.service_security_issues()
        if not issues:
            return
        issue_text = "; ".join(issues)
        raise RuntimeError(
            "Refusing to start resp-lanu on a non-loopback bind host because "
            f"{issue_text}. Set RESP_LANU_ADMIN_TOKEN and RESP_LANU_SESSION_SECRET "
            "before LAN deployment."
        )

    @property
    def database_path(self) -> Path:
        return self.data_dir / "resp_lanu.db"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.legacy_artifacts_dir.mkdir(parents=True, exist_ok=True)

    def masked_settings(self) -> dict:
        api_key = None if not self.openai_api_key else f"{self.openai_api_key[:4]}***"
        token = f"{self.admin_token[:4]}***" if self.admin_token else "(unset)"
        secret = f"{self.session_secret[:4]}***" if self.session_secret else "(unset)"
        return {
            "app_name": self.app_name,
            "profile": self.profile,
            "workspace_dir": str(self.workspace_dir),
            "data_dir": str(self.data_dir),
            "database_path": str(self.database_path),
            "legacy_artifacts_dir": str(self.legacy_artifacts_dir),
            "bind_host": self.bind_host,
            "bind_port": self.bind_port,
            "log_level": self.log_level,
            "admin_token": token,
            "session_secret": secret,
            "max_upload_bytes": self.max_upload_bytes,
            "generate_feature_artifacts": self.generate_feature_artifacts,
            "recognizer_provider": self.recognizer_provider,
            "dialogue_provider": self.dialogue_provider,
            "tts_provider": self.tts_provider,
            "enable_tts": self.enable_tts,
            "model_dir": str(self.model_dir),
            "grammar_file": str(self.grammar_file) if self.grammar_file else None,
            "phrase_hints_file": str(self.phrase_hints_file) if self.phrase_hints_file else None,
            "recording_device": self.recording_device,
            "openai_base_url": self.openai_base_url,
            "openai_api_key": api_key,
            "openai_model": self.openai_model,
            "espeak_binary": self.espeak_binary,
            "piper_binary": self.piper_binary,
            "piper_model_path": str(self.piper_model_path) if self.piper_model_path else None,
        }


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
