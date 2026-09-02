"""Pause / Stop / Resume for a production run (design doc section 34).

The pipeline is a sequence of blocking steps on a worker thread, so it
cannot be interrupted mid-ffmpeg without corrupting output. Instead every
stage calls `checkpoint()` at its own safe boundaries (between scenes,
between phases). A pause request parks the thread there; a stop request
raises `RunStopped`, which the orchestrator catches to shut down cleanly
with all completed work still on disk and in the database.

That is what makes "Scene 4の素材生成から再開します" true rather than a
message: the run row already records which phases finished, and the
per-scene work is idempotent, so resuming re-enters the pipeline at the
first unfinished phase and skips scenes that already have their material.
"""
from __future__ import annotations

import threading
import time

from app.core.db import SessionLocal
from app.models.studio import ProductionRun

# run_id -> requested transition. Held in memory only: a request is a
# live instruction to a running thread, and a process restart means there
# is no thread left to instruct.
_requests: dict[str, str] = {}
_lock = threading.Lock()


class RunStopped(RuntimeError):
    """Raised inside a run's thread when the user asked it to stop."""


def request(run_id: str, action: str) -> None:
    """action: "pause" | "resume" | "stop"."""
    with _lock:
        if action == "resume":
            _requests.pop(run_id, None)
        else:
            _requests[run_id] = action


def peek(run_id: str) -> str | None:
    with _lock:
        return _requests.get(run_id)


def clear(run_id: str) -> None:
    with _lock:
        _requests.pop(run_id, None)


def _set_status(run_id: str, status: str) -> None:
    db = SessionLocal()
    try:
        run = db.get(ProductionRun, run_id)
        if run is not None:
            run.status = status
            db.commit()
    finally:
        db.close()


def checkpoint(run_id: str) -> None:
    """Safe point for the pipeline to honour a pause/stop request.

    Blocks (parked, sleeping) while paused, and raises RunStopped if the
    user chose to stop. Called between scenes and between phases, never in
    the middle of an encode.
    """
    action = peek(run_id)
    if action is None:
        return

    if action == "stop":
        clear(run_id)
        _set_status(run_id, "stopped")
        raise RunStopped("ユーザーの操作により制作を停止しました")

    if action == "pause":
        _set_status(run_id, "paused")
        while True:
            time.sleep(0.4)
            action = peek(run_id)
            if action is None:  # resumed
                _set_status(run_id, "running")
                return
            if action == "stop":
                clear(run_id)
                _set_status(run_id, "stopped")
                raise RunStopped("ユーザーの操作により制作を停止しました")
