"""Turns a project's timeline into a single rendered video file via FFmpeg.

Runs synchronously on a worker thread (see job_manager). Every long step
reports incremental progress onto the Job row so the UI can poll it, and
per-clip video segments are cached on disk keyed by (asset, trim, target
format) so re-rendering after a small timeline edit doesn't re-encode
untouched clips.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.core.config import DEFAULT_BGM_VOLUME
from app.core.db import SessionLocal
from app.core.paths import project_dir, renders_dir, tmp_segments_dir
from app.models.job import Job
from app.models.project import Project
from app.models.subtitle import SubtitleCue
from app.models.timeline import Clip, Track
from app.schemas.settings import SubtitleSettings
from app.services import ai_diagnostics, job_log, settings_service, subtitle_style
from app.services.ffmpeg import compose, engine
from app.services.srt import build_srt

logger = logging.getLogger(__name__)


class RenderError(RuntimeError):
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


def _ordered_clips(track: Track | None) -> list[Clip]:
    if track is None:
        return []
    return sorted(track.clips, key=lambda c: c.order_index)


def _segment_cache_path(
    project_id: str, clip: Clip, width: int, height: int, fps: float, crf: int
) -> Path:
    key = (
        f"{clip.media_asset_id}_{clip.in_point:.3f}_{clip.out_point:.3f}"
        f"_{width}x{height}_{fps:.3f}_crf{crf}.mp4"
    )
    return tmp_segments_dir(project_id) / key


def run_render(
    project_id: str,
    job_id: str,
    burn_subtitles: bool = False,
    crf: int = 18,
    subtitle_override: SubtitleSettings | None = None,
    sfx: list[tuple[Path, float]] | None = None,
) -> None:
    """Renders a project's timeline to one MP4.

    `subtitle_override` lets the production agent burn captions in the font
    and style *it* chose for this video without writing those choices into
    the user's global settings - a Settings screen that silently changed
    because a run decided something would stop being a settings screen.
    Manual renders pass nothing and behave exactly as before.

    `sfx` is a list of (file, timestamp) pairs laid over the finished mix.
    """
    db = SessionLocal()
    log_lines: list[str] = []
    current_step = "segment_normalization"
    try:
        app_settings = settings_service.get_settings()
        subtitle_settings = subtitle_override or app_settings.subtitle
        # A global "字幕 OFF" in Settings always wins over the per-render
        # checkbox - it's meant to read as a real on/off switch, not a
        # suggestion.
        burn_subtitles = burn_subtitles and app_settings.subtitle.enabled

        project = db.get(Project, project_id)
        if project is None:
            raise RenderError(f"Project {project_id} not found")

        tracks = {t.type: t for t in project.tracks}
        video_clips = _ordered_clips(tracks.get("video"))
        bgm_clips = _ordered_clips(tracks.get("audio"))

        if not video_clips:
            raise RenderError("Timeline has no video clips to render")

        _update_job(job_id, status="running", progress=1.0, message="Preparing segments", step=current_step)

        work_dir = renders_dir(project_id) / "_work" / job_id
        work_dir.mkdir(parents=True, exist_ok=True)

        # Segment normalization is budgeted as 0-70% of overall progress.
        segment_paths: list[Path] = []
        n = len(video_clips)
        for i, clip in enumerate(video_clips):
            dest = _segment_cache_path(
                project_id, clip, project.width, project.height, project.fps, crf
            )
            if not app_settings.generation.cache_enabled or not dest.exists():
                src_path = project_dir(project_id) / clip.media_asset.stored_path

                def on_progress(frac: float, i=i, n=n) -> None:
                    _update_job(job_id, progress=round((i + frac) / n * 70, 1))

                engine.normalize_segment(
                    src_path,
                    clip.in_point,
                    clip.out_point,
                    project.width,
                    project.height,
                    project.fps,
                    dest,
                    on_progress=on_progress,
                    crf=crf,
                )
                log_lines.append(f"normalized clip {clip.id} -> {dest.name}")
            segment_paths.append(dest)
            _update_job(job_id, progress=round((i + 1) / n * 70, 1), message=f"Segment {i+1}/{n}")

        main_video = work_dir / "main_video.mp4"
        current_step = "concat"
        _update_job(job_id, progress=75.0, message="Concatenating segments", step=current_step)
        engine.concat_files(segment_paths, main_video, work_dir / "filelist.txt")

        final_path = renders_dir(project_id) / f"{job_id}.mp4"
        pre_subtitle_path = work_dir / "pre_subtitle.mp4" if burn_subtitles else final_path

        if bgm_clips:
            current_step = "audio_mix"
            _update_job(job_id, progress=82.0, message="Preparing background music", step=current_step)
            bgm_segment_paths = []
            for j, clip in enumerate(bgm_clips):
                seg = work_dir / f"bgm_seg_{j}.m4a"
                src_path = project_dir(project_id) / clip.media_asset.stored_path
                engine.extract_audio_segment(src_path, clip.in_point, clip.out_point, seg)
                bgm_segment_paths.append(seg)

            bgm_concat = work_dir / "bgm_concat.m4a"
            engine.concat_files(bgm_segment_paths, bgm_concat, work_dir / "bgm_filelist.txt")

            video_duration = sum(c.duration for c in video_clips)
            bgm_fitted = work_dir / "bgm_fitted.m4a"
            engine.loop_or_trim_audio(bgm_concat, video_duration, bgm_fitted)

            _update_job(job_id, progress=90.0, message="Mixing audio")
            # The BGM clip's own volume is the user's (or the AI's) explicit
            # choice - honouring it here is what makes "BGMをもう少し下げて"
            # change the rendered file rather than just a number in the UI.
            bgm_volume = bgm_clips[0].volume * DEFAULT_BGM_VOLUME
            # Ducked against the main audio so music steps back under
            # narration and returns in the gaps (design doc section 26).
            compose.mix_narration_with_bgm(
                main_video,
                bgm_fitted,
                pre_subtitle_path,
                bgm_volume=max(0.0, min(bgm_volume, 1.0)),
                duck=True,
            )
        else:
            main_video.replace(pre_subtitle_path)

        if burn_subtitles:
            current_step = "subtitle_burn"
            cues = (
                db.query(SubtitleCue)
                .filter(SubtitleCue.project_id == project_id)
                .order_by(SubtitleCue.order_index)
                .all()
            )
            if cues:
                _update_job(job_id, progress=94.0, message="Burning in subtitles", step=current_step)
                # Burned from an ASS sized to this exact frame, so the
                # subtitle size in Settings is real output pixels. Handing
                # ffmpeg an SRT instead makes libass rescale against its
                # own conversion resolution, which rendered a "42px"
                # caption at roughly 180px on a 1080x1920 short.
                ass_path = work_dir / "burn.ass"
                ass_path.write_text(
                    subtitle_style.build_ass(
                        cues, subtitle_settings, project.width, project.height
                    ),
                    encoding="utf-8",
                )
                # The .srt stays alongside it: it is what the user can
                # download and load into another editor.
                (work_dir / "burn.srt").write_text(build_srt(cues), encoding="utf-8")
                engine.burn_subtitles(pre_subtitle_path, ass_path, final_path, crf=crf)
            else:
                pre_subtitle_path.replace(final_path)

        if sfx:
            current_step = "sfx_overlay"
            _update_job(job_id, progress=97.0, message="Overlaying sound effects", step=current_step)
            usable = [(Path(path), at) for path, at in sfx if Path(path).exists()]
            if usable:
                # Overlaid last, onto the finished mix, because the effects
                # are positioned against the final timeline - doing it
                # before the concat would mean re-deriving every timestamp
                # per segment.
                with_sfx = work_dir / "with_sfx.mp4"
                try:
                    compose.overlay_sfx(final_path, usable, with_sfx)
                    with_sfx.replace(final_path)
                    log_lines.append(f"overlaid {len(usable)} sfx")
                except Exception as exc:  # noqa: BLE001
                    # An effect that will not mix is not worth losing the
                    # render over; the video without it is still the video.
                    logger.warning("SFX overlay failed, keeping clean mix: %s", exc)
                    log_lines.append(f"sfx overlay skipped: {exc}")

        rel_output = f"renders/{job_id}.mp4"
        _update_job(
            job_id,
            status="completed",
            progress=100.0,
            message="Render complete",
            output_path=rel_output,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the job row for the UI
        logger.exception("Render job %s failed", job_id)
        diagnosis = ai_diagnostics.diagnose(exc, step=current_step)
        log_lines.append(f"ERROR: {diagnosis.summary}")
        _update_job(
            job_id,
            status="failed",
            error=diagnosis.summary,
            error_detail=json.dumps(diagnosis.to_dict(), ensure_ascii=False),
            step=current_step,
            message="Render failed",
        )
    finally:
        job_log.write_log(project_id, "render", job_id, log_lines)
        db.close()
