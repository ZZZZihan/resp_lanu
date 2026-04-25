from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


BASELINE_SCHEMA_VERSION = 1


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    job_id TEXT,
    source_upload_artifact_id TEXT,
    user_text TEXT,
    transcript TEXT,
    assistant_text TEXT,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    status TEXT NOT NULL,
    phase TEXT NOT NULL,
    error TEXT,
    request_payload TEXT,
    result_payload TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(id),
    FOREIGN KEY(turn_id) REFERENCES turns(id)
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    turn_id TEXT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(id),
    FOREIGN KEY(turn_id) REFERENCES turns(id)
);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    turn_id TEXT,
    job_id TEXT,
    kind TEXT NOT NULL,
    label TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    media_type TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings_snapshots (
    id TEXT PRIMARY KEY,
    profile TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row

    def initialize(self) -> None:
        with self._lock:
            self._connection.executescript(SCHEMA)
            self._connection.execute(
                """
                INSERT OR IGNORE INTO schema_migrations (version, applied_at)
                VALUES (?, ?)
                """,
                (BASELINE_SCHEMA_VERSION, utc_now()),
            )
            self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _execute(self, query: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        cursor = self._connection.execute(query, params)
        self._connection.commit()
        return cursor

    def _fetchone(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        row = self._connection.execute(query, params).fetchone()
        return dict(row) if row else None

    def _fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        rows = self._connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def schema_version(self) -> int:
        with self._lock:
            row = self._fetchone("SELECT MAX(version) AS version FROM schema_migrations")
            return int(row["version"] or 0) if row else 0

    def create_session(self, title: str | None = None) -> dict[str, Any]:
        with self._lock:
            session_id = uuid.uuid4().hex
            now = utc_now()
            title = (title or "新建语音会话").strip()
            self._execute(
                "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (session_id, title, now, now),
            )
            return self.get_session(session_id) or {}

    def touch_session(self, session_id: str) -> None:
        with self._lock:
            self._execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (utc_now(), session_id),
            )

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._fetchall(
                """
                SELECT
                    s.*,
                    COALESCE(
                        (SELECT COUNT(*) FROM turns t WHERE t.session_id = s.id),
                        0
                    ) AS turn_count
                FROM sessions s
                ORDER BY s.updated_at DESC
                """
            )
            return rows

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            session = self._fetchone(
                """
                SELECT
                    s.*,
                    COALESCE(
                        (SELECT COUNT(*) FROM turns t WHERE t.session_id = s.id),
                        0
                    ) AS turn_count
                FROM sessions s
                WHERE s.id = ?
                """,
                (session_id,),
            )
            if not session:
                return None
            session["turns"] = self.list_turns(session_id)
            return session

    def list_turns(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            turns = self._fetchall(
                "SELECT * FROM turns WHERE session_id = ? ORDER BY created_at DESC",
                (session_id,),
            )
            for turn in turns:
                turn["artifacts"] = self.list_artifacts(turn_id=turn["id"])
                turn["messages"] = self.list_messages(session_id, turn_id=turn["id"])
            return turns

    def get_turn(self, turn_id: str) -> dict[str, Any] | None:
        with self._lock:
            turn = self._fetchone("SELECT * FROM turns WHERE id = ?", (turn_id,))
            if not turn:
                return None
            turn["artifacts"] = self.list_artifacts(turn_id=turn_id)
            turn["messages"] = self.list_messages(turn["session_id"], turn_id=turn_id)
            return turn

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._fetchall("SELECT * FROM jobs ORDER BY created_at DESC")

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._fetchone("SELECT * FROM jobs WHERE id = ?", (job_id,))

    def list_recoverable_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._fetchall(
                """
                SELECT * FROM jobs
                WHERE status IN ('queued', 'running')
                ORDER BY created_at ASC
                """
            )

    def create_assistant_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            session_id = payload.get("session_id")
            title = payload.get("title")
            if session_id:
                session = self.get_session(session_id)
                if not session:
                    raise ValueError(f"Unknown session_id: {session_id}")
            else:
                session = self.create_session(title=title or self._derive_session_title(payload))
                session_id = session["id"]

            now = utc_now()
            turn_id = uuid.uuid4().hex
            job_id = uuid.uuid4().hex

            self._execute(
                """
                INSERT INTO turns (
                    id, session_id, job_id, source_upload_artifact_id, user_text, transcript,
                    assistant_text, status, error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn_id,
                    session_id,
                    job_id,
                    payload.get("upload_artifact_id"),
                    payload.get("text_input"),
                    None,
                    None,
                    "queued",
                    None,
                    now,
                    now,
                ),
            )

            self._execute(
                """
                INSERT INTO jobs (
                    id, session_id, turn_id, status, phase, error, request_payload,
                    result_payload, created_at, started_at, finished_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    session_id,
                    turn_id,
                    "queued",
                    "queued",
                    None,
                    json.dumps(payload, ensure_ascii=False),
                    None,
                    now,
                    None,
                    None,
                    now,
                ),
            )
            self.touch_session(session_id)
            return self.get_job(job_id) or {}

    def reset_running_job_for_recovery(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self.get_job(job_id)
            if not job:
                raise ValueError(f"Unknown job_id: {job_id}")
            if job["status"] != "running":
                return job

            now = utc_now()
            self._connection.execute("DELETE FROM messages WHERE turn_id = ?", (job["turn_id"],))
            self._connection.execute("DELETE FROM artifacts WHERE turn_id = ?", (job["turn_id"],))
            self._connection.execute(
                """
                UPDATE turns
                SET
                    user_text = NULL,
                    transcript = NULL,
                    assistant_text = NULL,
                    status = 'queued',
                    error = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, job["turn_id"]),
            )
            self._connection.execute(
                """
                UPDATE jobs
                SET
                    status = 'queued',
                    phase = 'queued',
                    error = NULL,
                    result_payload = NULL,
                    started_at = NULL,
                    finished_at = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, job_id),
            )
            self._connection.commit()
            return self.get_job(job_id) or {}

    def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        phase: str | None = None,
        error: str | None = None,
        result_payload: dict[str, Any] | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            job = self.get_job(job_id)
            if not job:
                raise ValueError(f"Unknown job_id: {job_id}")
            next_status = status or job["status"]
            next_phase = phase or job["phase"]
            next_error = error
            next_result = (
                json.dumps(result_payload, ensure_ascii=False)
                if result_payload is not None
                else job["result_payload"]
            )
            next_started = started_at if started_at is not None else job["started_at"]
            next_finished = finished_at if finished_at is not None else job["finished_at"]
            self._execute(
                """
                UPDATE jobs
                SET
                    status = ?,
                    phase = ?,
                    error = ?,
                    result_payload = ?,
                    started_at = ?,
                    finished_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    next_status,
                    next_phase,
                    next_error,
                    next_result,
                    next_started,
                    next_finished,
                    utc_now(),
                    job_id,
                ),
            )
            return self.get_job(job_id) or {}

    def update_turn(
        self,
        turn_id: str,
        *,
        user_text: str | None = None,
        transcript: str | None = None,
        assistant_text: str | None = None,
        status: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            turn = self.get_turn(turn_id)
            if not turn:
                raise ValueError(f"Unknown turn_id: {turn_id}")
            self._execute(
                """
                UPDATE turns
                SET
                    user_text = ?,
                    transcript = ?,
                    assistant_text = ?,
                    status = ?,
                    error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    user_text if user_text is not None else turn["user_text"],
                    transcript if transcript is not None else turn["transcript"],
                    assistant_text if assistant_text is not None else turn["assistant_text"],
                    status if status is not None else turn["status"],
                    error,
                    utc_now(),
                    turn_id,
                ),
            )
            session_id = turn["session_id"]
            self.touch_session(session_id)
            return self.get_turn(turn_id) or {}

    def add_message(
        self, session_id: str, turn_id: str | None, role: str, content: str
    ) -> dict[str, Any]:
        with self._lock:
            message_id = uuid.uuid4().hex
            now = utc_now()
            self._execute(
                """
                INSERT INTO messages (id, session_id, turn_id, role, content, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (message_id, session_id, turn_id, role, content, now),
            )
            self.touch_session(session_id)
            return self._fetchone("SELECT * FROM messages WHERE id = ?", (message_id,)) or {}

    def list_messages(self, session_id: str, turn_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if turn_id:
                return self._fetchall(
                    """
                    SELECT * FROM messages
                    WHERE session_id = ? AND turn_id = ?
                    ORDER BY created_at ASC
                    """,
                    (session_id, turn_id),
                )
            return self._fetchall(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            )

    def add_artifact(
        self,
        *,
        session_id: str | None,
        turn_id: str | None,
        job_id: str | None,
        kind: str,
        label: str,
        relative_path: str,
        media_type: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            artifact_id = uuid.uuid4().hex
            self._execute(
                """
                INSERT INTO artifacts (
                    id,
                    session_id,
                    turn_id,
                    job_id,
                    kind,
                    label,
                    relative_path,
                    media_type,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    session_id,
                    turn_id,
                    job_id,
                    kind,
                    label,
                    relative_path,
                    media_type,
                    json.dumps(metadata, ensure_ascii=False) if metadata else None,
                    utc_now(),
                ),
            )
            return self.get_artifact(artifact_id) or {}

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._fetchone("SELECT * FROM artifacts WHERE id = ?", (artifact_id,))

    def list_artifacts(
        self,
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            clauses = []
            params: list[Any] = []
            if session_id is not None:
                clauses.append("session_id = ?")
                params.append(session_id)
            if turn_id is not None:
                clauses.append("turn_id = ?")
                params.append(turn_id)
            if kind is not None:
                clauses.append("kind = ?")
                params.append(kind)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            return self._fetchall(
                f"SELECT * FROM artifacts {where} ORDER BY created_at DESC",
                tuple(params),
            )

    def list_audio_recordings(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._fetchall(
                """
                SELECT * FROM artifacts
                WHERE kind IN ('uploaded_audio', 'input_audio', 'assistant_audio')
                ORDER BY created_at DESC
                """
            )

    def record_settings_snapshot(self, profile: str, payload: dict[str, Any]) -> None:
        with self._lock:
            snapshot_id = uuid.uuid4().hex
            self._execute(
                """
                INSERT INTO settings_snapshots (id, profile, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (snapshot_id, profile, json.dumps(payload, ensure_ascii=False), utc_now()),
            )

    def latest_completed_turn(self, session_id: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            if session_id:
                turn = self._fetchone(
                    """
                    SELECT * FROM turns
                    WHERE session_id = ? AND status = 'completed'
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (session_id,),
                )
            else:
                turn = self._fetchone(
                    """
                    SELECT * FROM turns
                    WHERE status = 'completed'
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """
                )
            if not turn:
                return None
            return self.get_turn(turn["id"])

    def _derive_session_title(self, payload: dict[str, Any]) -> str:
        text = (payload.get("text_input") or "").strip()
        if text:
            return text[:24]
        if payload.get("upload_artifact_id"):
            return "语音输入会话"
        return "新建语音会话"
