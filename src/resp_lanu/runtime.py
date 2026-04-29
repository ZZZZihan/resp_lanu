from __future__ import annotations

import json
import queue
import re
import shlex
import shutil
import subprocess
import threading
import traceback
from pathlib import Path
from typing import Any

from .audio import preprocess_audio
from .providers import (
    DialogueEngine,
    ProviderUnavailableError,
    SpeechRecognizer,
    SpeechSynthesizer,
    build_provider_bundle,
)
from .schemas import JobPhase, JobStatus, ProviderStatus
from .settings import Settings
from .storage import Database, utc_now


class JobEventBroker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[str, list[queue.Queue[dict[str, Any]]]] = {}

    def subscribe(self, job_id: str) -> queue.Queue[dict[str, Any]]:
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue()
        with self._lock:
            self._subscribers.setdefault(job_id, []).append(subscriber)
        return subscriber

    def unsubscribe(self, job_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            subscribers = self._subscribers.get(job_id, [])
            if subscriber in subscribers:
                subscribers.remove(subscriber)
            if not subscribers and job_id in self._subscribers:
                self._subscribers.pop(job_id, None)

    def publish(self, job_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            subscribers = list(self._subscribers.get(job_id, []))
        for subscriber in subscribers:
            subscriber.put(payload)

    def stream(self, job_id: str, initial_payload: dict[str, Any]) -> Any:
        subscriber = self.subscribe(job_id)
        try:
            yield self._format_sse(initial_payload)
            while True:
                try:
                    payload = subscriber.get(timeout=2)
                    yield self._format_sse(payload)
                except queue.Empty:
                    yield ": ping\n\n"
        finally:
            self.unsubscribe(job_id, subscriber)

    def _format_sse(self, payload: dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


class AssistantRuntime:
    def __init__(
        self,
        settings: Settings,
        *,
        storage: Database | None = None,
        recognizer: SpeechRecognizer | None = None,
        primary_dialogue_engine: DialogueEngine | None = None,
        fallback_dialogue_engine: DialogueEngine | None = None,
        synthesizer: SpeechSynthesizer | None = None,
    ) -> None:
        self.settings = settings
        self.settings.ensure_directories()
        self.storage = storage or Database(settings.database_path)
        self.storage.initialize()
        providers = build_provider_bundle(settings)
        self.recognizer = recognizer or providers["recognizer"]
        self.primary_dialogue_engine = primary_dialogue_engine or providers["dialogue"]
        self.fallback_dialogue_engine = fallback_dialogue_engine or providers["fallback_dialogue"]
        self.synthesizer = synthesizer or providers["synthesizer"]
        self.events = JobEventBroker()
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._worker_thread: threading.Thread | None = None
        self._worker_running = False

    def start(self) -> None:
        if self._worker_running:
            return
        self.storage.record_settings_snapshot(
            self.settings.profile, self.settings.masked_settings()
        )
        recovered_job_ids = self._recover_interrupted_jobs()
        self._worker_running = True
        for job_id in recovered_job_ids:
            self._queue.put(job_id)
        self._worker_thread = threading.Thread(
            target=self._worker_loop, name="resp-lanu-worker", daemon=True
        )
        self._worker_thread.start()

    def stop(self) -> None:
        if not self._worker_running:
            return
        self._worker_running = False
        self._queue.put(None)
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=5)
        self.storage.close()

    def worker_running(self) -> bool:
        return bool(self._worker_thread and self._worker_thread.is_alive())

    def queue_size(self) -> int:
        return self._queue.qsize()

    def provider_statuses(self) -> dict[str, ProviderStatus]:
        return {
            "recognizer": self.recognizer.status(),
            "dialogue": self.primary_dialogue_engine.status(),
            "fallback_dialogue": self.fallback_dialogue_engine.status(),
            "tts": self.synthesizer.status(),
        }

    def health_payload(self) -> dict[str, Any]:
        provider_statuses = self.provider_statuses()
        ready = self.settings.model_dir.exists() and self.storage.database_path.exists()
        status = "ok" if ready else "degraded"
        return {
            "status": status,
            "ready": ready,
            "worker_running": self.worker_running(),
            "queue_size": self.queue_size(),
            "profile": self.settings.profile,
            "providers": provider_statuses,
        }

    def settings_payload(self) -> dict[str, Any]:
        return {
            "settings": self.settings.masked_settings(),
            "providers": self.provider_statuses(),
        }

    def create_uploaded_audio(
        self,
        *,
        filename: str,
        media_type: str | None,
        content: bytes,
    ) -> dict[str, Any]:
        artifact_id = self._new_id()
        safe_name = Path(filename or "upload.wav").name
        target_dir = self.settings.uploads_dir / artifact_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / safe_name
        target_path.write_bytes(content)
        relative_path = self._relative_to_workspace(target_path)
        return self.storage.add_artifact(
            session_id=None,
            turn_id=None,
            job_id=None,
            kind="uploaded_audio",
            label=safe_name,
            relative_path=relative_path,
            media_type=media_type or "audio/wav",
            metadata={
                "size_bytes": len(content),
                "original_filename": safe_name,
                "source_media_type": media_type or "audio/wav",
            },
        )

    def record_pi_audio(self, *, duration_seconds: int) -> dict[str, Any]:
        artifact_id = self._new_id()
        target_dir = self.settings.uploads_dir / artifact_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "pi-recording.wav"
        device = self.settings.recording_device or self._detect_recording_device()
        command = [
            "arecord",
            "-q",
            "-D",
            device,
            "-f",
            "S16_LE",
            "-r",
            "16000",
            "-c",
            "1",
            "-d",
            str(duration_seconds),
            "-t",
            "wav",
            str(target_path),
        ]
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=duration_seconds + 5,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("arecord is required for Raspberry Pi recording.") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Raspberry Pi recording timed out.") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            raise RuntimeError(f"Raspberry Pi recording failed: {detail}") from exc

        if not target_path.exists() or target_path.stat().st_size <= 44:
            raise RuntimeError("Raspberry Pi recording produced an empty WAV file.")

        return self.storage.add_artifact(
            session_id=None,
            turn_id=None,
            job_id=None,
            kind="uploaded_audio",
            label=target_path.name,
            relative_path=self._relative_to_workspace(target_path),
            media_type="audio/wav",
            metadata={
                "source": "pi_arecord",
                "recording_device": device,
                "duration_seconds": duration_seconds,
                "size_bytes": target_path.stat().st_size,
            },
        )

    def create_session(self, title: str | None = None) -> dict[str, Any]:
        return self.storage.create_session(title)

    def submit_assistant_turn(self, payload: dict[str, Any]) -> dict[str, Any]:
        job = self.storage.create_assistant_job(payload)
        self._queue.put(job["id"])
        snapshot = self.get_job_snapshot(job["id"])
        self.events.publish(job["id"], snapshot)
        return snapshot

    def get_job_snapshot(self, job_id: str) -> dict[str, Any]:
        job = self.storage.get_job(job_id)
        if not job:
            raise ValueError(f"Unknown job_id: {job_id}")
        turn = self.storage.get_turn(job["turn_id"])
        session = self.storage.get_session(job["session_id"])
        artifacts = self.storage.list_artifacts(turn_id=job["turn_id"])
        return {
            "job": job,
            "turn": turn,
            "session": session,
            "artifacts": artifacts,
        }

    def _recover_interrupted_jobs(self) -> list[str]:
        recovered_job_ids = []
        for job in self.storage.list_recoverable_jobs():
            if job["status"] == JobStatus.RUNNING.value:
                self._remove_turn_dir(job)
                job = self.storage.reset_running_job_for_recovery(job["id"])
            recovered_job_ids.append(job["id"])
        return recovered_job_ids

    def _remove_turn_dir(self, job: dict[str, Any]) -> None:
        turn_dir = self.settings.sessions_dir / job["session_id"] / job["turn_id"]
        if turn_dir.exists():
            shutil.rmtree(turn_dir)

    def _worker_loop(self) -> None:
        while self._worker_running:
            job_id = self._queue.get()
            if job_id is None:
                break
            try:
                self._process_job(job_id)
            finally:
                self._queue.task_done()

    def _publish_phase(
        self,
        job_id: str,
        *,
        status: str,
        phase: str,
        error: str | None = None,
        result_payload: dict[str, Any] | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> dict[str, Any]:
        self.storage.update_job(
            job_id,
            status=status,
            phase=phase,
            error=error,
            result_payload=result_payload,
            started_at=started_at,
            finished_at=finished_at,
        )
        snapshot = self.get_job_snapshot(job_id)
        self.events.publish(job_id, snapshot)
        return snapshot

    def _process_job(self, job_id: str) -> None:
        job = self.storage.get_job(job_id)
        if not job:
            return
        request_payload = json.loads(job["request_payload"] or "{}")
        session_id = job["session_id"]
        turn_id = job["turn_id"]
        turn_dir = self.settings.sessions_dir / session_id / turn_id
        turn_dir.mkdir(parents=True, exist_ok=True)
        input_audio_path: Path | None = None
        transcript = ""
        final_user_text = ""
        reply_text = ""
        metadata: dict[str, Any] = {
            "providers": {
                "recognizer": self.recognizer.name,
                "dialogue": self.primary_dialogue_engine.name,
                "tts": self.synthesizer.name,
            }
        }

        try:
            self._publish_phase(
                job_id,
                status=JobStatus.RUNNING.value,
                phase=JobPhase.INGEST.value,
                started_at=utc_now(),
            )
            text_input = (request_payload.get("text_input") or "").strip()
            upload_id = request_payload.get("upload_artifact_id")
            if upload_id:
                upload_artifact = self.storage.get_artifact(upload_id)
                if not upload_artifact:
                    raise ValueError(f"Unknown upload artifact: {upload_id}")
                source_path = self.settings.workspace_dir / upload_artifact["relative_path"]
                if not source_path.exists():
                    raise FileNotFoundError(f"Uploaded file does not exist: {source_path}")
                source_suffix = source_path.suffix or ".bin"
                copied_input_path = turn_dir / f"input_source{source_suffix}"
                shutil.copy2(source_path, copied_input_path)
                self.storage.add_artifact(
                    session_id=session_id,
                    turn_id=turn_id,
                    job_id=job_id,
                    kind="input_audio",
                    label=copied_input_path.name,
                    relative_path=self._relative_to_workspace(copied_input_path),
                    media_type=upload_artifact["media_type"],
                    metadata={"source_upload_artifact_id": upload_id},
                )
                input_audio_path = self._prepare_audio_input(
                    copied_input_path,
                    upload_artifact["media_type"],
                    turn_dir,
                )
                if input_audio_path != copied_input_path:
                    self.storage.add_artifact(
                        session_id=session_id,
                        turn_id=turn_id,
                        job_id=job_id,
                        kind="converted_audio",
                        label=input_audio_path.name,
                        relative_path=self._relative_to_workspace(input_audio_path),
                        media_type="audio/wav",
                        metadata={
                            "source_upload_artifact_id": upload_id,
                            "source_media_type": upload_artifact["media_type"],
                        },
                    )

            if input_audio_path is not None:
                self._publish_phase(
                    job_id, status=JobStatus.RUNNING.value, phase=JobPhase.PREPROCESS.value
                )
                preprocessed_wav = turn_dir / "preprocessed.wav"
                preprocess_summary = preprocess_audio(input_audio_path, preprocessed_wav)
                preprocess_summary_dict = json.loads(preprocess_summary.to_json())
                self._write_json(turn_dir / "preprocess_summary.json", preprocess_summary_dict)
                self.storage.add_artifact(
                    session_id=session_id,
                    turn_id=turn_id,
                    job_id=job_id,
                    kind="preprocessed_audio",
                    label="preprocessed.wav",
                    relative_path=self._relative_to_workspace(preprocessed_wav),
                    media_type="audio/wav",
                    metadata=preprocess_summary_dict,
                )
                self.storage.add_artifact(
                    session_id=session_id,
                    turn_id=turn_id,
                    job_id=job_id,
                    kind="preprocess_summary",
                    label="preprocess_summary.json",
                    relative_path=self._relative_to_workspace(turn_dir / "preprocess_summary.json"),
                    media_type="application/json",
                    metadata=preprocess_summary_dict,
                )

                if self.settings.generate_feature_artifacts:
                    from .features import extract_feature_bundle, save_feature_bundle

                    feature_bundle, feature_summary = extract_feature_bundle(preprocessed_wav)
                    save_feature_bundle(turn_dir / "features", feature_bundle, feature_summary)
                    self.storage.add_artifact(
                        session_id=session_id,
                        turn_id=turn_id,
                        job_id=job_id,
                        kind="feature_summary",
                        label="feature_summary.json",
                        relative_path=self._relative_to_workspace(
                            turn_dir / "features" / "feature_summary.json"
                        ),
                        media_type="application/json",
                        metadata=feature_summary,
                    )

                self._publish_phase(
                    job_id, status=JobStatus.RUNNING.value, phase=JobPhase.ASR.value
                )
                recognition = self.recognizer.recognize(preprocessed_wav)
                transcript = recognition.transcript
                self._write_json(turn_dir / "asr_result.json", recognition.payload)
                self.storage.add_artifact(
                    session_id=session_id,
                    turn_id=turn_id,
                    job_id=job_id,
                    kind="asr_result",
                    label="asr_result.json",
                    relative_path=self._relative_to_workspace(turn_dir / "asr_result.json"),
                    media_type="application/json",
                    metadata={
                        "transcript": recognition.transcript,
                        "raw_transcript": recognition.raw_transcript,
                        "corrections": recognition.corrections,
                    },
                )
                metadata["recognition"] = recognition.payload

            final_user_text = " ".join(
                part for part in [transcript.strip(), text_input] if part
            ).strip()
            if not final_user_text:
                raise ValueError("No usable input text or transcript was produced.")
            self.storage.add_message(session_id, turn_id, "user", final_user_text)
            self.storage.update_turn(
                turn_id,
                user_text=final_user_text,
                transcript=transcript or None,
                status=JobStatus.RUNNING.value,
            )

            self._publish_phase(
                job_id, status=JobStatus.RUNNING.value, phase=JobPhase.DIALOGUE.value
            )
            dialogue_history = self.storage.list_messages(session_id)
            dialogue_result = self._generate_reply(dialogue_history, final_user_text)
            reply_text = dialogue_result.assistant_text
            metadata["dialogue"] = dialogue_result.metadata
            metadata["dialogue"]["provider"] = dialogue_result.provider_name
            self._write_json(
                turn_dir / "assistant_response.json",
                {
                    "user_text": final_user_text,
                    "assistant_text": reply_text,
                    "metadata": metadata["dialogue"],
                },
            )
            self.storage.add_artifact(
                session_id=session_id,
                turn_id=turn_id,
                job_id=job_id,
                kind="assistant_response",
                label="assistant_response.json",
                relative_path=self._relative_to_workspace(turn_dir / "assistant_response.json"),
                media_type="application/json",
                metadata=metadata["dialogue"],
            )

            synthesized_artifact = None
            if request_payload.get("use_tts", True) and self.settings.enable_tts:
                self._publish_phase(
                    job_id, status=JobStatus.RUNNING.value, phase=JobPhase.TTS.value
                )
                try:
                    synthesis = self.synthesizer.synthesize(
                        reply_text, turn_dir / "assistant_response.wav"
                    )
                    synthesized_artifact = self.storage.add_artifact(
                        session_id=session_id,
                        turn_id=turn_id,
                        job_id=job_id,
                        kind="assistant_audio",
                        label=synthesis.output_path.name,
                        relative_path=self._relative_to_workspace(synthesis.output_path),
                        media_type=synthesis.media_type,
                        metadata={"provider": synthesis.provider_name},
                    )
                    if self.settings.play_assistant_audio_on_server:
                        metadata["server_audio_playback"] = self._play_audio_on_server(
                            synthesis.output_path
                        )
                except ProviderUnavailableError as exc:
                    metadata["tts_warning"] = str(exc)
                except RuntimeError as exc:
                    metadata["tts_warning"] = str(exc)

            self._publish_phase(
                job_id, status=JobStatus.RUNNING.value, phase=JobPhase.PERSIST.value
            )
            self.storage.add_message(session_id, turn_id, "assistant", reply_text)
            result_payload = {
                "user_text": final_user_text,
                "transcript": transcript,
                "assistant_text": reply_text,
                "assistant_audio_artifact_id": synthesized_artifact["id"]
                if synthesized_artifact
                else None,
                "metadata": metadata,
            }
            self.storage.update_turn(
                turn_id,
                user_text=final_user_text,
                transcript=transcript or None,
                assistant_text=reply_text,
                status=JobStatus.COMPLETED.value,
            )
            self._publish_phase(
                job_id,
                status=JobStatus.COMPLETED.value,
                phase=JobPhase.COMPLETED.value,
                result_payload=result_payload,
                finished_at=utc_now(),
            )
        except Exception as exc:
            traceback_payload = {"error": str(exc), "traceback": traceback.format_exc()}
            self.storage.update_turn(
                turn_id,
                user_text=final_user_text or None,
                transcript=transcript or None,
                assistant_text=reply_text or None,
                status=JobStatus.FAILED.value,
                error=str(exc),
            )
            self._publish_phase(
                job_id,
                status=JobStatus.FAILED.value,
                phase=JobPhase.FAILED.value,
                error=str(exc),
                result_payload=traceback_payload,
                finished_at=utc_now(),
            )

    def _generate_reply(self, history: list[dict], user_text: str):
        try:
            return self.primary_dialogue_engine.generate_reply(history, user_text)
        except ProviderUnavailableError as exc:
            fallback = self.fallback_dialogue_engine.generate_reply(history, user_text)
            fallback.metadata["fallback_reason"] = str(exc)
            fallback.metadata["fallback_provider"] = self.fallback_dialogue_engine.name
            return fallback

    def _prepare_audio_input(
        self,
        source_path: Path,
        media_type: str | None,
        turn_dir: Path,
    ) -> Path:
        normalized_media_type = (media_type or "").lower()
        is_wav = source_path.suffix.lower() == ".wav" or normalized_media_type in {
            "audio/wav",
            "audio/x-wav",
            "audio/wave",
            "audio/vnd.wave",
        }
        if is_wav:
            return source_path

        ffmpeg_binary = shutil.which("ffmpeg")
        if not ffmpeg_binary:
            raise RuntimeError("ffmpeg is required to convert browser-recorded audio into WAV.")

        converted_path = turn_dir / "input.wav"
        subprocess.run(
            [
                ffmpeg_binary,
                "-y",
                "-i",
                str(source_path),
                "-vn",
                "-acodec",
                "pcm_s16le",
                "-ac",
                "1",
                "-ar",
                "16000",
                str(converted_path),
            ],
            check=True,
            capture_output=True,
        )
        return converted_path

    def _detect_recording_device(self) -> str:
        try:
            completed = subprocess.run(
                ["arecord", "-l"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("arecord is required for Raspberry Pi recording.") from exc
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("No usable Raspberry Pi recording device was detected.") from exc

        for line in completed.stdout.splitlines():
            match = re.match(r"^card\s+(\d+):.*device\s+(\d+):", line.strip())
            if match:
                return f"plughw:{match.group(1)},{match.group(2)}"
        raise RuntimeError("No usable Raspberry Pi recording device was detected.")

    def _play_audio_on_server(self, audio_path: Path) -> dict[str, Any]:
        player = shutil.which(self.settings.audio_player_binary)
        if not player:
            raise RuntimeError(
                f"Audio player is not available: {self.settings.audio_player_binary}"
            )
        playback_path = self._prepare_server_playback_audio(audio_path, player)
        player_args = shlex.split(self.settings.audio_player_args)
        command = [player, *player_args, str(playback_path)]
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=180,
            )
            return {
                "player": self.settings.audio_player_binary,
                "args": player_args,
                "path": self._relative_to_workspace(audio_path),
                "playback_path": self._relative_to_workspace(playback_path),
            }
        except OSError as exc:
            raise RuntimeError(f"Server audio playback failed: {exc}") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            raise RuntimeError(f"Server audio playback failed: {detail}") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Server audio playback timed out.") from exc

    def _prepare_server_playback_audio(self, audio_path: Path, player: str) -> Path:
        if Path(player).name != "aplay":
            return audio_path

        ffmpeg_binary = shutil.which("ffmpeg")
        if not ffmpeg_binary:
            raise RuntimeError("ffmpeg is required to convert TTS audio for aplay.")

        playback_path = audio_path.with_name(f"{audio_path.stem}.playback.wav")
        try:
            subprocess.run(
                [
                    ffmpeg_binary,
                    "-y",
                    "-i",
                    str(audio_path),
                    "-vn",
                    "-acodec",
                    "pcm_s16le",
                    "-ac",
                    "2",
                    "-ar",
                    "48000",
                    str(playback_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            raise RuntimeError(f"Server audio conversion failed: {detail}") from exc
        return playback_path

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _relative_to_workspace(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.settings.workspace_dir))

    def _new_id(self) -> str:
        import uuid

        return uuid.uuid4().hex
