"""The production event system (design doc section 8).

Every stage reports what it is doing through `emit()`. Nothing in the
pipeline writes progress text straight onto the Job row any more, because
a single `message` string could never answer the five questions section 4
demands at once - which phase, which task, on what, why, and what's next.

Events are append-only rows plus an in-process notification, so:

* the UI polls `since()` and gets exactly the events it hasn't seen;
* a browser reload replays the whole run from the database;
* Full Auto and AI Co-Creation share one reporting vocabulary, which is
  what lets the same progress components render both.

Deliberately *not* a Chain-of-Thought stream (section 7): an event says
what Kairo is doing, never what the model is thinking.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Optional

from app.core.db import SessionLocal
from app.models.studio import ProductionEvent, ProductionRun
from app.services.studio import phases

logger = logging.getLogger(__name__)

# Guards seq allocation. Runs execute on worker threads and a single run is
# sequential, but several runs (or a co-creation apply alongside a run) can
# emit concurrently, and the UI relies on seq being strictly increasing per
# run to poll without gaps.
_seq_lock = threading.Lock()
_seq_counters: dict[str, int] = {}

# Woken on every emit so a waiting long-poll returns immediately instead of
# sleeping out its full interval.
_wakeup = threading.Condition()


def _next_seq(db, run_id: str) -> int:
    with _seq_lock:
        current = _seq_counters.get(run_id)
        if current is None:
            row = (
                db.query(ProductionEvent.seq)
                .filter(ProductionEvent.run_id == run_id)
                .order_by(ProductionEvent.seq.desc())
                .first()
            )
            current = row[0] if row else 0
        current += 1
        _seq_counters[run_id] = current
        return current


def emit(
    run_id: str,
    project_id: str,
    *,
    phase: str,
    task: str = "",
    status: str = "running",
    level: str = "user",
    scene_id: Optional[str] = None,
    target: str = "",
    message: str = "",
    reason: str = "",
    next_task: str = "",
    within_phase: float = 0.0,
    model: str = "",
    error: Optional[dict] = None,
    db=None,
) -> ProductionEvent | None:
    """Records one production event and mirrors the run's headline state.

    `db` may be an existing session (the orchestrator passes its own so the
    write joins the surrounding transaction); otherwise a short-lived one
    is opened and closed here.
    """
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        progress = phases.overall_progress(phase, within_phase)
        event = ProductionEvent(
            run_id=run_id,
            project_id=project_id,
            seq=_next_seq(db, run_id),
            phase=phase,
            task=task,
            status=status,
            level=level,
            scene_id=scene_id,
            target=target,
            message=message,
            reason=reason,
            next_task=next_task,
            progress=progress,
            model=model,
            error_json=json.dumps(error, ensure_ascii=False) if error else None,
        )
        db.add(event)

        # The run row carries the "where are we right now" snapshot so a
        # client that just connected can render the current state without
        # replaying the whole event list first.
        run = db.get(ProductionRun, run_id)
        if run is not None and level == "user":
            run.phase = phase
            run.task = task or run.task
            run.progress = progress
        db.commit()

        with _wakeup:
            _wakeup.notify_all()
        return event
    except Exception:
        # Reporting must never be the thing that fails a production run.
        logger.exception("Failed to emit production event for run %s", run_id)
        try:
            db.rollback()
        except Exception:
            pass
        return None
    finally:
        if own_session:
            db.close()


def since(run_id: str, after_seq: int = 0, limit: int = 500) -> list[ProductionEvent]:
    db = SessionLocal()
    try:
        return (
            db.query(ProductionEvent)
            .filter(ProductionEvent.run_id == run_id, ProductionEvent.seq > after_seq)
            .order_by(ProductionEvent.seq)
            .limit(limit)
            .all()
        )
    finally:
        db.close()


def wait_for_new(run_id: str, after_seq: int, timeout: float = 20.0) -> list[ProductionEvent]:
    """Long-poll helper: returns as soon as there is anything newer than
    `after_seq`, or an empty list once `timeout` elapses. Keeps the
    progress UI live without a per-second polling loop."""
    existing = since(run_id, after_seq)
    if existing:
        return existing
    with _wakeup:
        _wakeup.wait(timeout)
    return since(run_id, after_seq)


def to_dict(event: ProductionEvent) -> dict:
    return {
        "id": event.id,
        "run_id": event.run_id,
        "seq": event.seq,
        "phase": event.phase,
        "phase_label": phases.label(event.phase),
        "task": event.task,
        "status": event.status,
        "level": event.level,
        "scene_id": event.scene_id,
        "target": event.target,
        "message": event.message,
        "reason": event.reason,
        "next_task": event.next_task,
        "progress": event.progress,
        "model": event.model,
        "error": json.loads(event.error_json) if event.error_json else None,
        "timestamp": event.created_at.isoformat() if event.created_at else None,
    }


def forget(run_id: str) -> None:
    """Drops the cached seq counter for a finished run so long-lived
    processes don't accumulate one entry per run forever."""
    with _seq_lock:
        _seq_counters.pop(run_id, None)
