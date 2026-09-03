"""Turning a designed scene into actual material on disk.

Three stages live here, in the order the pipeline runs them:

1. `render_scene_visual` - the scene's key visual, for a scene nothing was
   pinned to. A downloaded diffusion engine is used if there is one, and
   otherwise Kairo composes the frame itself (`image_engines.procedural`),
   which is what makes "素材ゼロでも完成する" true rather than aspirational.
   `fill_missing_visual` sits above it and walks the whole priority order:
   a licensed web image first, then generation, then composition, with the
   choice recorded on the scene so the finished video can say where each
   shot came from.

   Material the user supplied never reaches either of them. It is pinned
   to the scene by the matching stage (`material_plan`), resolved here by
   `resolve_pinned_source`, and used directly - a photo gets the scene's
   camera move, a video gets cut from the interval the analysis found
   usable.

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
from dataclasses import dataclass
from pathlib import Path

from app.core.paths import assets_dir, project_dir
from app.models.media_asset import MediaAsset
from app.models.production import Scene
from app.models.project import Project
from app.schemas.studio import ProductionStrategy
from app.services import image_engines, media_service, tts_service
from app.services.ffmpeg import compose
from app.services.ffmpeg.probe import probe_media
from app.services.image_engines.procedural import SceneVisualSpec, resolve_camera
from app.services.studio import web_material_service

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
    source_start: float = 0.0,
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
            source_start=source_start,
            # The user's own footage is almost never shot in the aspect
            # ratio of the short being made. Letterboxing it would hand
            # back half the screen as black bars, so it fills the frame.
            fill="cover",
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
        # A rendered scene clip is not material the user can be offered
        # again; marking it keeps it out of the material list and out of
        # the matching pool.
        origin="kairo_clip",
        analysis_status="skipped",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)

    scene.media_asset_id = asset.id
    scene.status = "generated"
    db.commit()
    return asset


@dataclass
class UserSource:
    """The user's own material for one scene, resolved to a real file."""

    path: Path
    kind: str  # "video" | "image"
    start: float = 0.0
    asset_id: str = ""
    filename: str = ""


def resolve_pinned_source(db, scene: Scene, project_id: str) -> UserSource | None:
    """The user's own material for this scene, when one is pinned.

    Reads `user_asset_id`, never `media_asset_id`: the latter is the clip
    Kairo rendered, and using it here would make each rebuild re-wrap the
    previous render instead of the original source.

    Photos count as well as footage. When the material pipeline started
    placing the user's stills into scenes, restricting this to videos was
    what silently replaced them with generated frames - the pin was set,
    and the asset stage could not see it.
    """
    # "user" is the user's own file; "web" is a licensed image Kairo
    # downloaded for a beat their material did not cover. Both are real
    # files pinned to the scene, and both are rendered the same way - what
    # differs is the provenance recorded in `material_origin`.
    if scene.asset_source not in ("user", "web") or not scene.user_asset_id:
        return None
    asset = db.get(MediaAsset, scene.user_asset_id)
    if asset is None or asset.project_id != project_id:
        return None
    if asset.kind not in ("video", "image"):
        return None
    path = project_dir(project_id) / asset.stored_path
    if not path.exists():
        return None
    return UserSource(
        path=path,
        kind=asset.kind,
        start=float(scene.user_asset_start or 0.0),
        asset_id=asset.id,
        filename=asset.original_filename,
    )


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
    user_source = resolve_pinned_source(db, scene, project.id)

    visual_path: Path | None = None
    video_source: Path | None = None
    source_start = 0.0
    if user_source is not None and user_source.kind == "video":
        video_source = user_source.path
        source_start = user_source.start
    elif user_source is not None:
        # A user photo is used exactly as the generated still would be, so
        # it gets the same Ken Burns move from the scene's camera direction
        # rather than sitting motionless for three seconds.
        visual_path = user_source.path
    else:
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
        source_video=video_source,
        source_start=source_start,
        crf=crf,
        is_last=is_last,
    )
    return register_clip_asset(db, project, scene, clip, index)


# ------------------------------------------------------- filling the gaps



def _web_identity(candidate) -> str:
    """A stable identity for a web image: its page, else its file URL."""
    return (getattr(candidate, "source_page", "") or getattr(candidate, "url", "") or "").strip()


def _used_web_sources(db, project_id: str) -> set[str]:
    """Web images this project has already downloaded.

    Read from `origin_detail`, which `fill_missing_visual` writes as
    "<attribution> / <source page or url>" - the trailing field is the same
    identity `_web_identity` produces, so the two match without a new column.
    """
    rows = (
        db.query(MediaAsset)
        .filter(MediaAsset.project_id == project_id, MediaAsset.origin == "web")
        .all()
    )
    used: set[str] = set()
    for row in rows:
        detail = (row.origin_detail or "").strip()
        if " / " in detail:
            used.add(detail.rsplit(" / ", 1)[-1].strip())
        elif detail:
            used.add(detail)
    return used


def fill_missing_visual(
    db,
    project: Project,
    scene: Scene,
    index: int,
    strategy: ProductionStrategy,
    *,
    keywords: list[str],
    sources: list[str],
    orientation: str = "vertical",
) -> tuple[str, str]:
    """Produces a visual for a beat the user's material did not cover.

    Walks the priority order (design requirement 7) downwards from the
    first source that is actually available, and returns the origin it
    ended up using with a one-line explanation. Falling through is not a
    failure: an unreachable web source or an absent diffusion model simply
    means the next source is used, and the reason is recorded so the
    completion screen can say what happened instead of showing a shot with
    no explanation.
    """
    if "web" in sources:
        # Everything this project has already pulled from the web, so a
        # later scene with similar keywords does not land on the same photo.
        # Without this the same image filled three scenes of a 13-scene
        # video and the quality review reported it as repetition.
        already_used = _used_web_sources(db, project.id)
        try:
            # Searched wider than needed on purpose: the first few results
            # are the ones most likely to have been taken already, so a
            # limit of 3 could return nothing new.
            results = web_material_service.search(keywords, limit=8, orientation=orientation)
        except Exception:  # noqa: BLE001
            logger.exception("Web material search failed for scene %s", scene.id)
            results = []
        for candidate in results:
            identity = _web_identity(candidate)
            if identity and identity in already_used:
                logger.info("Skipping web material already used in this project: %s", identity)
                continue
            try:
                path = web_material_service.download(candidate, project.id)
            except web_material_service.WebMaterialUnavailable as exc:
                logger.info("Web material rejected: %s", exc)
                continue
            try:
                asset = media_service.register_file(
                    db,
                    project.id,
                    path,
                    original_filename=candidate.title or path.name,
                    origin="web",
                    origin_detail=(
                        f"{candidate.attribution} / {candidate.source_page or candidate.url}"
                    ),
                )
            except Exception:  # noqa: BLE001
                logger.exception("Could not register downloaded web material")
                path.unlink(missing_ok=True)
                continue
            scene.asset_source = "web"
            scene.user_asset_id = asset.id
            scene.user_asset_start = None
            scene.user_asset_end = None
            scene.material_origin = "web"
            scene.material_note = f"Web素材: {candidate.attribution}"
            db.commit()
            return "web", scene.material_note

    if "ai_generated" in sources:
        try:
            render_scene_visual(scene, index, project, strategy, engine_id="sd")
            scene.material_origin = "ai_generated"
            scene.material_note = "不足していたためAI画像生成で補完しました"
            db.commit()
            return "ai_generated", scene.material_note
        except Exception:  # noqa: BLE001
            logger.exception("AI image generation failed for scene %s", scene.id)

    render_scene_visual(scene, index, project, strategy, engine_id="procedural")
    scene.material_origin = "procedural"
    scene.material_note = "不足していたためKairoが構成した背景で補完しました"
    db.commit()
    return "procedural", scene.material_note
