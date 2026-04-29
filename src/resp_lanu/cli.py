from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import uvicorn
from pydantic import BaseModel

from .legacy import export_legacy_artifacts
from .runtime import AssistantRuntime
from .settings import Settings


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value


def _build_settings(args: argparse.Namespace) -> Settings:
    settings_kwargs = {
        "profile": args.profile,
        "workspace_dir": Path.cwd(),
    }
    if getattr(args, "host", None) is not None:
        settings_kwargs["bind_host"] = args.host
    if getattr(args, "port", None) is not None:
        settings_kwargs["bind_port"] = args.port
    return Settings(**settings_kwargs)


def serve_command() -> None:
    parser = argparse.ArgumentParser(description="Run the resp-lanu local HTTP service.")
    parser.add_argument(
        "--profile", default="dev-mac", choices=["dev-mac", "pi-offline", "pi-connected"]
    )
    parser.add_argument("--host", default=None, help="Override bind host.")
    parser.add_argument("--port", type=int, default=None, help="Override bind port.")
    args = parser.parse_args()

    settings = _build_settings(args)
    from .web import create_app

    app = create_app(settings=settings)
    uvicorn.run(
        app, host=settings.bind_host, port=settings.bind_port, log_level=settings.log_level.lower()
    )


def doctor_command() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect local configuration and provider readiness."
    )
    parser.add_argument(
        "--profile", default="dev-mac", choices=["dev-mac", "pi-offline", "pi-connected"]
    )
    args = parser.parse_args()
    settings = Settings(profile=args.profile, workspace_dir=Path.cwd())
    runtime = AssistantRuntime(settings)
    try:
        report = {
            "settings": settings.masked_settings(),
            "health": runtime.health_payload(),
            "checks": {
                "database_path_exists": settings.database_path.parent.exists(),
                "model_dir_exists": settings.model_dir.exists(),
                "uploads_dir_exists": settings.uploads_dir.exists(),
                "sessions_dir_exists": settings.sessions_dir.exists(),
                "admin_token_is_default": settings.admin_token_is_default(),
                "session_secret_is_default": settings.session_secret_is_default(),
                "service_security_blocking": bool(settings.service_security_issues()),
            },
        }
        print(json.dumps(_json_ready(report), ensure_ascii=False, indent=2))
    finally:
        runtime.storage.close()


def voice_turn_command() -> None:
    parser = argparse.ArgumentParser(
        description="Record from the Pi microphone, run one assistant turn, and play TTS."
    )
    parser.add_argument(
        "--profile", default="pi-connected", choices=["dev-mac", "pi-offline", "pi-connected"]
    )
    parser.add_argument("--duration", type=int, default=6, help="Recording duration in seconds.")
    parser.add_argument("--timeout", type=float, default=180.0, help="Job completion timeout.")
    parser.add_argument("--title", default="Pi5 直接语音对话")
    parser.add_argument(
        "--text-input",
        default=None,
        help="Optional text appended to ASR transcript.",
    )
    parser.add_argument(
        "--loop", action="store_true", help="Continue recording turns until Ctrl+C."
    )
    parser.add_argument(
        "--pause-seconds", type=float, default=0.5, help="Delay between looped turns."
    )
    parser.add_argument("--no-tts", action="store_true", help="Skip assistant audio synthesis.")
    parser.add_argument(
        "--no-server-playback",
        action="store_true",
        help="Do not play synthesized audio through the Pi default output.",
    )
    args = parser.parse_args()

    settings = Settings(profile=args.profile, workspace_dir=Path.cwd())
    if args.no_server_playback:
        settings.play_assistant_audio_on_server = False

    runtime = AssistantRuntime(settings)
    runtime.start()
    session_id: str | None = None
    try:
        while True:
            print(f"Recording {args.duration}s from {settings.recording_device or 'auto'}...")
            upload = runtime.record_pi_audio(duration_seconds=args.duration)
            snapshot = runtime.submit_assistant_turn(
                {
                    "session_id": session_id,
                    "title": args.title,
                    "text_input": args.text_input,
                    "upload_artifact_id": upload["id"],
                    "use_tts": not args.no_tts,
                }
            )
            finished = _wait_for_job(runtime, snapshot["job"]["id"], timeout=args.timeout)
            session_id = finished["job"]["session_id"]
            _print_voice_turn_result(finished)
            if finished["job"]["status"] != "completed" or not args.loop:
                break
            time.sleep(max(0.0, args.pause_seconds))
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        runtime.stop()


def _wait_for_job(runtime: AssistantRuntime, job_id: str, *, timeout: float) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snapshot = runtime.get_job_snapshot(job_id)
        if snapshot["job"]["status"] in {"completed", "failed"}:
            return snapshot
        time.sleep(0.2)
    raise TimeoutError(f"Timed out waiting for job {job_id}.")


def _print_voice_turn_result(snapshot: dict[str, Any]) -> None:
    job = snapshot["job"]
    turn = snapshot.get("turn") or {}
    result_payload = json.loads(job.get("result_payload") or "{}")
    metadata = result_payload.get("metadata") or {}
    dialogue = metadata.get("dialogue") or {}
    print(json.dumps(
        {
            "status": job["status"],
            "transcript": turn.get("transcript"),
            "user_text": turn.get("user_text"),
            "assistant_text": turn.get("assistant_text"),
            "route": dialogue.get("route"),
            "dialogue_provider": dialogue.get("dialogue_provider"),
            "tts_warning": metadata.get("tts_warning"),
            "server_audio_playback": metadata.get("server_audio_playback"),
        },
        ensure_ascii=False,
        indent=2,
    ))


def export_legacy_artifacts_command() -> None:
    parser = argparse.ArgumentParser(
        description="Export the latest completed turn into the legacy artifacts layout."
    )
    parser.add_argument(
        "--profile", default="dev-mac", choices=["dev-mac", "pi-offline", "pi-connected"]
    )
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--turn-id", default=None)
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    settings = Settings(profile=args.profile, workspace_dir=Path.cwd())
    storage = AssistantRuntime(settings).storage
    output_dir = Path(args.output_dir or settings.legacy_artifacts_dir / "legacy_export")
    exported = export_legacy_artifacts(
        storage,
        output_dir,
        session_id=args.session_id,
        turn_id=args.turn_id,
        workspace_dir=settings.workspace_dir,
    )
    print(str(exported))
