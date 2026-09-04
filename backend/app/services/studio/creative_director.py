"""The agent's creative decisions: font, music, beat grid, SFX, subtitles.

This is the stage that turns "旅行ジャンル、40秒、明るいトーン" into named
assets with reasons attached. It sits between the planner (which decides
what the video says) and assembly (which builds it), and it exists as its
own module because those decisions have to be *recorded*, not just made -
the UI shows them, the report cites them, and `assets-used.json` is
generated from them.

Three rules shape it:

* **Nothing unlicensed is ever chosen.** Selection goes through
  `library/selector.py`, which filters on licence status before scoring.
* **Every choice carries its reason.** A decision that cannot be explained
  is not better than no decision, because the user cannot act on it.
* **Missing is a valid outcome.** No suitable font, no beat in the music, no
  effect in that category - each is reported plainly and the production
  continues with what it does have.
"""
from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from app.core.config import LIBRARY_ROOT
from app.core.paths import assets_dir
from app.models.library import LibraryAsset
from app.models.media_asset import MediaAsset
from app.schemas.edit_style import EditDirective, FontCandidate
from app.schemas.production_assets import (
    AssetChoice,
    AssetDecisions,
    BeatSyncResult,
    FontRanking,
    LicenseRef,
    SfxPlacement,
    SubtitleDecision,
)
from app.schemas.settings import SubtitleSettings
from app.schemas.trend import GenreProfileData
from app.services import subtitle_style
from app.services.ffmpeg.probe import probe_media
from app.services.library import audio_library, font_ranking, licenses, selector
from app.services.studio import style_memory

logger = logging.getLogger(__name__)


def _choice_from_selection(kind: str, sel: selector.Selection) -> AssetChoice:
    if not sel.found or sel.asset is None:
        return AssetChoice(
            kind=kind,
            found=False,
            reason=sel.reason,
            considered=sel.considered,
            rejected_for_license=sel.rejected_for_license,
            unavailable_reason=sel.reason,
        )
    asset = sel.asset
    data = sel.to_dict()
    return AssetChoice(
        kind=kind,
        found=True,
        asset_id=asset.id,
        name=asset.name,
        family=asset.family,
        path=asset.path,
        category=asset.category,
        source=asset.source,
        source_url=asset.source_url,
        reason=sel.reason,
        reasons=sel.reasons,
        score=sel.score,
        license=LicenseRef(**data["license"]),
        bpm=asset.bpm,
        duration=asset.duration,
        loudness_lufs=asset.loudness_lufs,
        considered=sel.considered,
        rejected_for_license=sel.rejected_for_license,
    )


# --------------------------------------------------------------- fonts


def choose_font(
    db,
    *,
    genre: str,
    profile: GenreProfileData | None,
    require_commercial: bool = True,
) -> AssetChoice:
    """The caption face, chosen from the genre alone.

    Kept for callers that have no directive (the library screen's preview,
    and any older path). A production run goes through
    `choose_font_for_directive`, which ranks against what this specific
    video needs instead of what the genre generally wants.
    """
    sel = selector.select_font(
        db, genre=genre, profile=profile, require_commercial=require_commercial
    )
    return _choice_from_selection("font", sel)


def choose_font_for_directive(
    db,
    directive: EditDirective,
    *,
    require_commercial: bool = True,
    recent_families: list[str] | None = None,
) -> tuple[AssetChoice, list[FontCandidate], dict]:
    """The caption face for one specific video (requirement 3).

    Returns the choice, the runners-up, and the ranking diagnostics. All
    three are stored on the run: the brief asks for the font decision to be
    inspectable afterwards, and a winner with no field behind it explains
    nothing.

    Falls back to the genre-only selector when the ranking finds nothing -
    an over-strict directive (a readability floor no installed face clears,
    say) must not leave a production with no caption font at all.
    """
    recent = (
        recent_families
        if recent_families is not None
        else style_memory.recent_fonts()
    )
    candidates, diagnostics = font_ranking.rank(
        db, directive, require_commercial=require_commercial, recent_families=recent
    )
    ranked = font_ranking.unique_families(candidates)
    if not ranked:
        sel = selector.select_font(
            db,
            genre=directive.genre,
            profile=None,
            require_commercial=require_commercial,
            # The directive's floor is what emptied the list; drop to the
            # selector's own minimum rather than shipping boxes for text.
            min_readability=40,
        )
        choice = _choice_from_selection("font", sel)
        if choice.found:
            choice.reasons.insert(
                0,
                "編集方針の条件に合う書体が見つからなかったため、"
                "可読性を基準に選び直しました",
            )
            choice.reason = choice.reasons[0]
        return choice, [], diagnostics

    best = ranked[0]
    row = db.get(LibraryAsset, best.asset_id)
    if row is None:
        return AssetChoice(kind="font", found=False, reason="選択した書体が見つかりません"), ranked, diagnostics

    lic = {
        "id": row.license_id,
        "name": row.license_name,
        "status": row.license_status,
        "status_label": licenses.status_label(row.license_status),
        "url": row.license_url,
        "attribution_required": row.attribution_required,
        "attribution": row.attribution_text,
        "commercial_use": row.commercial_use,
    }
    reasons = list(best.reasons)
    if len(ranked) > 1:
        reasons.append(
            f"候補{diagnostics.get('eligible', 0)}書体を採点し、"
            f"次点「{ranked[1].family}」({ranked[1].score:.0f}点)を上回りました"
        )
    if not diagnostics.get("profiled"):
        reasons.append(
            "フォントの印象プロファイルが未算出のため、可読性中心の採点です"
            "（設定 > ライブラリで再スキャンすると精度が上がります）"
        )
    choice = AssetChoice(
        kind="font",
        found=True,
        asset_id=row.id,
        name=row.name,
        family=row.family or row.name,
        path=row.path,
        category=row.category,
        source=row.source,
        source_url=row.source_url,
        reason=" / ".join(reasons[:3]) or "編集方針に最も合う書体として選択",
        reasons=reasons,
        score=best.score,
        license=LicenseRef(**lic),
        considered=int(diagnostics.get("considered", 0)),
        rejected_for_license=int(diagnostics.get("rejected_for_license", 0)),
    )
    return choice, ranked, diagnostics


def subtitle_settings_for(
    base: SubtitleSettings,
    font: AssetChoice | None,
    profile: GenreProfileData | None,
    *,
    width: int,
    height: int,
    directive: EditDirective | None = None,
) -> tuple[SubtitleSettings, SubtitleDecision]:
    """The caption style this production will actually be burned with.

    Derived from the user's settings, overridden only where the agent has a
    reason: the chosen family, the position/style the directive or the
    genre profile asks for, and - when a delivery platform demands it - a
    scale on the size.

    Size stays anchored to the user's setting. The directive may scale it
    for the format (a 16:9 delivery needs smaller text than a 9:16 one),
    but it is a multiplier on what the user chose rather than a replacement
    for it, so the Settings screen keeps meaning what it says.
    """
    resolved = base.model_copy(deep=True)
    reasons: list[str] = []
    from_profile = False

    if font is not None and font.found and font.family:
        resolved.font = font.family
        reasons.append(f"書体: {font.family}（{font.reason}）")

    if directive is not None and directive.style_label:
        if directive.subtitle.position != resolved.position:
            resolved.position = directive.subtitle.position  # type: ignore[assignment]
            reasons.append(
                f"表示位置: {directive.subtitle.position}（{directive.platform_label}の画面構成に合わせて）"
            )
        if directive.subtitle.style != resolved.style:
            resolved.style = directive.subtitle.style  # type: ignore[assignment]
            reasons.append(f"縁取り: {directive.subtitle.style}（{directive.style_label}の方針）")
        scale = directive.subtitle.size_scale
        if abs(scale - 1.0) > 0.02:
            before = resolved.size
            resolved.size = max(12, min(200, int(round(resolved.size * scale))))
            reasons.append(
                f"サイズ: {before}px→{resolved.size}px"
                f"（{directive.platform_label}向けに{scale:.2f}倍）"
            )

    # The genre profile only speaks when no directive did. The directive has
    # already folded the profile in (edit_director._apply_profile) *and*
    # applied the platform's rules on top, so letting the raw profile
    # override here would undo the platform decision - a Shorts caption
    # pushed up off the UI would drop straight back onto it.
    if profile is not None and (directive is None or not directive.style_label):
        if profile.subtitle_position in ("top", "middle", "bottom"):
            if profile.subtitle_position != resolved.position:
                resolved.position = profile.subtitle_position  # type: ignore[assignment]
                from_profile = True
                reasons.append(f"表示位置: {profile.subtitle_position}（ジャンル傾向）")
        if profile.subtitle_style in ("outline", "box", "plain"):
            if profile.subtitle_style != resolved.style:
                resolved.style = profile.subtitle_style  # type: ignore[assignment]
                from_profile = True
                reasons.append(f"縁取り: {profile.subtitle_style}（ジャンル傾向）")

    decision = SubtitleDecision(
        font=resolved.font,
        size=subtitle_style.resolve_size_px(resolved, height),
        position=resolved.position,
        style=resolved.style,
        color=resolved.color,
        max_chars_per_line=subtitle_style.max_chars_per_line(resolved, width, height),
        reason=" / ".join(reasons) or "設定のとおりの字幕スタイルを使用します",
        from_trend_profile=from_profile,
    )
    return resolved, decision


# --------------------------------------------------------------- music


def choose_music(
    db,
    *,
    mood: str,
    duration: float,
    profile: GenreProfileData | None,
    tempo: str = "medium",
    require_commercial: bool = True,
) -> AssetChoice:
    """Picks a bed, preferring one with a usable beat grid.

    Tried twice on purpose: a track with a known tempo enables Beat Sync, so
    it is worth insisting on first, but a video with music that cannot be
    cut to is still better than a silent one.
    """
    sel = selector.select_music(
        db,
        mood=mood,
        duration=duration,
        profile=profile,
        tempo=tempo,
        require_commercial=require_commercial,
        require_beat=True,
    )
    if not sel.found:
        sel = selector.select_music(
            db,
            mood=mood,
            duration=duration,
            profile=profile,
            tempo=tempo,
            require_commercial=require_commercial,
            require_beat=False,
        )
        if sel.found:
            sel.fallback = True
            sel.reasons.append("テンポ情報のある曲がなかったため、雰囲気優先で選びました")
    return _choice_from_selection("music", sel)


def import_library_audio(
    db, project_id: str, choice: AssetChoice, *, origin: str, label: str
) -> MediaAsset | None:
    """Copies a chosen library file into the project and registers it.

    Copied rather than referenced so a project stays self-contained: the
    render, the timeline and any later re-render all read from the
    project's own assets directory, and deleting a library entry later
    cannot break a finished video.
    """
    if not choice.found or not choice.path:
        return None
    source = LIBRARY_ROOT / choice.path
    if not source.exists():
        logger.info("Library asset missing on disk: %s", source)
        return None

    dest_name = f"{origin}_{uuid.uuid4().hex[:8]}{source.suffix}"
    dest = assets_dir(project_id) / dest_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source, dest)
        info = probe_media(dest)
    except Exception:
        logger.exception("Could not import library asset %s", source)
        return None

    asset = MediaAsset(
        project_id=project_id,
        kind="audio",
        original_filename=f"{label}_{choice.name}{source.suffix}",
        stored_path=f"assets/{dest_name}",
        duration=info.duration,
        has_audio=True,
        audio_codec=info.audio_codec,
        origin=origin,
        origin_detail=f"{choice.source} / {choice.license.name}",
        analysis_status="skipped",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


# ------------------------------------------------------------ beat sync


# Cutting on every beat at 130 BPM means a cut every 0.46s, which is a
# strobe, not an edit. The grid the scenes are snapped to is therefore a
# multiple of the beat, chosen so the resulting cut length lands closest to
# what the strategy already wanted.
_CANDIDATE_MULTIPLES = (1, 2, 3, 4, 6, 8)


def plan_beat_sync(
    scenes: list,
    music: AssetChoice | None,
    *,
    target_scene_seconds: float,
    max_shift_ratio: float = 0.35,
) -> BeatSyncResult:
    """Snaps scene durations onto the music's beat grid.

    Returns the plan without applying it. `max_shift_ratio` bounds how much
    any one scene may move: a scene whose length was chosen to fit measured
    narration must not be stretched 40% to hit a beat, because the audio
    would then run past the cut.
    """
    if music is None or not music.found:
        return BeatSyncResult(applied=False, reason="BGMが選ばれていないため同期しません。")
    if not music.bpm:
        return BeatSyncResult(
            applied=False,
            reason="このBGMはテンポを検出できなかったため、シーン境界でカットします。",
        )
    if not scenes:
        return BeatSyncResult(applied=False, reason="対象シーンがありません。")

    beat = 60.0 / float(music.bpm)
    best_multiple = min(
        _CANDIDATE_MULTIPLES,
        key=lambda m: abs(beat * m - target_scene_seconds),
    )
    grid = beat * best_multiple

    cut_points: list[float] = []
    adjusted = 0
    drift = 0.0
    cursor = 0.0
    for scene in scenes:
        current = float(scene.estimated_duration or 0.0)
        if current <= 0:
            cut_points.append(round(cursor, 3))
            continue
        # Snap this scene's length to the nearest whole number of grid
        # units, never to zero.
        units = max(1, round(current / grid))
        snapped = units * grid
        shift = abs(snapped - current)
        if shift > current * max_shift_ratio:
            snapped = current  # too far; leave this scene alone
        else:
            if shift >= 0.02:
                adjusted += 1
                drift += shift
        cursor += snapped
        cut_points.append(round(cursor, 3))

    return BeatSyncResult(
        applied=adjusted > 0,
        reason=(
            f"{music.bpm:.0f}BPMの{best_multiple}拍（{grid:.2f}秒）刻みに"
            f"{adjusted}シーンのカット位置を合わせました。"
            if adjusted
            else "既にビートに近かったため調整は不要でした。"
        ),
        bpm=music.bpm,
        bpm_source="declared" if music.source.startswith("Kairo") else "detected",
        beat_seconds=round(beat, 4),
        beats_per_cut=best_multiple,
        adjusted_scenes=adjusted,
        total_drift_seconds=round(drift, 3),
        cut_points=cut_points,
    )


def apply_beat_sync(scenes: list, plan: BeatSyncResult) -> set[int]:
    """Writes a beat-sync plan onto the scenes. Returns changed indices."""
    if not plan.applied or not plan.cut_points:
        return set()
    changed: set[int] = set()
    previous = 0.0
    for i, scene in enumerate(scenes):
        if i >= len(plan.cut_points):
            break
        new_duration = round(plan.cut_points[i] - previous, 3)
        previous = plan.cut_points[i]
        if new_duration <= 0.2:
            continue
        if abs(new_duration - float(scene.estimated_duration or 0.0)) >= 0.02:
            scene.estimated_duration = new_duration
            changed.add(i)
    return changed


# ------------------------------------------------------------------ SFX


# Which effect marks which kind of moment. Deliberately small: an effect on
# every event is noise, and the design brief is explicit that SFX must not
# be overused.
_TRIGGER_CATEGORY = {
    "hook": "whoosh",
    "scene_change": "whoosh",
    "emphasis": "hit",
    "subtitle": "pop",
    "ending": "cinematic",
}

# No more than this many effects per minute of finished video.
MAX_SFX_PER_MINUTE = 12.0


def plan_sfx(
    db,
    scenes: list,
    *,
    profile: GenreProfileData | None = None,
    require_commercial: bool = True,
    directive: EditDirective | None = None,
) -> tuple[list[SfxPlacement], list[AssetChoice]]:
    """Where the effects go, and why each one is there.

    Placed against the *scene design* rather than sprinkled: a transition
    accent at each cut that is not a hard scene change is what makes an
    effect read as intentional. Density is capped, and the cap drops the
    least-motivated placements first (scene changes) rather than truncating
    the list, so the hook and the ending keep theirs.
    """
    if not scenes:
        return [], []

    resolved: dict[str, AssetChoice] = {}

    def asset_for(category: str) -> AssetChoice | None:
        if category not in resolved:
            sel = selector.select_sfx(db, category, require_commercial=require_commercial)
            resolved[category] = _choice_from_selection("sfx", sel)
        choice = resolved[category]
        return choice if choice.found else None

    placements: list[SfxPlacement] = []
    cursor = 0.0
    total = sum(float(s.estimated_duration or 0.0) for s in scenes)

    for i, scene in enumerate(scenes):
        duration = float(scene.estimated_duration or 0.0)
        # A scene's own `sfx` field is the writer's explicit request and
        # always wins over the automatic placement rules.
        requested = (getattr(scene, "sfx", "") or "").strip().lower()
        if i == 0:
            trigger, category = "hook", _TRIGGER_CATEGORY["hook"]
        elif i == len(scenes) - 1:
            trigger, category = "ending", _TRIGGER_CATEGORY["ending"]
        else:
            trigger, category = "scene_change", _TRIGGER_CATEGORY["scene_change"]
        if requested in ("pop", "whoosh", "hit", "click", "transition", "cinematic", "sparkle"):
            trigger, category = "script", requested

        choice = asset_for(category)
        if choice is not None:
            placements.append(
                SfxPlacement(
                    # Just before the cut, so the effect leads into the new
                    # shot rather than landing on top of it.
                    at=round(max(0.0, cursor - 0.06), 3),
                    category=category,
                    asset_id=choice.asset_id,
                    name=choice.name,
                    trigger=trigger,
                    scene_index=i,
                    gain=0.7 if trigger in ("hook", "ending", "script") else 0.5,
                    reason={
                        "hook": "冒頭の掴みを立てるため",
                        "ending": "終わりの余韻を作るため",
                        "scene_change": "場面転換をはっきりさせるため",
                        "script": "シーン設計で指定された効果音",
                    }.get(trigger, ""),
                )
            )
        cursor += duration

    # The style decides the density. A documentary that tolerates 1.5
    # effects per minute must not get the short-form default of 12, and a
    # Vlog with a whoosh at every cut is the "エフェクトが多い＝高品質" trap
    # the brief rules out.
    per_minute = MAX_SFX_PER_MINUTE
    if directive is not None and directive.style_label:
        per_minute = max(0.0, directive.audio.sfx_per_minute)
    if per_minute <= 0.01:
        return [], [c for c in resolved.values() if c.found]
    limit = max(1, int(per_minute * max(total, 1.0) / 60.0))
    if len(placements) > limit:
        # Priority within the budget: the opening and the closing accent
        # first (they mark the video's edges), then the effects the scene
        # writer asked for by name, then the automatic scene-change accents.
        #
        # The writer's requests used to be exempt from the cap entirely,
        # which meant a Vlog whose script asked for a whoosh on ten of its
        # twenty-four beats got twelve effects against a style budget of
        # four. An explicit request is a strong preference about *which*
        # effects survive, not permission to ignore how many the style
        # tolerates - "エフェクトが多い＝高品質" is exactly what the brief
        # rules out.
        priority = {"hook": 0, "ending": 0, "script": 1}
        ordered = sorted(
            placements, key=lambda p: (priority.get(p.trigger, 2), p.at)
        )
        edges = [p for p in ordered if priority.get(p.trigger, 2) == 0][:2]
        rest = [p for p in ordered if p not in edges]
        room = max(0, limit - len(edges))
        # Thin the remainder evenly rather than dropping the tail, so the
        # effects that survive are spread across the video.
        step = max(1, len(rest) // room) if room else 1
        keep = edges + (rest[::step][:room] if room else [])
        placements = sorted(keep, key=lambda p: p.at)

    return placements, [c for c in resolved.values() if c.found]


def sfx_render_list(db, placements: list[SfxPlacement]) -> list[tuple[Path, float]]:
    """(file, timestamp) pairs for `compose.overlay_sfx`."""
    out: list[tuple[Path, float]] = []
    for placement in placements:
        if not placement.asset_id:
            continue
        row = db.get(LibraryAsset, placement.asset_id)
        if row is None:
            continue
        path = LIBRARY_ROOT / row.path
        if path.exists():
            out.append((path, placement.at))
    return out


def ensure_library(db) -> None:
    """Makes sure the library has something in it before selecting from it.

    A first run on a fresh install would otherwise find an empty library and
    report "no usable music" - technically true, and useless. Generating the
    built-in assets is cheap, local and licence-clean.
    """
    from app.services.library import fonts as font_service

    if db.query(LibraryAsset).filter(LibraryAsset.kind == "font").count() == 0:
        font_service.scan(db)
    if db.query(LibraryAsset).filter(LibraryAsset.kind == "music").count() == 0:
        audio_library.bootstrap(db)


def build(
    db,
    *,
    genre: str,
    genre_label: str,
    profile: GenreProfileData | None,
    scenes: list,
    duration: float,
    mood: str,
    tempo: str,
    subtitle_base: SubtitleSettings,
    width: int,
    height: int,
    require_commercial: bool = True,
    target_scene_seconds: float = 3.0,
    directive: EditDirective | None = None,
) -> AssetDecisions:
    """One call, every creative-asset decision for a run.

    `directive` is what makes the font and the SFX density decisions about
    *this* video rather than about its genre. It is optional so the older
    genre-only path still works unchanged for callers that have none.
    """
    ensure_library(db)

    ranking: FontRanking | None = None
    if directive is not None and directive.style_label:
        font, candidates, diagnostics = choose_font_for_directive(
            db, directive, require_commercial=require_commercial
        )
        ranking = FontRanking(
            **{k: v for k, v in diagnostics.items() if k in FontRanking.model_fields},
            candidates=[c.model_dump() for c in candidates],
        )
    else:
        font = choose_font(
            db, genre=genre, profile=profile, require_commercial=require_commercial
        )
    music = choose_music(
        db,
        mood=mood,
        duration=duration,
        profile=profile,
        tempo=tempo,
        require_commercial=require_commercial,
    )
    _resolved, subtitle = subtitle_settings_for(
        subtitle_base, font, profile, width=width, height=height, directive=directive
    )
    beat = plan_beat_sync(scenes, music, target_scene_seconds=target_scene_seconds)
    placements, sfx_assets = plan_sfx(
        db,
        scenes,
        profile=profile,
        require_commercial=require_commercial,
        directive=directive,
    )

    notes: list[str] = []
    if not font.found:
        notes.append(f"フォント: {font.reason}")
    if not music.found:
        notes.append(f"BGM: {music.reason}")
    if not placements:
        notes.append("効果音: 使用できる効果音がライブラリにありませんでした。")

    return AssetDecisions(
        genre=genre,
        genre_label=genre_label,
        font=font,
        font_ranking=ranking,
        music=music,
        sfx=placements,
        sfx_assets=sfx_assets,
        subtitle=subtitle,
        beat_sync=beat,
        notes=notes,
    )
