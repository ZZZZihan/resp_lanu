from __future__ import annotations

import sys
from pathlib import Path


def add_repo_root(script_file: str) -> Path:
    root_dir = Path(script_file).resolve().parents[1]
    src_dir = root_dir / "src"
    for candidate in (src_dir, root_dir):
        candidate_str = str(candidate)
        if candidate_str not in sys.path:
            sys.path.insert(0, candidate_str)
    return root_dir
