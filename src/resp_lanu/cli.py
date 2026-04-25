from __future__ import annotations

import argparse
import json
from pathlib import Path

import uvicorn

from .legacy import export_legacy_artifacts
from .runtime import AssistantRuntime
from .settings import Settings


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
    print(json.dumps(report, ensure_ascii=False, indent=2))


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
