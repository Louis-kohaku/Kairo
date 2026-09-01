"""Runs an image-to-video generation as a background Job (same pattern as
render_service/subtitle_service), then registers the result as a normal
MediaAsset so it immediately shows up in the Media Bin / Timeline like any
imported clip.
"""
from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path

from app.core.db import SessionLocal
from app.core.paths import assets_dir
from app.models.generation import Generation
from app.models.job import Job
from app.models.media_asset import MediaAsset
from app.services import ai_diagnostics, job_log, video_engines
from app.services.ffmpeg.probe import probe_media

logger = logging.getLogger(__name__)


def _update_job(db, job_id: str, **fields) -> None:
    job = db.get(Job, job_id)
    if job is None:
        return
    for key, value in fields.items():
        setattr(job, key, value)
    db.commit()


def run_image_to_video(project_id: str, job_id: str, generation_id: str) -> None:
    db = SessionLocal()
    log_lines = [job_log.timestamp_line("Image-to-video generation started")]
    engine = None
    try:
        generation = db.get(Generation, generation_id)
        if generation is None:
            raise RuntimeError(f"Generation {generation_id} not found")

        generation.status = "running"
        generation.job_id = job_id
        db.commit()

        _update_job(db, job_id, status="running", progress=1.0, message="開始しています", step="generation")

        engine = video_engines.get_engine(generation.engine_id)
        log_lines.append(job_log.timestamp_line(f"Engine: {engine.capabilities.display_name} ({generation.engine_id})"))
        params = json.loads(generation.params_json or "{}")
        source_image = Path(generation.source_image_path)

        def progress_cb(pct: float, msg: str) -> None:
            _update_job(db, job_id, progress=round(pct, 1), message=msg)

        tmp_output = assets_dir(project_id) / f"_gen_{uuid.uuid4().hex}.mp4"
        result = engine.generate_image_to_video(
            source_image,
            tmp_output,
            prompt=generation.prompt,
            progress_cb=progress_cb,
            **params,
        )

        _update_job(db, job_id, progress=95.0, message="生成結果を取り込み中")

        final_name = f"{uuid.uuid4().hex}.mp4"
        final_path = assets_dir(project_id) / final_name
        shutil.move(str(result.output_path), str(final_path))

        info = probe_media(final_path)
        asset = MediaAsset(
            project_id=project_id,
            kind="video",
            original_filename=f"AI生成_{generation.engine_id}_{generation.id[:8]}.mp4",
            stored_path=f"assets/{final_name}",
            duration=info.duration,
            width=info.width,
            height=info.height,
            fps=info.fps,
            has_audio=info.has_audio,
            video_codec=info.video_codec,
            audio_codec=info.audio_codec,
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)

        generation.status = "completed"
        generation.output_media_asset_id = asset.id
        generation.elapsed_seconds = result.elapsed_seconds
        db.commit()

        _update_job(
            db,
            job_id,
            status="completed",
            progress=100.0,
            message=f"生成完了({result.elapsed_seconds:.0f}秒)",
            output_path=asset.stored_path,
        )
        log_lines.append(job_log.timestamp_line("Generation completed"))
    except Exception as exc:  # noqa: BLE001 - surfaced to the job/generation rows for the UI
        logger.exception("Image-to-video generation job %s failed", job_id)
        db.rollback()

        context = None
        if engine is not None:
            context = ai_diagnostics.AIContext(
                provider=engine.capabilities.display_name,
                model=engine.capabilities.id,
                task="画像→動画生成",
                operation="Local Inference",
                endpoint="local",
                model_status="downloaded" if engine.is_model_downloaded() else "not_downloaded",
            )
        diagnosis = ai_diagnostics.diagnose(exc, context=context, step="generation")
        error_detail = json.dumps(diagnosis.to_dict(), ensure_ascii=False)
        log_lines.append(job_log.timestamp_line(f"ERROR: {diagnosis.summary}"))

        generation = db.get(Generation, generation_id)
        if generation is not None:
            generation.status = "failed"
            generation.error = diagnosis.summary
            generation.error_detail = error_detail
            db.commit()

        _update_job(
            db,
            job_id,
            status="failed",
            error=diagnosis.summary,
            error_detail=error_detail,
            step="generation",
            message=diagnosis.summary,
        )
    finally:
        job_log.write_log(project_id, "image_to_video", job_id, log_lines)
        db.close()
