from __future__ import annotations

import json
import sqlite3
import subprocess
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import resp_lanu.runtime as runtime_module
from resp_lanu.cli import doctor_command
from resp_lanu.legacy import export_legacy_artifacts
from resp_lanu.providers import (
    MimoRouterDialogueEngine,
    OpenAICompatibleDialogueEngine,
    ZeroClawDialogueEngine,
)
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


def test_doctor_command_outputs_json_provider_statuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["resp-lanu-doctor", "--profile", "dev-mac"])

    doctor_command()

    report = json.loads(capsys.readouterr().out)
    assert report["settings"]["profile"] == "dev-mac"
    assert isinstance(report["health"]["providers"]["dialogue"], dict)
    assert "available" in report["health"]["providers"]["dialogue"]


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


def test_runtime_records_pi_audio_with_arecord(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = build_settings(tmp_path, profile="dev-mac")
    runtime = AssistantRuntime(
        settings,
        recognizer=FakeRecognizer(),
        primary_dialogue_engine=FakeDialogueEngine(),
        fallback_dialogue_engine=FakeDialogueEngine(),
        synthesizer=FakeSynthesizer(),
    )
    commands = []

    def fake_arecord(command, **kwargs):
        del kwargs
        commands.append(command)
        if command[:2] == ["arecord", "-l"]:
            stdout = "card 2: Device [USB PnP Sound Device], device 0: USB Audio [USB Audio]\n"
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")
        if command[:2] == ["arecord", "-q"]:
            Path(command[-1]).write_bytes(create_wav_bytes())
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(runtime_module.subprocess, "run", fake_arecord)

    artifact = runtime.record_pi_audio(duration_seconds=1)
    metadata = json.loads(artifact["metadata_json"])

    assert artifact["kind"] == "uploaded_audio"
    assert artifact["label"] == "pi-recording.wav"
    assert metadata["source"] == "pi_arecord"
    assert metadata["recording_device"] == "plughw:2,0"
    assert commands[1][:4] == ["arecord", "-q", "-D", "plughw:2,0"]


def test_runtime_converts_server_audio_for_aplay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = build_settings(
        tmp_path,
        profile="dev-mac",
        audio_player_binary="aplay",
        audio_player_args="-D plughw:CARD=vc4hdmi1,DEV=0",
    )
    runtime = AssistantRuntime(
        settings,
        recognizer=FakeRecognizer(),
        primary_dialogue_engine=FakeDialogueEngine(),
        fallback_dialogue_engine=FakeDialogueEngine(),
        synthesizer=FakeSynthesizer(),
    )
    audio_path = tmp_path / "data" / "sessions" / "assistant_response.mp3"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"fake mp3")
    commands = []

    def fake_which(name: str) -> str | None:
        if name in {"aplay", "ffmpeg"}:
            return f"/usr/bin/{name}"
        return None

    def fake_run(command, **kwargs):
        del kwargs
        commands.append(command)
        if command[0] == "/usr/bin/ffmpeg":
            Path(command[-1]).write_bytes(create_wav_bytes())
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(runtime_module.shutil, "which", fake_which)
    monkeypatch.setattr(runtime_module.subprocess, "run", fake_run)

    metadata = runtime._play_audio_on_server(audio_path)

    assert commands[0][:8] == [
        "/usr/bin/ffmpeg",
        "-y",
        "-i",
        str(audio_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ac",
    ]
    assert commands[1] == [
        "/usr/bin/aplay",
        "-D",
        "plughw:CARD=vc4hdmi1,DEV=0",
        str(audio_path.with_name("assistant_response.playback.wav")),
    ]
    assert metadata["player"] == "aplay"
    assert metadata["args"] == ["-D", "plughw:CARD=vc4hdmi1,DEV=0"]
    assert metadata["playback_path"].endswith("assistant_response.playback.wav")


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


def test_openai_dialogue_does_not_duplicate_current_user_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = build_settings(
        tmp_path,
        dialogue_provider="openai-compatible",
        openai_base_url="https://example.test/v1",
        openai_api_key="test-token",
        openai_model="mimo-v2.5",
    )
    captured_payload = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {"choices": [{"message": {"content": "收到"}}]}
            ).encode("utf-8")

    def fake_urlopen(request: urllib.request.Request, timeout: int):
        del timeout
        captured_payload.update(json.loads(request.data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    engine = OpenAICompatibleDialogueEngine(settings)
    result = engine.generate_reply(
        [{"role": "user", "content": "你好"}],
        "你好",
    )

    user_messages = [
        message for message in captured_payload["messages"] if message["role"] == "user"
    ]
    system_message = captured_payload["messages"][0]["content"]
    assert result.assistant_text == "收到"
    assert "自动合成为语音" in system_message
    assert "不要声称自己不能控制音箱" in system_message
    assert user_messages == [{"role": "user", "content": "你好"}]


def test_zeroclaw_dialogue_invokes_cli_without_duplicate_current_user_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "zeroclaw"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    settings = build_settings(
        tmp_path,
        dialogue_provider="zeroclaw",
        zeroclaw_binary=str(binary),
        zeroclaw_working_dir=tmp_path,
        zeroclaw_provider="custom:https://token-plan-cn.xiaomimimo.com/v1",
        zeroclaw_model="mimo-v2.5",
        zeroclaw_api_key="test-token",
    )
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="收到\n",
            stderr="\x1b[33m WARN\x1b[0m zeroclaw::config::schema ignored\n",
        )

    monkeypatch.setattr("resp_lanu.providers.subprocess.run", fake_run)
    engine = ZeroClawDialogueEngine(settings)

    result = engine.generate_reply(
        [{"role": "user", "content": "打开 ZeroClaw"}],
        "打开 ZeroClaw",
    )

    assert result.assistant_text == "收到"
    assert captured["command"][:6] == [
        str(binary),
        "agent",
        "--provider",
        "custom:https://token-plan-cn.xiaomimimo.com/v1",
        "--model",
        "mimo-v2.5",
    ]
    prompt = captured["command"][-1]
    assert prompt.count("打开 ZeroClaw") == 1
    assert captured["kwargs"]["env"]["ZEROCLAW_API_KEY"] == "test-token"
    assert captured["kwargs"]["cwd"] == tmp_path


def test_mimo_router_routes_ordinary_chinese_dialogue_to_mimo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = build_settings(
        tmp_path,
        dialogue_provider="mimo-router",
        openai_base_url="https://example.test/v1",
        openai_api_key="mimo-secret-token",
        openai_model="mimo-v2.5",
        zeroclaw_api_key="zeroclaw-secret-token",
    )
    captured_payload = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {"choices": [{"message": {"content": "我是 MiMo，收到。"}}]}
            ).encode("utf-8")

    def fake_urlopen(request: urllib.request.Request, timeout: int):
        del timeout
        captured_payload.update(json.loads(request.data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    engine = MimoRouterDialogueEngine(settings)

    result = engine.generate_reply([], "你好，给我介绍一下树莓派语音助手")

    assert result.provider_name == "mimo-router"
    assert result.assistant_text == "我是 MiMo，收到。"
    assert result.metadata["route"] == "mimo"
    assert result.metadata["dialogue_provider"] == "openai-compatible"
    assert result.metadata["intent_reason"] == "default ordinary-dialogue route"
    assert captured_payload["model"] == "mimo-v2.5"
    assert "mimo-secret-token" not in json.dumps(result.metadata, ensure_ascii=False)
    assert "zeroclaw-secret-token" not in json.dumps(result.metadata, ensure_ascii=False)


def test_mimo_router_routes_action_and_memory_intents_to_zeroclaw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "zeroclaw"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    settings = build_settings(
        tmp_path,
        dialogue_provider="mimo-router",
        openai_base_url="https://example.test/v1",
        openai_api_key="shared-secret-token",
        openai_model="mimo-v2.5",
        zeroclaw_binary=str(binary),
        zeroclaw_working_dir=tmp_path,
        zeroclaw_provider="custom:https://token-plan-cn.xiaomimimo.com/v1",
        zeroclaw_model="mimo-v2.5",
        zeroclaw_api_key="shared-secret-token",
    )
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="已保存到长期记忆\n", stderr="")

    monkeypatch.setattr("resp_lanu.providers.subprocess.run", fake_run)
    engine = MimoRouterDialogueEngine(settings)

    result = engine.generate_reply([], "请记住我的机器人动作偏好，然后启动长期 daemon")

    assert result.assistant_text == "已保存到长期记忆"
    assert result.metadata["route"] == "zeroclaw"
    assert result.metadata["dialogue_provider"] == "zeroclaw"
    assert "matched keyword" in result.metadata["intent_reason"]
    assert result.metadata["command"][0] == str(binary)
    metadata_json = json.dumps(result.metadata, ensure_ascii=False)
    assert "shared-secret-token" not in metadata_json
    assert captured["kwargs"]["env"]["ZEROCLAW_API_KEY"] == "shared-secret-token"


def test_mimo_router_falls_back_without_leaking_secrets(tmp_path: Path) -> None:
    settings = build_settings(
        tmp_path,
        dialogue_provider="mimo-router",
        openai_base_url=None,
        openai_api_key="mimo-secret-token",
        zeroclaw_binary=str(tmp_path / "missing-zeroclaw"),
        zeroclaw_api_key="zeroclaw-secret-token",
    )
    engine = MimoRouterDialogueEngine(settings)

    mimo_result = engine.generate_reply([], "你好，请介绍一下你自己")
    zeroclaw_result = engine.generate_reply([], "请记住这个长期任务")

    assert mimo_result.metadata["route"] == "mimo"
    assert mimo_result.metadata["dialogue_provider"] == "rule-based"
    assert mimo_result.metadata["requested_dialogue_provider"] == "openai-compatible"
    assert "fallback_reason" in mimo_result.metadata
    assert zeroclaw_result.metadata["route"] == "zeroclaw"
    assert zeroclaw_result.metadata["dialogue_provider"] == "rule-based"
    assert zeroclaw_result.metadata["requested_dialogue_provider"] == "zeroclaw"
    metadata_json = json.dumps(
        {"mimo": mimo_result.metadata, "zeroclaw": zeroclaw_result.metadata},
        ensure_ascii=False,
    )
    assert "mimo-secret-token" not in metadata_json
    assert "zeroclaw-secret-token" not in metadata_json


def test_api_can_record_pi_audio_and_submit_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = build_settings(
        tmp_path,
        profile="dev-mac",
        recording_device="plughw:CARD=Device,DEV=0",
    )
    runtime = AssistantRuntime(
        settings,
        recognizer=FakeRecognizer(),
        primary_dialogue_engine=FakeDialogueEngine(),
        fallback_dialogue_engine=FakeDialogueEngine(),
        synthesizer=FakeSynthesizer(),
    )
    app = create_app(settings=settings, runtime=runtime)
    headers = {"x-admin-token": settings.admin_token}

    def fake_arecord(command, **kwargs):
        del kwargs
        assert command[:4] == ["arecord", "-q", "-D", "plughw:CARD=Device,DEV=0"]
        Path(command[-1]).write_bytes(create_wav_bytes())
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(runtime_module.subprocess, "run", fake_arecord)

    with TestClient(app) as client:
        record_response = client.post(
            "/api/v1/audio/record",
            headers=headers,
            json={"duration_seconds": 1},
        )
        assert record_response.status_code == 200
        upload_artifact = record_response.json()["artifact"]
        metadata = json.loads(upload_artifact["metadata_json"])
        assert upload_artifact["kind"] == "uploaded_audio"
        assert metadata["source"] == "pi_arecord"

        job_response = client.post(
            "/api/v1/assistant/respond",
            headers=headers,
            json={
                "title": "Pi5 录音接口",
                "text_input": "接口测试",
                "upload_artifact_id": upload_artifact["id"],
                "use_tts": False,
            },
        )
        assert job_response.status_code == 200
        finished = wait_for_job(runtime, job_response.json()["job"]["id"])
        assert finished["job"]["status"] == "completed"
        assert any(item["kind"] == "asr_result" for item in finished["artifacts"])


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


def test_project_exposes_pi_voice_turn_command() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    cli_source = Path("src/resp_lanu/cli.py").read_text(encoding="utf-8")
    assert "resp-lanu-voice-turn" in pyproject
    assert "def voice_turn_command" in cli_source
    assert "record_pi_audio" in cli_source


def test_assistant_console_includes_browser_recording_ui() -> None:
    template = Path("src/resp_lanu/templates/assistant.html").read_text(encoding="utf-8")
    app_js = Path("src/resp_lanu/static/app.js").read_text(encoding="utf-8")
    assert 'id="pi-record-submit"' in template
    assert 'id="record-start"' in template
    assert 'id="record-stop"' in template
    assert "/api/v1/audio/record" in app_js
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
