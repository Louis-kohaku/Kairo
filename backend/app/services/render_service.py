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
from app.services.studio import subtitle_design

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
    project_id: str,
    clip: Clip,
    width: int,
    height: int,
    fps: float,
    crf: int,
    color_key: str = "",
) -> Path:
    """Where a normalised segment is cached.

    The colour grade is part of the key. Without it, changing the look and
    re-rendering would silently reuse the ungraded segments from the
    previous run - the grade would appear to do nothing, which is exactly
    the "setting that does not affect real output" failure mode.
    """
    suffix = ""
    if color_key:
        import hashlib

        suffix = "_c" + hashlib.sha1(color_key.encode("utf-8")).hexdigest()[:8]
    key = (
        f"{clip.media_asset_id}_{clip.in_point:.3f}_{clip.out_point:.3f}"
        f"_{width}x{height}_{fps:.3f}_crf{crf}{suffix}.mp4"
    )
    return tmp_segments_dir(project_id) / key


def _transition_budget(
    plan,
    durations: list[float],
    segment_count: int,
) -> dict[int, float]:
    """How long each boundary's transition may actually be.

    A transition consumes footage: an overlap of D seconds takes D from the
    end of the outgoing shot and D from the start of the incoming one, and
    gives back one D-long clip - so the video gets D shorter per
    transition, exactly as it would in any editor.

    That is only acceptable while both shots can spare the frames. A
    0.8-second cut cannot lend 0.4s to a dissolve without becoming a flash,
    so each boundary's overlap is capped at 40% of either neighbour and
    every shot is guaranteed to keep at least MIN_SHOT_SECONDS of itself.
    Boundaries that cannot afford one keep their cut, which is a correct
    edit rather than a degraded one.
    """
    MIN_SHOT_SECONDS = 0.4
    choices = plan.by_index()
    budget: dict[int, float] = {}
    # Running total of what each segment has already given up, so a clip
    # between two transitions is never trimmed past its own length.
    consumed = [0.0] * segment_count

    wanted = sorted(
        (
            (i, c)
            for i, c in choices.items()
            if c.transition != "cut" and engine.supports_transition(c.transition)
        ),
        key=lambda item: item[0],
    )
    for index, choice in wanted:
        if index <= 0 or index >= segment_count:
            continue
        before = float(durations[index - 1]) if index - 1 < len(durations) else 0.0
        after = float(durations[index]) if index < len(durations) else 0.0
        left = before - consumed[index - 1] - MIN_SHOT_SECONDS
        right = after - consumed[index] - MIN_SHOT_SECONDS
        allowed = min(
            float(choice.duration),
            max(0.0, left),
            max(0.0, right),
            before * 0.4,
            after * 0.4,
        )
        if allowed < 0.1:
            logger.info(
                "Boundary %s cannot afford a transition (%.2fs available); keeping the cut",
                index,
                max(0.0, min(left, right)),
            )
            continue
        budget[index] = round(allowed, 3)
        consumed[index - 1] += allowed
        consumed[index] += allowed
    return budget


def _apply_transitions(
    segment_paths: list[Path],
    plan,
    work_dir: Path,
    *,
    width: int,
    height: int,
    fps: float,
    crf: int,
    durations: list[float],
) -> tuple[list[Path], int]:
    """Rebuilds the segment list with transition clips spliced in.

    Each affordable boundary becomes three files where there were two: the
    outgoing clip minus its last D seconds, a D-second rendered transition,
    and the incoming clip minus its first D seconds. Every file is encoded
    to the same codec, resolution and frame rate as the ordinary segments,
    so the concat demuxer's stream copy - and the segment caching built
    around it - keeps working exactly as before.

    Returns (paths, transitions actually applied). A transition that fails
    to render is dropped and the boundary stays a cut: an effect is never
    worth losing the video over.
    """
    choices = plan.by_index()
    budget = _transition_budget(plan, durations, len(segment_paths))
    if not budget:
        return segment_paths, 0

    # What each segment loses at each end, from the budget above.
    trim_head = [0.0] * len(segment_paths)
    trim_tail = [0.0] * len(segment_paths)
    for index, seconds in budget.items():
        trim_tail[index - 1] += seconds
        trim_head[index] += seconds

    # --- the transition clips, built from the untrimmed originals -----
    bridges: dict[int, Path] = {}
    for index, seconds in sorted(budget.items()):
        previous_duration = (
            float(durations[index - 1]) if index - 1 < len(durations) else 0.0
        )
        tail_clip = work_dir / f"trans_{index:03d}_a.mp4"
        head_clip = work_dir / f"trans_{index:03d}_b.mp4"
        bridge = work_dir / f"trans_{index:03d}.mp4"
        try:
            engine.trim_segment(
                segment_paths[index - 1],
                tail_clip,
                start=max(0.0, previous_duration - seconds),
                duration=seconds,
                width=width,
                height=height,
                fps=fps,
                crf=crf,
            )
            engine.trim_segment(
                segment_paths[index],
                head_clip,
                start=0.0,
                duration=seconds,
                width=width,
                height=height,
                fps=fps,
                crf=crf,
            )
            engine.build_transition(
                tail_clip,
                head_clip,
                bridge,
                transition=choices[index].transition,
                duration=seconds,
                width=width,
                height=height,
                fps=fps,
                crf=crf,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Transition at boundary %s failed, cutting instead: %s", index, exc
            )
            # Give the frames back, so the neighbouring shots are not
            # shortened for a transition that does not exist.
            trim_tail[index - 1] -= seconds
            trim_head[index] -= seconds
            continue
        bridges[index] = bridge

    if not bridges:
        return segment_paths, 0

    # --- the trimmed body clips, then the final order ------------------
    out: list[Path] = []
    for i, path in enumerate(segment_paths):
        if i in bridges:
            out.append(bridges[i])
        head = max(0.0, trim_head[i])
        tail = max(0.0, trim_tail[i])
        own = float(durations[i]) if i < len(durations) else 0.0
        if head > 0.005 or tail > 0.005:
            trimmed = work_dir / f"seg_{i:03d}_trim.mp4"
            engine.trim_segment(
                path,
                trimmed,
                start=head,
                duration=max(0.1, own - head - tail),
                width=width,
                height=height,
                fps=fps,
                crf=crf,
            )
            out.append(trimmed)
        else:
            out.append(path)

    return out, len(bridges)


def run_render(
    project_id: str,
    job_id: str,
    burn_subtitles: bool = False,
    crf: int = 18,
    subtitle_override: SubtitleSettings | None = None,
    sfx: list[tuple[Path, float]] | None = None,
    transitions=None,
    color=None,
    audio=None,
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

        # The colour look, as an ffmpeg filter chain built from typed
        # numbers. Applied per segment (rather than once at the end) so it
        # survives the concat stream copy and lands identically on every
        # shot; empty when no grade was chosen, which is what a manual
        # render does and what the code did before grading existed.
        color_chain = ""
        if color is not None and not color.is_identity():
            color_chain = engine.color_filter(
                brightness=color.brightness,
                contrast=color.contrast,
                saturation=color.saturation,
                gamma=color.gamma,
                shadow_blue=color.shadow_blue,
                highlight_red=color.highlight_red,
            )
            if color_chain:
                log_lines.append(f"color grade {color.id}: {color_chain}")

        # Segment normalization is budgeted as 0-70% of overall progress.
        segment_paths: list[Path] = []
        n = len(video_clips)
        for i, clip in enumerate(video_clips):
            dest = _segment_cache_path(
                project_id,
                clip,
                project.width,
                project.height,
                project.fps,
                crf,
                color_key=color_chain,
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
                    color=color_chain,
                )
                log_lines.append(f"normalized clip {clip.id} -> {dest.name}")
            segment_paths.append(dest)
            _update_job(job_id, progress=round((i + 1) / n * 70, 1), message=f"Segment {i+1}/{n}")

        main_video = work_dir / "main_video.mp4"
        current_step = "concat"
        _update_job(job_id, progress=75.0, message="Concatenating segments", step=current_step)
        if transitions:
            segment_paths, applied = _apply_transitions(
                segment_paths,
                transitions,
                work_dir,
                width=project.width,
                height=project.height,
                fps=project.fps,
                crf=crf,
                durations=[c.duration for c in video_clips],
            )
            if applied:
                log_lines.append(f"applied {applied} transitions")
                _update_job(
                    job_id,
                    progress=78.0,
                    message=f"Building {applied} transitions",
                    step="transitions",
                )
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
                # Per-caption designs, when the agent produced any. A cue
                # with none is written exactly as before, so a manual
                # render and a Whisper transcript are unaffected.
                designs: dict[int, object] = {}
                for index, cue in enumerate(cues):
                    design = subtitle_design.load(cue)
                    if design is not None:
                        designs[index] = design
                if designs:
                    log_lines.append(f"burning {len(designs)} designed captions")
                ass_path.write_text(
                    subtitle_style.build_ass(
                        cues,
                        subtitle_settings,
                        project.width,
                        project.height,
                        designs=designs,
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

        if audio is not None and audio.normalize:
            # The last thing done to the file: every platform normalises
            # playback to about -14 LUFS, so delivering at that level is
            # what stops a music-only video coming out inaudible next to
            # everything else on a phone. Stream-copies the video, so it
            # costs seconds rather than a re-encode.
            current_step = "loudness"
            _update_job(job_id, progress=98.0, message="Normalising loudness", step=current_step)
            normalized = work_dir / "normalized.mp4"
            try:
                engine.normalize_loudness(
                    final_path,
                    normalized,
                    target_lufs=audio.target_lufs,
                    denoise=audio.denoise,
                )
                normalized.replace(final_path)
                log_lines.append(
                    f"loudness normalised to {audio.target_lufs} LUFS"
                    + (" with denoise" if audio.denoise else "")
                )
            except Exception as exc:  # noqa: BLE001
                # A mix that will not normalise is still a finished video.
                logger.warning("Loudness normalisation failed, keeping mix: %s", exc)
                log_lines.append(f"loudness normalisation skipped: {exc}")

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
