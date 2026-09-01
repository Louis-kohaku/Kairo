"""Runs render jobs in the background without blocking API requests.

Phase 1 keeps this intentionally simple: one asyncio task per job, offloaded
to a worker thread since ffmpeg calls are blocking subprocess invocations.
The Job row in SQLite is the source of truth for status/progress, so a
client can always poll GET /jobs/{id} regardless of which process/thread is
actually doing the work.
"""
from __future__ import annotations

import asyncio

from sqlalchemy.orm import Session

from app.models.job import Job
from app.services import ai_edit_service, production_service, render_service, subtitle_service

_background_tasks: set[asyncio.Task] = set()


def _enqueue(db: Session, project_id: str, job_type: str, target) -> Job:
    job = Job(project_id=project_id, type=job_type, status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)

    task = asyncio.create_task(_run(target, job.id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return job


def enqueue_render_job(db: Session, project_id: str, burn_subtitles: bool = False) -> Job:
    return _enqueue(
        db,
        project_id,
        "render",
        lambda job_id: render_service.run_render(project_id, job_id, burn_subtitles),
    )


def enqueue_subtitle_job(db: Session, project_id: str) -> Job:
    return _enqueue(
        db,
        project_id,
        "subtitles",
        lambda job_id: subtitle_service.generate_subtitles(project_id, job_id),
    )


def enqueue_ai_edit_job(db: Session, project_id: str, instruction: str) -> Job:
    return _enqueue(
        db,
        project_id,
        "ai_edit",
        lambda job_id: ai_edit_service.run_ai_edit(project_id, job_id, instruction),
    )


def enqueue_production_job(
    db: Session, project_id: str, instruction: str, target_duration_minutes: float
) -> Job:
    return _enqueue(
        db,
        project_id,
        "produce",
        lambda job_id: production_service.run_production(
            project_id, job_id, instruction, target_duration_minutes
        ),
    )


async def _run(target, job_id: str) -> None:
    await asyncio.to_thread(target, job_id)
