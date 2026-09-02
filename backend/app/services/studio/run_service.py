"""Production run lifecycle: start, pause, resume, stop, inspect.

Thin by design - the work is in `pipeline.py`, the interruption mechanics
are in `control.py`, and the reporting is in `events.py`. What lives here
is the policy around them: only one run at a time per project, what
"resume" means for a run that failed versus one the user paused, and how a
run is presented to the API.
"""
from __future__ import annotations

import json
import logging

from app.models.production import Scene
from app.models.studio import ProductionRun
from app.services.studio import control, events, phases

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("pending", "running", "pausing", "paused")


class RunError(RuntimeError):
    pass


def active_run(db, project_id: str) -> ProductionRun | None:
    return (
        db.query(ProductionRun)
        .filter(
            ProductionRun.project_id == project_id,
            ProductionRun.status.in_(ACTIVE_STATUSES),
        )
        .order_by(ProductionRun.created_at.desc())
        .first()
    )


def latest_run(db, project_id: str) -> ProductionRun | None:
    return (
        db.query(ProductionRun)
        .filter(ProductionRun.project_id == project_id)
        .order_by(ProductionRun.created_at.desc())
        .first()
    )


def create_run(
    db,
    project_id: str,
    *,
    instruction: str,
    target_duration_seconds: float,
    orientation: str = "vertical",
    mode: str = "full_auto",
) -> ProductionRun:
    existing = active_run(db, project_id)
    if existing is not None:
        raise RunError("このプロジェクトでは既に制作が進行中です。")

    run = ProductionRun(
        project_id=project_id,
        mode=mode,
        status="pending",
        phase=phases.PHASE_IDS[0],
        instruction=instruction.strip(),
        target_duration_seconds=max(5.0, target_duration_seconds),
        orientation=orientation,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def pause(db, run: ProductionRun) -> ProductionRun:
    if run.status not in ("running", "pending"):
        raise RunError("実行中の制作のみ一時停止できます。")
    control.request(run.id, "pause")
    run.status = "pausing"
    db.commit()
    events.emit(
        run.id,
        run.project_id,
        phase=run.phase,
        status="info",
        message="一時停止をリクエストしました。現在の処理が区切りに達したら停止します。",
    )
    return run


def resume(db, run: ProductionRun) -> ProductionRun:
    """Continues a run.

    A paused run's thread is still parked at a checkpoint, so it only needs
    the request cleared. A stopped or failed run has no thread left, so it
    is re-queued - and because completed phases are recorded on the row,
    the new pipeline skips straight to where the old one stopped.
    """
    if run.status == "paused":
        control.request(run.id, "resume")
        run.status = "running"
        db.commit()
        events.emit(
            run.id,
            run.project_id,
            phase=run.phase,
            message=f"{phases.label(run.phase)}から再開します",
        )
        return run

    if run.status in ("stopped", "failed"):
        from app.services import job_manager

        control.clear(run.id)
        run.status = "pending"
        run.error = None
        run.error_detail = None
        db.commit()
        resume_from = run.resume_phase or run.phase
        events.emit(
            run.id,
            run.project_id,
            phase=resume_from,
            message=f"{phases.label(resume_from)}から再開します",
            reason="完了済みの工程はやり直しません",
        )
        job_manager.enqueue_studio_run(run.id)
        return run

    raise RunError("この状態の制作は再開できません。")


def stop(db, run: ProductionRun) -> ProductionRun:
    control.request(run.id, "stop")
    if run.status in ("pending",):
        # Never started: nothing is parked at a checkpoint to notice.
        run.status = "stopped"
        run.resume_phase = run.phase
        db.commit()
    return run


def to_dict(db, run: ProductionRun | None) -> dict | None:
    if run is None:
        return None
    completed = [p for p in (run.completed_phases or "").split(",") if p]
    scene_count = (
        db.query(Scene).filter(Scene.project_id == run.project_id).count()
    )
    return {
        "id": run.id,
        "project_id": run.project_id,
        "mode": run.mode,
        "status": run.status,
        "phase": run.phase,
        "phase_label": phases.label(run.phase),
        "task": run.task,
        "progress": run.progress,
        "instruction": run.instruction,
        "target_duration_seconds": run.target_duration_seconds,
        "orientation": run.orientation,
        "completed_phases": completed,
        "resume_phase": run.resume_phase,
        "render_job_id": run.render_job_id,
        "output_path": run.output_path,
        "error": run.error,
        "error_detail": load_json(run.error_detail),
        "research": load_json(run.research_json),
        "strategy": load_json(run.strategy_json),
        "quality": load_json(run.quality_json),
        "improvement": load_json(run.improvement_json),
        "model_plan": load_json(run.model_plan_json),
        "scene_count": scene_count,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }


def load_json(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def phase_list() -> list[dict]:
    return [
        {"id": p.id, "label": p.label, "purpose": p.purpose, "skippable": p.skippable}
        for p in phases.PHASES
    ]
