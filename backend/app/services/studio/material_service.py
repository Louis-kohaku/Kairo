"""Turning a designed scene into actual material on disk.

Three stages live here, in the order the pipeline runs them:

1. `render_scene_visual` - the scene's key visual. A clip the user supplied
   wins outright (section 24); otherwise a downloaded diffusion engine is
   used if there is one, and otherwise Kairo composes the frame itself
   (`image_engines.procedural`), which is what makes "素材ゼロでも完成
   する" true rather than aspirational.

2. `synthesize_narration` - speech for the scene, then `retime_from_narration`,
   which is the point of doing this before assembly: a scene whose planned
   3.0s holds 4.4s of speech would otherwise cut the sentence in half. The
   *measured* audio length sets the floor for the scene's duration.

3. `build_scene_clip` - image (or footage) + narration + SFX -> one real
   video file, registered as an ordinary MediaAsset. From that point on the
   timeline, the preview, the render pipeline and the manual editor treat
   AI-produced material exactly like an imported file, which is why none of
   them needed changing.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from app.core.paths import assets_dir, project_dir
from app.models.media_asset import MediaAsset
from app.models.production import Scene
from app.models.project import Project
from app.schemas.studio import ProductionStrategy
from app.services import image_engines, tts_service
from app.services.ffmpeg import compose
from app.services.ffmpeg.probe import probe_media
from app.services.image_engines.procedural import SceneVisualSpec, resolve_camera

logger = logging.getLogger(__name__)

# A scene needs a beat of air after the narration ends, or the cut lands on
# the final syllable and the video feels rushed even at the right length.
NARRATION_TAIL_PADDING = 0.45
NARRATION_LEAD_IN = 0.15


def scene_visual_dir(project_id: str) -> Path:
    d = project_dir(project_id) / "scenes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def scene_audio_dir(project_id: str) -> Path:
    d = project_dir(project_id) / "audio"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ------------------------------------------------------------- visuals


def render_scene_visual(
    scene: Scene,
    index: int,
    project: Project,
    strategy: ProductionStrategy,
    *,
    engine_id: str = "procedural",
) -> Path:
    """Produces (or reuses) the still that represents this scene."""
    dest = scene_visual_dir(project.id) / f"scene_{index:03d}_{scene.id[:8]}.png"
    spec = SceneVisualSpec(
        index=index,
        visual_type=scene.visual_type,
        visual_prompt=scene.visual_prompt,
        emotion=scene.emotion or "",
        camera=scene.camera or "",
        # Only text-led scenes bake their words into the frame; ordinary
        # captions are burned in by the subtitle pass so they stay editable.
        caption=scene.subtitle_text if scene.visual_type == "text_animation" else "",
        title=strategy.title,
        seed_text=f"{project.id}:{scene.id}",
    )

    resolved = image_engines.resolve_engine_id(engine_id)
    engine = image_engines.get_engine(resolved)
    if resolved == "procedural":
        return engine.render_scene_image(spec, project.width, project.height, dest)
    return engine.render(spec, project.width, project.height, dest)


# ----------------------------------------------------------- narration


def synthesize_narration(scene: Scene, index: int, project_id: str, voice_id: str | None) -> tuple[Path | None, float]:
    """Speaks the scene's narration. Returns (path, measured seconds).

    A failure is not fatal: the scene keeps its planned duration and the
    video is simply silent there, which is a far better outcome than
    aborting a production because one line would not synthesise.
    """
    text = (scene.narration or "").strip()
    if not text:
        return None, 0.0
    if not tts_service.is_supported_platform():
        return None, 0.0

    dest = scene_audio_dir(project_id) / f"narr_{index:03d}_{scene.id[:8]}.wav"
    try:
        tts_service.synthesize_to_wav(text, voice_id, dest)
    except Exception:
        logger.exception("Narration synthesis failed for scene %s", scene.id)
        return None, 0.0

    try:
        duration = float(probe_media(dest).duration)
    except Exception:
        logger.exception("Could not measure narration length for scene %s", scene.id)
        duration = 0.0
    return dest, duration


def retime_from_narration(scene: Scene, narration_seconds: float, max_seconds: float) -> bool:
    """Grows a scene so its narration fits. Returns True if it changed.

    Capped at `max_seconds` so one over-long line cannot turn a 60-second
    short into a two-minute one; when the cap bites, the speech is still
    played in full over the following cut rather than being truncated.
    """
    if narration_seconds <= 0:
        return False
    needed = narration_seconds + NARRATION_LEAD_IN + NARRATION_TAIL_PADDING
    if needed <= scene.estimated_duration + 0.05:
        return False
    scene.estimated_duration = round(min(needed, max_seconds), 2)
    return True


# --------------------------------------------------------------- clips


def _pick_sfx(scene: Scene) -> str | None:
    raw = (scene.sfx or "").strip().lower()
    if not raw or raw in ("none", "なし", "無し", "-"):
        return None
    for kind in compose.SFX_KINDS:
        if kind in raw:
            return kind
    # The writer asked for *something*; a neutral accent is closer to the
    # intent than dropping it silently.
    return "pop"


def build_scene_clip(
    scene: Scene,
    index: int,
    project: Project,
    *,
    visual_path: Path | None,
    narration_path: Path | None,
    source_video: Path | None = None,
    crf: int = 20,
    is_last: bool = False,
) -> Path:
    """Renders one scene into a finished video file with its own audio.

    `is_last` is the only thing that gets a fade: scenes are concatenated
    back to back, so fading every clip in and out put a black flash at
    every cut. Short-form cuts hard; the video as a whole fades out once,
    at the end.
    """
    work = scene_visual_dir(project.id) / "_clips"
    work.mkdir(parents=True, exist_ok=True)
    dest = work / f"clip_{index:03d}_{scene.id[:8]}.mp4"
    duration = max(0.4, float(scene.estimated_duration))

    if source_video is not None and source_video.exists():
        compose.video_to_clip(
            source_video,
            dest,
            duration,
            project.width,
            project.height,
            project.fps,
            audio_path=narration_path,
            crf=crf,
        )
    else:
        if visual_path is None:
            raise RuntimeError(f"Scene {scene.id} has no visual to render")
        zoom_start, zoom_end, pan = resolve_camera(scene.camera or "")
        compose.still_to_clip(
            visual_path,
            dest,
            duration,
            project.width,
            project.height,
            project.fps,
            audio_path=narration_path,
            audio_delay=NARRATION_LEAD_IN if narration_path else 0.0,
            zoom_start=zoom_start,
            zoom_end=zoom_end,
            pan=pan,
            crf=crf,
            fade_in=0.0,
            fade_out=0.4 if is_last else 0.0,
        )

    kind = _pick_sfx(scene)
    if kind:
        sfx_path = scene_audio_dir(project.id) / f"sfx_{index:03d}_{kind}.m4a"
        try:
            compose.synthesize_sfx(sfx_path, kind)
            mixed = work / f"clip_{index:03d}_{scene.id[:8]}_sfx.mp4"
            # Placed just after the cut, where an accent lands with the
            # picture change rather than arriving under the narration.
            compose.overlay_sfx(dest, [(sfx_path, 0.08)], mixed)
            dest.unlink(missing_ok=True)
            mixed.replace(dest)
        except Exception:
            logger.exception("SFX overlay failed for scene %s; keeping clean audio", scene.id)

    return dest


def register_clip_asset(db, project: Project, scene: Scene, clip_path: Path, index: int) -> MediaAsset:
    """Moves a finished scene clip into the project's assets and records it.

    Registering as a MediaAsset (rather than referencing the working file)
    is what lets the existing timeline, preview and render code use it
    unchanged.
    """
    final_name = f"scene_{index:03d}_{uuid.uuid4().hex[:8]}.mp4"
    final_path = assets_dir(project.id) / final_name
    final_path.parent.mkdir(parents=True, exist_ok=True)
    clip_path.replace(final_path)

    info = probe_media(final_path)
    asset = MediaAsset(
        project_id=project.id,
        kind="video",
        original_filename=f"Scene{index + 1:02d}_{(scene.subtitle_text or scene.narration or '')[:16]}.mp4",
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

    scene.media_asset_id = asset.id
    scene.status = "generated"
    db.commit()
    return asset


def resolve_user_source(db, scene: Scene, project_id: str) -> Path | None:
    """The user's own footage for this scene, when they pinned one.

    Reads `user_asset_id`, never `media_asset_id`: the latter is the clip
    Kairo rendered, and using it here would make each rebuild re-wrap the
    previous render instead of the original source.
    """
    if scene.asset_source != "user" or not scene.user_asset_id:
        return None
    asset = db.get(MediaAsset, scene.user_asset_id)
    if asset is None or asset.project_id != project_id or asset.kind != "video":
        return None
    path = project_dir(project_id) / asset.stored_path
    return path if path.exists() else None


def rebuild_scene(
    db,
    project: Project,
    scene: Scene,
    index: int,
    strategy: ProductionStrategy,
    *,
    engine_id: str = "procedural",
    crf: int = 20,
    use_narration: bool = True,
    voice_id: str | None = None,
    regenerate_visual: bool = False,
    resynthesize_narration: bool = False,
    is_last: bool = False,
) -> MediaAsset:
    """Rebuilds one scene's material end to end and re-registers its asset.

    The single place both the pipeline and AI Co-Creation go through when a
    scene changes, so a chat-driven edit produces material identical to
    what a full run would have produced. Existing files are reused unless
    explicitly asked to regenerate, which is what makes both resume and
    "just change the duration" cheap: only the clip is re-encoded.
    """
    user_source = resolve_user_source(db, scene, project.id)

    visual_path: Path | None = None
    if user_source is None:
        visual_path = scene_visual_dir(project.id) / f"scene_{index:03d}_{scene.id[:8]}.png"
        if regenerate_visual or not visual_path.exists():
            visual_path = render_scene_visual(
                scene, index, project, strategy, engine_id=engine_id
            )

    narration_path: Path | None = None
    if use_narration:
        candidate = scene_audio_dir(project.id) / f"narr_{index:03d}_{scene.id[:8]}.wav"
        if resynthesize_narration or not candidate.exists():
            narration_path, seconds = synthesize_narration(scene, index, project.id, voice_id)
            if narration_path is not None:
                scene.narration_duration = seconds
        elif candidate.exists():
            narration_path = candidate

    clip = build_scene_clip(
        scene,
        index,
        project,
        visual_path=visual_path,
        narration_path=narration_path,
        source_video=user_source,
        crf=crf,
        is_last=is_last,
    )
    return register_clip_asset(db, project, scene, clip, index)
