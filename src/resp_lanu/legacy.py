from __future__ import annotations

import shutil
from pathlib import Path

from .storage import Database


def export_legacy_artifacts(
    storage: Database,
    output_dir: str | Path,
    *,
    session_id: str | None = None,
    turn_id: str | None = None,
    workspace_dir: str | Path,
) -> Path:
    workspace_dir = Path(workspace_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if turn_id:
        turn = storage.get_turn(turn_id)
    else:
        turn = storage.latest_completed_turn(session_id=session_id)
    if not turn:
        raise ValueError("No completed turn is available for legacy export.")

    turn_dir = workspace_dir / "data" / "sessions" / turn["session_id"] / turn["id"]
    files_to_copy = [
        ("preprocessed.wav", "preprocessed.wav"),
        ("preprocess_summary.json", "preprocess_summary.json"),
        ("asr_result.json", "asr_result.json"),
        ("assistant_response.json", "assistant_response.json"),
        ("assistant_response.wav", "assistant_response.wav"),
    ]

    for source_name, target_name in files_to_copy:
        source_path = turn_dir / source_name
        if source_path.exists():
            shutil.copy2(source_path, output_dir / target_name)

    features_dir = turn_dir / "features"
    if features_dir.exists():
        shutil.copytree(features_dir, output_dir / "features", dirs_exist_ok=True)

    return output_dir
