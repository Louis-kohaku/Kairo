"""Generates a project-wide subtitle track by transcribing the video
track's clips in order and offsetting each clip's cues onto the shared
timeline axis - the same axis the render pipeline and the UI playhead use.

`generate_cues_for_project` is the reusable core: it does the work and
returns the saved cues without touching any Job row, so both the
standalone "generate subtitles" endpoint and the AI-edit orchestrator (
which may run this as one step among several under a single job) can
drive its progress the same way.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from app.core.db import SessionLocal
from app.core.paths import project_dir, renders_dir
from app.models.job import Job
from app.models.project import Project
from app.models.subtitle import SubtitleCue
from app.services import whisper_service
from app.services.ffmpeg import engine
from app.services.srt import build_srt

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]


class SubtitleGenerationError(RuntimeError):
    pass


def _update_job(job_id: str, **fields) -> None:
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return
        for key, value in fields.items():
            setattr(job, key, value)
        db.commit()
    finally:
        db.close()


def generate_cues_for_project(
    project_id: str, on_progress: Optional[ProgressCallback] = None
) -> list[SubtitleCue]:
    db = SessionLocal()
    try:
        project = db.get(Project, project_id)
        if project is None:
            raise SubtitleGenerationError(f"Project {project_id} not found")

        video_track = next((t for t in project.tracks if t.type == "video"), None)
        clips = sorted(video_track.clips, key=lambda c: c.order_index) if video_track else []
        if not clips:
            raise SubtitleGenerationError("Timeline has no video clips to transcribe")

        if on_progress:
            on_progress(1.0, "音声を抽出中")

        work_dir = renders_dir(project_id) / "_work" / f"subs_{project_id}"
        work_dir.mkdir(parents=True, exist_ok=True)

        all_cues: list[tuple[float, float, str]] = []
        cursor = 0.0
        n = len(clips)

        for i, clip in enumerate(clips):
            src_path = project_dir(project_id) / clip.media_asset.stored_path
            segment_path = work_dir / f"clip_{i}.m4a"
            engine.extract_audio_segment(src_path, clip.in_point, clip.out_point, segment_path)

            if on_progress:
                on_progress(round(10 + i / n * 80, 1), f"文字起こし中 ({i + 1}/{n})")
            segments = whisper_service.transcribe(segment_path)

            clip_duration = clip.duration
            for seg in segments:
                start = cursor + max(0.0, min(seg.start, clip_duration))
                end = cursor + max(0.0, min(seg.end, clip_duration))
                if end > start:
                    all_cues.append((start, end, seg.text))

            cursor += clip_duration

        if on_progress:
            on_progress(92.0, "字幕を保存中")

        existing = db.query(SubtitleCue).filter(SubtitleCue.project_id == project_id).all()
        for cue in existing:
            db.delete(cue)
        db.flush()

        for order, (start, end, text) in enumerate(sorted(all_cues)):
            db.add(
                SubtitleCue(
                    project_id=project_id,
                    order_index=order,
                    start=start,
                    end=end,
                    text=text,
                )
            )
        db.commit()

        cues = (
            db.query(SubtitleCue)
            .filter(SubtitleCue.project_id == project_id)
            .order_by(SubtitleCue.order_index)
            .all()
        )
        srt_path = project_dir(project_id) / "subtitles" / "generated.srt"
        srt_path.parent.mkdir(parents=True, exist_ok=True)
        srt_path.write_text(build_srt(cues), encoding="utf-8")

        return cues
    finally:
        db.close()


def generate_subtitles(project_id: str, job_id: str) -> None:
    try:
        _update_job(job_id, status="running", progress=1.0, message="音声を抽出中")

        def on_progress(pct: float, message: str) -> None:
            _update_job(job_id, progress=pct, message=message)

        cues = generate_cues_for_project(project_id, on_progress)

        _update_job(
            job_id,
            status="completed",
            progress=100.0,
            message=f"{len(cues)}件の字幕を生成しました",
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the job row for the UI
        logger.exception("Subtitle generation job %s failed", job_id)
        _update_job(job_id, status="failed", error=str(exc), message="字幕生成に失敗しました")
