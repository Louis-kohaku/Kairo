"""Subtitles, background music, and laying everything onto the timeline.

The subtitle pass here is deliberately *not* the Whisper transcription path
(`subtitle_service.py`). Transcribing speech Kairo itself wrote and timed
would be slower, less accurate, and would throw away the writer's actual
caption - the short, punchy `subtitle_text` that section 25 asks for. So
cues are composed from the scene design, with exact timings, and Whisper
stays for its real job: captioning footage nobody has a script for.

Assembly then reuses `timeline_service` for every mutation rather than
inserting Clip rows directly, so ordering, trim validation and renumbering
behave identically whether a clip was placed by the AI or dragged in by
hand.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from app.core.paths import assets_dir
from app.models.media_asset import MediaAsset
from app.models.production import Scene
from app.models.project import Project
from app.models.subtitle import SubtitleCue
from app.models.timeline import Clip, Track
from app.services import timeline_service
from app.services.ffmpeg import compose
from app.services.ffmpeg.probe import probe_media
from app.services.srt import build_srt

logger = logging.getLogger(__name__)

# Short-form captions are read at a glance on a phone. Past roughly this
# many characters a line stops being glanceable, so it is wrapped; past two
# lines it is truncated rather than allowed to cover the frame.
MAX_CHARS_PER_LINE = 14
MAX_LINES = 2
MIN_CUE_SECONDS = 0.8
# Held a beat shorter than the scene so the caption clears before the cut,
# which stops text appearing to bleed across a scene change.
CUE_TAIL_GAP = 0.12


def caption_budget(project, settings) -> int:
    """Characters per caption line for this project's frame and font size.

    Derived rather than fixed: the readable line length is a function of
    the frame width and the subtitle size the user chose, and those are
    exactly the two things a constant cannot know.
    """
    from app.services import subtitle_style

    return subtitle_style.max_chars_per_line(settings.subtitle, project.width, project.height)


def wrap_caption(text: str, max_chars: int = MAX_CHARS_PER_LINE) -> str:
    """Breaks a caption into at most two readable lines.

    Japanese has no spaces to wrap on, so this breaks on character count,
    preferring a natural punctuation boundary when one is close to the
    limit.
    """
    text = " ".join((text or "").split())
    if not text:
        return ""
    if len(text) <= max_chars:
        return text

    breakpoints = "、。！？!?,. 　"
    lines: list[str] = []
    remaining = text
    while remaining and len(lines) < MAX_LINES:
        if len(remaining) <= max_chars:
            lines.append(remaining)
            remaining = ""
            break
        window = remaining[: max_chars + 2]
        cut = max((window.rfind(ch) for ch in breakpoints), default=-1)
        if cut < max_chars * 0.5:
            cut = max_chars
        else:
            cut += 1
        lines.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()

    if remaining:
        # Out of lines with text left: an ellipsis is honest about the trim.
        lines[-1] = lines[-1][: max_chars - 1] + "…"
    return "\n".join(lines)


def compose_cues(
    db, project_id: str, scenes: list[Scene], max_chars: int | None = None
) -> list[SubtitleCue]:
    """Rebuilds the project's subtitle track from the scene design.

    `max_chars` should come from `caption_budget()` so line breaks match
    the size the captions will actually be burned at; it falls back to the
    default budget for callers that have no project to hand.
    """
    limit = max_chars or MAX_CHARS_PER_LINE
    db.query(SubtitleCue).filter(SubtitleCue.project_id == project_id).delete()
    db.flush()

    cursor = 0.0
    order = 0
    created: list[SubtitleCue] = []
    for scene in scenes:
        duration = max(0.2, float(scene.estimated_duration))
        text = wrap_caption(scene.subtitle_text or scene.narration or "", limit)
        if text:
            end = cursor + max(MIN_CUE_SECONDS, duration - CUE_TAIL_GAP)
            cue = SubtitleCue(
                project_id=project_id,
                order_index=order,
                start=round(cursor, 3),
                end=round(min(end, cursor + duration), 3),
                text=text,
            )
            db.add(cue)
            created.append(cue)
            order += 1
        cursor += duration

    db.commit()
    return created


def write_srt(project_id: str, cues: list[SubtitleCue]) -> Path:
    from app.core.paths import project_dir

    path = project_dir(project_id) / "subtitles" / "generated.srt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_srt(cues), encoding="utf-8")
    return path


# ------------------------------------------------------------------ BGM


def build_bgm(db, project: Project, duration: float, mood: str) -> MediaAsset | None:
    """Synthesises a background bed for the whole video and registers it.

    Generated rather than sourced: it keeps Kairo download-free and means
    every produced video is licence-clean by construction. A user who wants
    real music imports it and the AI-generated bed is replaced.
    """
    if duration <= 0.5:
        return None
    name = f"bgm_{uuid.uuid4().hex[:8]}.m4a"
    dest = assets_dir(project.id) / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        compose.synthesize_bgm(dest, duration + 1.0, mood=mood)
    except Exception:
        logger.exception("BGM synthesis failed for project %s", project.id)
        return None

    try:
        info = probe_media(dest)
    except Exception:
        logger.exception("Could not probe generated BGM")
        return None

    asset = MediaAsset(
        project_id=project.id,
        kind="audio",
        original_filename=f"AI生成BGM_{mood}.m4a",
        stored_path=f"assets/{name}",
        duration=info.duration,
        has_audio=True,
        audio_codec=info.audio_codec,
        origin="kairo_bgm",
        analysis_status="skipped",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


# ------------------------------------------------------------- timeline


def _track(db, project_id: str, kind: str) -> Track | None:
    return (
        db.query(Track)
        .filter(Track.project_id == project_id, Track.type == kind)
        .order_by(Track.order_index)
        .first()
    )


def clear_track(db, track: Track | None) -> None:
    if track is None:
        return
    for clip in list(db.query(Clip).filter(Clip.track_id == track.id).all()):
        db.delete(clip)
    db.commit()


def assemble(db, project: Project, scenes: list[Scene], bgm_asset: MediaAsset | None) -> float:
    """Lays every scene's clip onto the video track in order, and the BGM
    onto the audio track. Returns the assembled duration."""
    video_track = _track(db, project.id, "video")
    audio_track = _track(db, project.id, "audio")
    if video_track is None:
        raise RuntimeError("映像トラックが見つかりません")

    clear_track(db, video_track)

    total = 0.0
    for scene in scenes:
        if not scene.media_asset_id:
            continue
        asset = db.get(MediaAsset, scene.media_asset_id)
        if asset is None:
            continue
        # The clip file is authoritative about its own length; using the
        # planned duration here would drift against the encoded material.
        out_point = asset.duration
        timeline_service.add_clip(db, video_track.id, asset.id, 0.0, out_point, 1.0, None)
        total += out_point

    if audio_track is not None:
        clear_track(db, audio_track)
        if bgm_asset is not None:
            timeline_service.add_clip(
                db,
                audio_track.id,
                bgm_asset.id,
                0.0,
                min(bgm_asset.duration, max(0.5, total)),
                1.0,
                None,
            )

    return total
