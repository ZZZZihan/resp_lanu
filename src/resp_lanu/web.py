from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .runtime import AssistantRuntime
from .schemas import (
    ArtifactResponse,
    AssistantRespondRequest,
    HealthResponse,
    JobEventResponse,
    JobResponse,
    SessionResponse,
    SettingsResponse,
    TurnResponse,
    UploadResponse,
)
from .settings import Settings, get_settings

ALLOWED_UPLOAD_EXTENSIONS = frozenset({".wav", ".webm", ".ogg", ".mp4", ".m4a"})
ALLOWED_UPLOAD_MIME_TYPES = frozenset(
    {
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
        "audio/vnd.wave",
        "audio/webm",
        "video/webm",
        "audio/ogg",
        "application/ogg",
        "audio/mp4",
        "video/mp4",
        "audio/x-m4a",
    }
)
UPLOAD_CHUNK_SIZE = 1024 * 1024


def create_app(
    settings: Settings | None = None,
    runtime: AssistantRuntime | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    settings.validate_service_security()
    runtime = runtime or AssistantRuntime(settings)
    templates = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime.start()
        yield
        runtime.stop()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, same_site="lax")
    app.state.runtime = runtime
    app.state.settings = settings
    app.mount(
        "/static", StaticFiles(directory=str(Path(__file__).with_name("static"))), name="static"
    )

    def runtime_dep() -> AssistantRuntime:
        return runtime

    def is_authenticated(request: Request) -> bool:
        header_token = request.headers.get("x-admin-token", "")
        if header_token and secrets.compare_digest(header_token, settings.admin_token):
            return True
        return bool(request.session.get("authenticated"))

    def require_api_auth(request: Request) -> None:
        if not is_authenticated(request):
            raise HTTPException(status_code=401, detail="Authentication required.")

    def normalized_upload_mime(file: UploadFile) -> str:
        return (file.content_type or "").split(";", 1)[0].strip().lower()

    def validate_upload_metadata(file: UploadFile) -> str:
        filename = file.filename or ""
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
            raise HTTPException(status_code=415, detail="Unsupported audio file extension.")
        media_type = normalized_upload_mime(file)
        if media_type not in ALLOWED_UPLOAD_MIME_TYPES:
            raise HTTPException(status_code=415, detail="Unsupported audio media type.")
        return media_type

    async def read_limited_upload(file: UploadFile) -> bytes:
        chunks = []
        total_size = 0
        while True:
            remaining = settings.max_upload_bytes - total_size + 1
            read_size = max(1, min(UPLOAD_CHUNK_SIZE, remaining))
            chunk = await file.read(read_size)
            if not chunk:
                break
            total_size += len(chunk)
            if total_size > settings.max_upload_bytes:
                raise HTTPException(status_code=413, detail="Uploaded audio is too large.")
            chunks.append(chunk)
        if total_size == 0:
            raise HTTPException(status_code=400, detail="Uploaded audio is empty.")
        return b"".join(chunks)

    def render_page(
        request: Request, template_name: str, *, page_name: str, page_title: str
    ) -> HTMLResponse:
        if not is_authenticated(request):
            return RedirectResponse(url="/login", status_code=303)
        return templates.TemplateResponse(
            name=template_name,
            request=request,
            context={
                "page_name": page_name,
                "page_title": page_title,
                "app_name": settings.app_name,
                "profile": settings.profile,
            },
        )

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/assistant", status_code=303)

    @app.get("/login", response_class=HTMLResponse, include_in_schema=False)
    def login_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            name="login.html",
            request=request,
            context={
                "page_name": "login",
                "page_title": "登录",
                "app_name": settings.app_name,
                "error": None,
            },
        )

    @app.post("/login", include_in_schema=False)
    def login(request: Request, token: str = Form(...)) -> Response:
        if secrets.compare_digest(token, settings.admin_token):
            request.session["authenticated"] = True
            return RedirectResponse(url="/assistant", status_code=303)
        return templates.TemplateResponse(
            name="login.html",
            request=request,
            context={
                "page_name": "login",
                "page_title": "登录",
                "app_name": settings.app_name,
                "error": "管理令牌不正确。",
            },
            status_code=401,
        )

    @app.post("/logout", include_in_schema=False)
    def logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)

    @app.get("/assistant", response_class=HTMLResponse, include_in_schema=False)
    def assistant_page(request: Request) -> HTMLResponse:
        return render_page(request, "assistant.html", page_name="assistant", page_title="Assistant")

    @app.get("/history", response_class=HTMLResponse, include_in_schema=False)
    def history_page(request: Request) -> HTMLResponse:
        return render_page(request, "history.html", page_name="history", page_title="History")

    @app.get("/artifacts", response_class=HTMLResponse, include_in_schema=False)
    def artifacts_page(request: Request) -> HTMLResponse:
        return render_page(request, "artifacts.html", page_name="artifacts", page_title="Artifacts")

    @app.get("/settings", response_class=HTMLResponse, include_in_schema=False)
    def settings_page(request: Request) -> HTMLResponse:
        return render_page(request, "settings.html", page_name="settings", page_title="Settings")

    @app.get("/health", response_class=HTMLResponse, include_in_schema=False)
    def health_page(request: Request) -> HTMLResponse:
        return render_page(request, "health.html", page_name="health", page_title="Health")

    @app.get("/health/live", response_model=HealthResponse)
    def live_health(app_runtime: AssistantRuntime = Depends(runtime_dep)) -> dict:
        return app_runtime.health_payload()

    @app.get("/health/ready", response_model=HealthResponse)
    def ready_health(app_runtime: AssistantRuntime = Depends(runtime_dep)) -> dict:
        return app_runtime.health_payload()

    @app.get("/api/v1/health", response_model=HealthResponse)
    def api_health(app_runtime: AssistantRuntime = Depends(runtime_dep)) -> dict:
        return app_runtime.health_payload()

    @app.get("/api/v1/settings", response_model=SettingsResponse)
    def api_settings(
        request: Request, app_runtime: AssistantRuntime = Depends(runtime_dep)
    ) -> dict:
        require_api_auth(request)
        return app_runtime.settings_payload()

    @app.post("/api/v1/sessions", response_model=SessionResponse)
    def create_session(
        request: Request,
        title: str | None = Form(default=None),
        app_runtime: AssistantRuntime = Depends(runtime_dep),
    ) -> dict:
        require_api_auth(request)
        return app_runtime.create_session(title=title)

    @app.get("/api/v1/sessions", response_model=list[SessionResponse])
    def list_sessions(
        request: Request, app_runtime: AssistantRuntime = Depends(runtime_dep)
    ) -> list[dict]:
        require_api_auth(request)
        return app_runtime.storage.list_sessions()

    @app.get("/api/v1/sessions/{session_id}", response_model=SessionResponse)
    def get_session(
        session_id: str, request: Request, app_runtime: AssistantRuntime = Depends(runtime_dep)
    ) -> dict:
        require_api_auth(request)
        session = app_runtime.storage.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found.")
        return session

    @app.get("/api/v1/turns/{turn_id}", response_model=TurnResponse)
    def get_turn(
        turn_id: str, request: Request, app_runtime: AssistantRuntime = Depends(runtime_dep)
    ) -> dict:
        require_api_auth(request)
        turn = app_runtime.storage.get_turn(turn_id)
        if not turn:
            raise HTTPException(status_code=404, detail="Turn not found.")
        return turn

    @app.get("/api/v1/jobs", response_model=list[JobResponse])
    def list_jobs(
        request: Request, app_runtime: AssistantRuntime = Depends(runtime_dep)
    ) -> list[dict]:
        require_api_auth(request)
        return app_runtime.storage.list_jobs()

    @app.get("/api/v1/jobs/{job_id}", response_model=JobEventResponse)
    def get_job(
        job_id: str, request: Request, app_runtime: AssistantRuntime = Depends(runtime_dep)
    ) -> dict:
        require_api_auth(request)
        return app_runtime.get_job_snapshot(job_id)

    @app.get("/api/v1/jobs/{job_id}/events")
    def stream_job_events(
        job_id: str,
        request: Request,
        app_runtime: AssistantRuntime = Depends(runtime_dep),
    ) -> StreamingResponse:
        require_api_auth(request)
        initial_payload = app_runtime.get_job_snapshot(job_id)
        return StreamingResponse(
            app_runtime.events.stream(job_id, initial_payload),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/v1/artifacts", response_model=list[ArtifactResponse])
    def list_artifacts(
        request: Request,
        session_id: str | None = None,
        turn_id: str | None = None,
        kind: str | None = None,
        app_runtime: AssistantRuntime = Depends(runtime_dep),
    ) -> list[dict]:
        require_api_auth(request)
        return app_runtime.storage.list_artifacts(session_id=session_id, turn_id=turn_id, kind=kind)

    @app.get("/api/v1/artifacts/{artifact_id}", response_model=ArtifactResponse)
    def get_artifact(
        artifact_id: str,
        request: Request,
        app_runtime: AssistantRuntime = Depends(runtime_dep),
    ) -> dict:
        require_api_auth(request)
        artifact = app_runtime.storage.get_artifact(artifact_id)
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found.")
        return artifact

    @app.get("/api/v1/artifacts/{artifact_id}/content")
    def download_artifact(
        artifact_id: str,
        request: Request,
        app_runtime: AssistantRuntime = Depends(runtime_dep),
    ) -> FileResponse:
        require_api_auth(request)
        artifact = app_runtime.storage.get_artifact(artifact_id)
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found.")
        file_path = settings.workspace_dir / artifact["relative_path"]
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Artifact file is missing on disk.")
        return FileResponse(
            file_path, media_type=artifact["media_type"], filename=Path(file_path).name
        )

    @app.post("/api/v1/audio/upload", response_model=UploadResponse)
    async def upload_audio(
        request: Request,
        file: UploadFile = File(...),
        app_runtime: AssistantRuntime = Depends(runtime_dep),
    ) -> dict:
        require_api_auth(request)
        media_type = validate_upload_metadata(file)
        content = await read_limited_upload(file)
        artifact = app_runtime.create_uploaded_audio(
            filename=file.filename or "upload.wav",
            media_type=media_type,
            content=content,
        )
        return {"artifact": artifact}

    @app.get("/api/v1/audio/recordings", response_model=list[ArtifactResponse])
    def list_recordings(
        request: Request, app_runtime: AssistantRuntime = Depends(runtime_dep)
    ) -> list[dict]:
        require_api_auth(request)
        return app_runtime.storage.list_audio_recordings()

    @app.post("/api/v1/assistant/respond", response_model=JobEventResponse)
    def assistant_respond(
        payload: AssistantRespondRequest,
        request: Request,
        app_runtime: AssistantRuntime = Depends(runtime_dep),
    ) -> dict:
        require_api_auth(request)
        return app_runtime.submit_assistant_turn(payload.model_dump())

    return app
