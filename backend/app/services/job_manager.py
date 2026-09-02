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
from app.services import (
    ai_edit_service,
    ai_recommendation_service,
    production_service,
    render_service,
    settings_service,
    subtitle_service,
    video_generation_service,
)

_background_tasks: set[asyncio.Task] = set()

# Guards how many jobs actually run their (blocking, CPU/GPU-heavy) work at
# once, sized from settings.generation.parallelism (0 = auto). Recreated
# whenever the desired size changes rather than resized in place - simple,
# and fine at this app's scale (a single user, occasional jobs) even though
# a job already waiting on the old semaphore when it's swapped keeps
# waiting on that one until it's released.
_semaphore_size: int | None = None
_semaphore: asyncio.Semaphore | None = None


def _resolve_parallelism(value: int) -> int:
    if value <= 0:
        return ai_recommendation_service.recommended_parallelism()
    return max(1, min(value, 8))


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore_size, _semaphore
    size = _resolve_parallelism(settings_service.get_settings().generation.parallelism)
    if _semaphore is None or _semaphore_size != size:
        _semaphore_size = size
        _semaphore = asyncio.Semaphore(size)
    return _semaphore


def _enqueue(db: Session, project_id: str, job_type: str, target) -> Job:
    job = Job(project_id=project_id, type=job_type, status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)

    task = asyncio.create_task(_run(target, job.id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return job


def enqueue_render_job(
    db: Session, project_id: str, burn_subtitles: bool = False, crf: int = 18
) -> Job:
    return _enqueue(
        db,
        project_id,
        "render",
        lambda job_id: render_service.run_render(project_id, job_id, burn_subtitles, crf),
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


def enqueue_scene_regenerate_job(db: Session, project_id: str, scene_id: str) -> Job:
    return _enqueue(
        db,
        project_id,
        "scene_regenerate",
        lambda job_id: production_service.run_scene_regenerate(project_id, job_id, scene_id),
    )


def enqueue_image_to_video_job(db: Session, project_id: str, generation_id: str) -> Job:
    return _enqueue(
        db,
        project_id,
        "image_to_video",
        lambda job_id: video_generation_service.run_image_to_video(
            project_id, job_id, generation_id
        ),
    )


async def _run(target, job_id: str) -> None:
    async with _get_semaphore():
        await asyncio.to_thread(target, job_id)
