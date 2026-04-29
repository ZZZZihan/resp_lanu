from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobPhase(StrEnum):
    QUEUED = "queued"
    INGEST = "ingest"
    PREPROCESS = "preprocess"
    ASR = "asr"
    DIALOGUE = "dialogue"
    TTS = "tts"
    PERSIST = "persist"
    COMPLETED = "completed"
    FAILED = "failed"


class ProviderStatus(BaseModel):
    name: str
    configured: bool
    available: bool
    detail: str


class ArtifactResponse(BaseModel):
    id: str
    session_id: str | None = None
    turn_id: str | None = None
    job_id: str | None = None
    kind: str
    label: str
    relative_path: str
    media_type: str | None = None
    metadata_json: str | None = None
    created_at: str


class MessageResponse(BaseModel):
    id: str
    session_id: str
    turn_id: str | None = None
    role: str
    content: str
    created_at: str


class TurnResponse(BaseModel):
    id: str
    session_id: str
    job_id: str | None = None
    source_upload_artifact_id: str | None = None
    user_text: str | None = None
    transcript: str | None = None
    assistant_text: str | None = None
    status: str
    error: str | None = None
    created_at: str
    updated_at: str
    artifacts: list[ArtifactResponse] = Field(default_factory=list)
    messages: list[MessageResponse] = Field(default_factory=list)


class SessionResponse(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    turn_count: int = 0
    turns: list[TurnResponse] = Field(default_factory=list)


class JobResponse(BaseModel):
    id: str
    session_id: str
    turn_id: str
    status: str
    phase: str
    error: str | None = None
    request_payload: str | None = None
    result_payload: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str


class JobEventResponse(BaseModel):
    job: JobResponse
    session: SessionResponse | None = None
    turn: TurnResponse | None = None
    artifacts: list[ArtifactResponse] = Field(default_factory=list)


class UploadResponse(BaseModel):
    artifact: ArtifactResponse


class PiRecordRequest(BaseModel):
    duration_seconds: int = Field(default=6, ge=1, le=30)


class AssistantRespondRequest(BaseModel):
    session_id: str | None = None
    title: str | None = None
    text_input: str | None = None
    upload_artifact_id: str | None = None
    use_tts: bool = True

    @model_validator(mode="after")
    def validate_input(self) -> AssistantRespondRequest:
        if not (self.text_input and self.text_input.strip()) and not self.upload_artifact_id:
            raise ValueError("Either text_input or upload_artifact_id must be provided.")
        return self


class SettingsResponse(BaseModel):
    settings: dict[str, Any]
    providers: dict[str, ProviderStatus]


class HealthResponse(BaseModel):
    status: str
    ready: bool
    worker_running: bool
    queue_size: int
    profile: str
    providers: dict[str, ProviderStatus]
