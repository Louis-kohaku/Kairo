"""Per-job event logs (design doc section 8: "制作ログ"), one plain-text
file per job under the project's logs dir. `render_service.py` already
wrote its own version of this pattern (accumulate `log_lines`, flush once
in `finally`); this factors it out so every job type can use the same
storage/retrieval, and so it's retrievable via an API endpoint instead of
only living on disk.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.core.paths import logs_dir


def log_path(project_id: str, job_type: str, job_id: str) -> Path:
    return logs_dir(project_id) / f"{job_type}_{job_id}.log"


def timestamp_line(message: str) -> str:
    return f"[{datetime.now().strftime('%H:%M:%S')}] {message}"


def write_log(project_id: str, job_type: str, job_id: str, lines: list[str]) -> None:
    path = log_path(project_id, job_type, job_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
    except OSError:
        pass


def read_log(project_id: str, job_type: str, job_id: str) -> str | None:
    path = log_path(project_id, job_type, job_id)
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None
