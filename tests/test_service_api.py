from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import resp_lanu.runtime as runtime_module
from resp_lanu.legacy import export_legacy_artifacts
from resp_lanu.runtime import AssistantRuntime
from resp_lanu.storage import Database, utc_now
from resp_lanu.web import create_app

from .conftest import (
    FailingDialogueEngine,
    FakeDialogueEngine,
    FakeRecognizer,
    FakeSynthesizer,
    build_settings,
    create_wav_bytes,
    wait_for_job,
)


def test_settings_profile_defaults(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, profile="pi-offline")
    assert settings.bind_host == "0.0.0.0"
    assert settings.dialogue_provider == "rule-based"
    assert settings.database_path == tmp_path / "data" / "resp_lanu.db"


def test_settings_preserve_explicit_bind_host(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, profile="pi-offline", bind_host="192.168.1.99")
    assert settings.bind_host == "192.168.1.99"


def test_settings_profile_defaults_do_not_override_explicit_providers(tmp_path: Path) -> None:
    offline_settings = build_settings(
        tmp_path,
        profile="pi-offline",
        dialogue_provider="openai-compatible",
        openai_base_url="http://127.0.0.1:11434/v1",
    )
    assert offline_settings.dialogue_provider == "openai-compatible"

    connected_settings = build_settings(
        tmp_path,
        profile="pi-connected",
        openai_base_url="http://127.0.0.1:11434/v1",
    )
    assert connected_settings.dialogue_provider == "openai-compatible"

    tts_disabled = build_settings(tmp_path, tts_provider="none")
    assert tts_disabled.enable_tts is False

    tts_explicit = build_settings(tmp_path, tts_provider="none", enable_tts=True)
    assert tts_explicit.enable_tts is True


def test_service_security_blocks_default_secrets_on_lan(tmp_path: Path) -> None:
    unsafe_settings = build_settings(tmp_path, profile="pi-offline")
    with pytest.raises(RuntimeError, match="default"):
        create_app(settings=unsafe_settings)

    safe_settings = build_settings(
        tmp_path,
        profile="pi-offline",
        admin_token="replace-me-for-lan",
        session_secret="replace-me-too-for-lan",
    )
    app = create_app(settings=safe_settings)
    assert app.state.settings.bind_host == "0.0.0.0"


def test_runtime_processes_job_and_exports_legacy_artifacts(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, profile="dev-mac")
    runtime = AssistantRuntime(
        settings,
        recognizer=FakeRecognizer(),
        primary_dialogue_engine=FakeDialogueEngine(),
        fallback_dialogue_engine=FakeDialogueEngine(),
        synthesizer=FakeSynthesizer(),
    )
    runtime.start()
    try:
        upload = runtime.create_uploaded_audio(
            filename="input.wav",
            media_type="audio/wav",
            content=create_wav_bytes(),
        )
        snapshot = runtime.submit_assistant_turn(
            {
                "session_id": None,
                "title": "测试会话",
                "text_input": "",
                "upload_artifact_id": upload["id"],
                "use_tts": True,
            }
        )
        finished = wait_for_job(runtime, snapshot["job"]["id"])
        assert finished["job"]["status"] == "completed"
        assert finished["turn"]["assistant_text"] == "已收到：你好 树莓派 企业级 重构"

        export_dir = export_legacy_artifacts(
            runtime.storage,
            tmp_path / "legacy-export",
            turn_id=finished["turn"]["id"],
            workspace_dir=settings.workspace_dir,
        )
        assert (export_dir / "preprocess_summary.json").exists()
        assert (export_dir / "asr_result.json").exists()
        assert not (export_dir / "features" / "feature_summary.json").exists()
        assert not any(item["kind"] == "feature_summary" for item in finished["artifacts"])
    finally:
        runtime.stop()


def test_runtime_generates_feature_artifacts_when_enabled(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, profile="dev-mac", generate_feature_artifacts=True)
    runtime = AssistantRuntime(
        settings,
        recognizer=FakeRecognizer(),
        primary_dialogue_engine=FakeDialogueEngine(),
        fallback_dialogue_engine=FakeDialogueEngine(),
        synthesizer=FakeSynthesizer(),
    )
    runtime.start()
    try:
        upload = runtime.create_uploaded_audio(
            filename="input.wav",
            media_type="audio/wav",
            content=create_wav_bytes(),
        )
        snapshot = runtime.submit_assistant_turn(
            {
                "title": "特征文件",
                "upload_artifact_id": upload["id"],
                "use_tts": False,
            }
        )
        finished = wait_for_job(runtime, snapshot["job"]["id"])
        assert finished["job"]["status"] == "completed"
        assert any(item["kind"] == "feature_summary" for item in finished["artifacts"])
    finally:
        runtime.stop()


def test_runtime_converts_browser_recording_uploads_to_wav(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, profile="dev-mac")
    runtime = AssistantRuntime(
        settings,
        recognizer=FakeRecognizer(),
        primary_dialogue_engine=FakeDialogueEngine(),
        fallback_dialogue_engine=FakeDialogueEngine(),
        synthesizer=FakeSynthesizer(),
    )
    original_run = runtime_module.subprocess.run

    def fake_ffmpeg(command, check, capture_output):
        output_path = Path(command[-1])
        output_path.write_bytes(create_wav_bytes())

        class Result:
            returncode = 0
            stdout = b""
            stderr = b""

        return Result()

    runtime_module.subprocess.run = fake_ffmpeg
    runtime.start()
    try:
        upload = runtime.create_uploaded_audio(
            filename="browser-recording.webm",
            media_type="audio/webm",
            content=b"fake-webm",
        )
        snapshot = runtime.submit_assistant_turn(
            {
                "session_id": None,
                "title": "浏览器录音",
                "text_input": "",
                "upload_artifact_id": upload["id"],
                "use_tts": False,
            }
        )
        finished = wait_for_job(runtime, snapshot["job"]["id"])
        assert finished["job"]["status"] == "completed"
        assert any(item["kind"] == "converted_audio" for item in finished["artifacts"])
    finally:
        runtime.stop()
        runtime_module.subprocess.run = original_run


def test_runtime_falls_back_when_primary_dialogue_provider_fails(tmp_path: Path) -> None:
    settings = build_settings(
        tmp_path, profile="pi-connected", dialogue_provider="openai-compatible"
    )
    runtime = AssistantRuntime(
        settings,
        recognizer=FakeRecognizer(),
        primary_dialogue_engine=FailingDialogueEngine(),
        fallback_dialogue_engine=FakeDialogueEngine(),
        synthesizer=FakeSynthesizer(),
    )
    runtime.start()
    try:
        snapshot = runtime.submit_assistant_turn(
            {
                "text_input": "请告诉我系统状态",
                "upload_artifact_id": None,
                "use_tts": False,
                "title": "fallback",
            }
        )
        finished = wait_for_job(runtime, snapshot["job"]["id"])
        result_payload = json.loads(finished["job"]["result_payload"])
        assert finished["job"]["status"] == "completed"
        assert (
            result_payload["metadata"]["dialogue"]["fallback_reason"] == "forced fallback for test"
        )
    finally:
        runtime.stop()


def test_api_endpoints_cover_auth_upload_job_and_stream(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, profile="dev-mac")
    runtime = AssistantRuntime(
        settings,
        recognizer=FakeRecognizer(),
        primary_dialogue_engine=FakeDialogueEngine(),
        fallback_dialogue_engine=FakeDialogueEngine(),
        synthesizer=FakeSynthesizer(),
    )
    app = create_app(settings=settings, runtime=runtime)
    headers = {"x-admin-token": settings.admin_token}

    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/api/v1/sessions").status_code == 401

        upload_response = client.post(
            "/api/v1/audio/upload",
            headers=headers,
            files={"file": ("input.wav", create_wav_bytes(), "audio/wav")},
        )
        assert upload_response.status_code == 200
        upload_id = upload_response.json()["artifact"]["id"]

        job_response = client.post(
            "/api/v1/assistant/respond",
            headers=headers,
            json={
                "title": "浏览器测试",
                "upload_artifact_id": upload_id,
                "use_tts": True,
            },
        )
        assert job_response.status_code == 200
        job_id = job_response.json()["job"]["id"]

        finished = wait_for_job(runtime, job_id)
        assert finished["job"]["status"] == "completed"

        event_stream = runtime.events.stream(job_id, finished)
        first_chunk = next(event_stream)
        assert first_chunk.startswith("data: ")

        sessions_response = client.get("/api/v1/sessions", headers=headers)
        assert sessions_response.status_code == 200
        assert sessions_response.json()[0]["title"] == "浏览器测试"

        artifacts_response = client.get("/api/v1/artifacts", headers=headers)
        assert artifacts_response.status_code == 200
        assert any(item["kind"] == "assistant_audio" for item in artifacts_response.json())

        settings_response = client.get("/api/v1/settings", headers=headers)
        assert settings_response.status_code == 200
        assert settings_response.json()["settings"]["profile"] == "dev-mac"


def test_api_rejects_empty_oversize_and_unsupported_uploads(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, profile="dev-mac", max_upload_bytes=32)
    runtime = AssistantRuntime(
        settings,
        recognizer=FakeRecognizer(),
        primary_dialogue_engine=FakeDialogueEngine(),
        fallback_dialogue_engine=FakeDialogueEngine(),
        synthesizer=FakeSynthesizer(),
    )
    app = create_app(settings=settings, runtime=runtime)
    headers = {"x-admin-token": settings.admin_token}

    with TestClient(app) as client:
        empty_response = client.post(
            "/api/v1/audio/upload",
            headers=headers,
            files={"file": ("empty.wav", b"", "audio/wav")},
        )
        assert empty_response.status_code == 400

        unsupported_extension = client.post(
            "/api/v1/audio/upload",
            headers=headers,
            files={"file": ("notes.txt", b"hello", "audio/wav")},
        )
        assert unsupported_extension.status_code == 415

        unsupported_mime = client.post(
            "/api/v1/audio/upload",
            headers=headers,
            files={"file": ("input.wav", create_wav_bytes(), "text/plain")},
        )
        assert unsupported_mime.status_code == 415

        oversized_response = client.post(
            "/api/v1/audio/upload",
            headers=headers,
            files={"file": ("input.wav", create_wav_bytes(), "audio/wav")},
        )
        assert oversized_response.status_code == 413

        webm_response = client.post(
            "/api/v1/audio/upload",
            headers=headers,
            files={"file": ("browser-recording.webm", b"fake-webm", "audio/webm")},
        )
        assert webm_response.status_code == 200


def test_database_initializes_schema_migration_version(tmp_path: Path) -> None:
    database = Database(tmp_path / "resp_lanu.db")
    try:
        database.initialize()
        assert database.schema_version() == 1
    finally:
        database.close()


def test_database_marks_existing_v1_schema_without_destroying_data(tmp_path: Path) -> None:
    database_path = tmp_path / "resp_lanu.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("existing-session", "保留会话", utc_now(), utc_now()),
    )
    connection.commit()
    connection.close()

    database = Database(database_path)
    try:
        database.initialize()
        assert database.schema_version() == 1
        assert database.get_session("existing-session")["title"] == "保留会话"
    finally:
        database.close()


def test_runtime_recovers_queued_job_on_start(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, profile="dev-mac")
    seed_runtime = AssistantRuntime(
        settings,
        recognizer=FakeRecognizer(),
        primary_dialogue_engine=FakeDialogueEngine(),
        fallback_dialogue_engine=FakeDialogueEngine(),
        synthesizer=FakeSynthesizer(),
    )
    upload = seed_runtime.create_uploaded_audio(
        filename="input.wav",
        media_type="audio/wav",
        content=create_wav_bytes(),
    )
    job = seed_runtime.storage.create_assistant_job(
        {
            "title": "恢复 queued",
            "upload_artifact_id": upload["id"],
            "use_tts": False,
        }
    )
    seed_runtime.storage.close()

    recovered_runtime = AssistantRuntime(
        settings,
        recognizer=FakeRecognizer(),
        primary_dialogue_engine=FakeDialogueEngine(),
        fallback_dialogue_engine=FakeDialogueEngine(),
        synthesizer=FakeSynthesizer(),
    )
    recovered_runtime.start()
    try:
        finished = wait_for_job(recovered_runtime, job["id"])
        assert finished["job"]["status"] == "completed"
    finally:
        recovered_runtime.stop()


def test_runtime_recovers_running_job_and_cleans_partial_outputs(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, profile="dev-mac")
    seed_runtime = AssistantRuntime(
        settings,
        recognizer=FakeRecognizer(),
        primary_dialogue_engine=FakeDialogueEngine(),
        fallback_dialogue_engine=FakeDialogueEngine(),
        synthesizer=FakeSynthesizer(),
    )
    upload = seed_runtime.create_uploaded_audio(
        filename="input.wav",
        media_type="audio/wav",
        content=create_wav_bytes(),
    )
    job = seed_runtime.storage.create_assistant_job(
        {
            "title": "恢复 running",
            "upload_artifact_id": upload["id"],
            "use_tts": False,
        }
    )
    turn_id = job["turn_id"]
    session_id = job["session_id"]
    turn_dir = settings.sessions_dir / session_id / turn_id
    turn_dir.mkdir(parents=True, exist_ok=True)
    stale_file = turn_dir / "stale.json"
    stale_file.write_text("stale", encoding="utf-8")
    seed_runtime.storage.add_message(session_id, turn_id, "user", "stale user message")
    seed_runtime.storage.add_artifact(
        session_id=session_id,
        turn_id=turn_id,
        job_id=job["id"],
        kind="assistant_response",
        label="stale.json",
        relative_path=str(stale_file.relative_to(settings.workspace_dir)),
        media_type="application/json",
        metadata={"stale": True},
    )
    seed_runtime.storage.update_turn(
        turn_id,
        user_text="stale user message",
        transcript="stale transcript",
        assistant_text="stale assistant",
        status="running",
    )
    seed_runtime.storage.update_job(
        job["id"],
        status="running",
        phase="dialogue",
        started_at=utc_now(),
    )
    seed_runtime.storage.close()

    recovered_runtime = AssistantRuntime(
        settings,
        recognizer=FakeRecognizer(),
        primary_dialogue_engine=FakeDialogueEngine(),
        fallback_dialogue_engine=FakeDialogueEngine(),
        synthesizer=FakeSynthesizer(),
    )
    recovered_runtime.start()
    try:
        finished = wait_for_job(recovered_runtime, job["id"])
        messages = recovered_runtime.storage.list_messages(session_id)
        assert finished["job"]["status"] == "completed"
        assert not stale_file.exists()
        assert all(message["content"] != "stale user message" for message in messages)
        assert [message["role"] for message in messages] == ["user", "assistant"]
    finally:
        recovered_runtime.stop()


def test_setup_script_checks_voice_runtime_dependencies() -> None:
    script = Path("scripts/setup_pi.sh").read_text(encoding="utf-8")
    assert "arecord" in script
    assert "espeak-ng" in script


def test_assistant_console_includes_browser_recording_ui() -> None:
    template = Path("src/resp_lanu/templates/assistant.html").read_text(encoding="utf-8")
    app_js = Path("src/resp_lanu/static/app.js").read_text(encoding="utf-8")
    assert 'id="record-start"' in template
    assert 'id="record-stop"' in template
    assert "MediaRecorder" in app_js
    assert "getUserMedia" in app_js


def test_web_console_templates_use_unified_dark_shell() -> None:
    base_template = Path("src/resp_lanu/templates/base.html").read_text(encoding="utf-8")
    assistant_template = Path("src/resp_lanu/templates/assistant.html").read_text(
        encoding="utf-8"
    )
    history_template = Path("src/resp_lanu/templates/history.html").read_text(encoding="utf-8")
    artifacts_template = Path("src/resp_lanu/templates/artifacts.html").read_text(
        encoding="utf-8"
    )
    settings_template = Path("src/resp_lanu/templates/settings.html").read_text(
        encoding="utf-8"
    )
    health_template = Path("src/resp_lanu/templates/health.html").read_text(encoding="utf-8")
    style_css = Path("src/resp_lanu/static/style.css").read_text(encoding="utf-8")
    app_js = Path("src/resp_lanu/static/app.js").read_text(encoding="utf-8")

    assert "console-shell" in base_template
    assert "aria-current=\"page\"" in base_template
    assert "工作台" in base_template
    assert "workspace-grid" in assistant_template
    assert 'id="job-status" class="status-panel"' in assistant_template
    assert 'id="conversation-output" class="conversation-output"' in assistant_template
    assert 'id="history-output" class="card-list"' in history_template
    assert 'id="artifacts-output" class="table-list"' in artifacts_template
    assert 'id="settings-output" class="settings-grid"' in settings_template
    assert 'id="health-output" class="health-grid"' in health_template
    assert "color-scheme: dark" in style_css
    assert "renderHistory" in app_js
    assert "renderArtifacts" in app_js
    assert "renderSettings" in app_js
    assert "renderHealth" in app_js
