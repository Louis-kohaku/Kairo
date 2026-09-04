"""Deciding which material goes into which scene.

This is where design requirements 5-9 actually live. The rules it
implements, in the order they take effect:

**The user's material wins.** Not "is considered" - wins. A project that
contains any usable photo or video the user supplied never shows a
Kairo-drawn abstract background in its place (requirement 7). Matching by
subject is how the *best* of the user's material is chosen for each beat;
when nothing matches by subject, leftover user material is still placed
before anything is fetched or generated, because a real holiday photo in a
slightly-off beat is closer to what the user asked for than an invented
image in the right one.

**Video before stills.** Both are the user's, but footage carries motion
and sound, so between two equally-matching candidates the clip wins.

**Only the genuinely missing is filled.** A shortage is a scene no user
material was left for, and it is filled from the first source in the
priority order that is actually available in this environment - which is
checked, not assumed, so the plan the user confirms never lists a source
that will silently turn into something else.

The plan is data, produced before anything is rendered, so the user can
read it and say "この内容で制作開始" (requirement 9), and so the same
decision can be replayed when material is added later (requirement 12).
"""
from __future__ import annotations

import json
import logging
import re

from app.models.media_asset import MediaAsset
from app.models.production import Scene
from app.schemas.material import (
    MaterialAnalysis,
    MaterialAssignment,
    MaterialPlan,
    MaterialShortage,
)
from app.services import media_service
from app.services.studio import material_analysis, web_material_service

logger = logging.getLogger(__name__)

# Score awarded per subject tag that appears in the scene's own text. The
# dominant term by design: a photo tagged 海 in a scene about 海 should
# beat every other consideration.
TAG_SCORE = 3.0
# Footage over stills, per the priority order.
VIDEO_BONUS = 1.0
# Material shot the same way round as the video being made needs no
# cropping, so it is preferred when subjects tie.
ORIENTATION_BONUS = 0.6
# A near-black or motionless clip is still the user's material and still
# beats a generated image, but loses to their other material.
DARK_PENALTY = 1.5
# Below this a scene has no subject match; the material may still be used
# (leftover placement), but the plan says so rather than claiming a match.
MATCH_THRESHOLD = TAG_SCORE

# --- measured quality (requirement 7) ---------------------------------
# Deliberately smaller than TAG_SCORE. Being about the right subject is
# what makes a shot usable at all; being sharp is what breaks a tie. A
# blur penalty that outweighed a subject match would fill a beach scene
# with a crisp photo of a car park.
#
# The thresholds are calibrated against measurements in
# frame_quality.sharpness: a well-focused photo lands near 0.55, a 3px
# Gaussian blur near 0.22, and a 5px blur near 0.13.
BLUR_THRESHOLD = 0.16
BLUR_PENALTY = 2.5
SHAKE_THRESHOLD = 0.5
SHAKE_PENALTY = 2.0
DUPLICATE_PENALTY = 2.5

# Tags that describe how a picture looks rather than what is in it. They
# are useful to display and useless for matching a subject, so they never
# earn a match score.
_APPEARANCE_TAGS = {"明るい", "暗い", "動きあり", "静止", "縦向き", "横向き", "正方形"}


# ------------------------------------------------------------- scoring


def _scene_text(scene: Scene) -> str:
    return " ".join(
        filter(
            None,
            [
                scene.visual_prompt or "",
                scene.subtitle_text or "",
                scene.narration or "",
                scene.purpose or "",
                scene.emotion or "",
            ],
        )
    )


def _score(
    analysis: MaterialAnalysis,
    asset: MediaAsset,
    scene_text: str,
    orientation: str,
) -> tuple[float, list[str]]:
    """How well one piece of material fits one scene, and why."""
    matched: list[str] = []
    score = 0.0
    haystack = scene_text
    for tag in analysis.tags:
        if tag in _APPEARANCE_TAGS or len(tag) < 2:
            continue
        if tag in haystack:
            matched.append(tag)
            score += TAG_SCORE

    if asset.kind == "video":
        score += VIDEO_BONUS
    if orientation and analysis.orientation == orientation:
        score += ORIENTATION_BONUS
    if analysis.brightness is not None and analysis.brightness < material_analysis.DARK_THRESHOLD:
        score -= DARK_PENALTY

    # --- measured quality (requirement 7) -----------------------------
    # Subject relevance above decides *whether* a piece of material is
    # about this scene; these decide whether it is worth showing. They are
    # additive rather than a filter, because a slightly soft photo of
    # exactly the right thing still beats a razor-sharp photo of something
    # else - which is the judgement a human editor makes.
    if analysis.quality_score is not None:
        # -12 at a quality of 0, +8 at 100.
        score += (analysis.quality_score - 60.0) * 0.2
    if analysis.sharpness is not None and analysis.sharpness < BLUR_THRESHOLD:
        score -= BLUR_PENALTY
    if analysis.shake is not None and analysis.shake > SHAKE_THRESHOLD:
        score -= SHAKE_PENALTY
    if analysis.duplicate_of:
        # The first copy of a shot keeps its score; the later ones are
        # pushed down so a burst of five near-identical photos does not
        # fill five scenes with the same picture.
        score -= DUPLICATE_PENALTY
    return score, matched


def quality_caveats(analysis: MaterialAnalysis) -> list[str]:
    """What is technically wrong with this material, in the user's words.

    Reported next to the assignment rather than mixed into the matched
    tags: "ピンボケ" is not something a scene asked for, and listing it
    as a match made the plan claim the opposite of what it meant.
    """
    notes: list[str] = []
    if analysis.sharpness is not None and analysis.sharpness < BLUR_THRESHOLD:
        notes.append("ピントが甘い素材です")
    if analysis.shake is not None and analysis.shake > SHAKE_THRESHOLD:
        notes.append("手ブレが大きい素材です")
    if analysis.brightness is not None and analysis.brightness < 0.14:
        notes.append("とても暗い素材です")
    if analysis.duplicate_of:
        notes.append("他の素材とほぼ同じ画です")
    return notes


# Material below this technical quality is not placed just to use it up.
# The user uploaded it, so it is still offered when it actually matches a
# scene's subject - but filling an empty beat with an out-of-focus frame
# makes the video worse than a generated background would, which is the
# one case requirement 7's "user material first" rule should not win.
LEFTOVER_QUALITY_FLOOR = 40.0


def _usable_slice(analysis: MaterialAnalysis, duration: float) -> tuple[float | None, float | None]:
    """The part of a video clip a scene of `duration` should take.

    Starts at the usable interval's start rather than 0:00, so a clip whose
    first second is a dark pocket shot contributes its actual content.
    """
    if analysis.kind != "video" or analysis.duration <= 0:
        return None, None
    start = max(0.0, analysis.usable.start or 0.0)
    end = analysis.usable.end or analysis.duration
    if end - start < duration and analysis.duration >= duration:
        # The usable window is shorter than the beat: keep the start and
        # let the clip loop rather than cutting into the unusable head.
        end = min(analysis.duration, start + duration)
    return round(start, 2), round(min(end, analysis.duration), 2)


# ----------------------------------------------------------- fill source


def available_fill_sources(*, check_web: bool = True) -> list[str]:
    """Which of the lower-priority sources actually work right now.

    Checked rather than assumed so the "補完方法" the user confirms is a
    statement about this machine, not a wish list.
    """
    from app.services import image_engines

    sources: list[str] = []
    if check_web and web_material_service.is_reachable():
        sources.append("web")
    if image_engines.resolve_engine_id("sd") == "sd":
        sources.append("ai_generated")
    try:
        from app.services.image_engines import procedural

        if procedural.is_available():
            sources.append("procedural")
    except Exception:  # noqa: BLE001
        pass
    return sources


def _fill_method(sources: list[str]) -> tuple[str, str]:
    if "web" in sources:
        return "web", "ライセンスを確認できるWeb素材から補完します"
    if "ai_generated" in sources:
        return "ai_generated", "AI画像生成で補完します"
    if "procedural" in sources:
        return "procedural", "Kairoが構成した抽象背景で補完します"
    return "procedural", "補完手段がないため、単色の背景で補完します"


# Words a visual prompt uses to describe mood, framing or grammar rather
# than what is in the shot. They are useless as search terms - "幻想的" and
# "非常" match nothing in a photo index - and including them turns a
# workable query into an empty result.
_STOPWORDS = {
    "する",
    "した",
    "して",
    "いる",
    "ある",
    "こと",
    "もの",
    "ため",
    "よう",
    "画面",
    "映像",
    "シーン",
    "カット",
    "場所",
    "様子",
    "瞬間",
    "非常",
    "幻想的",
    "雰囲気",
    "印象",
    "感覚",
    "全体",
    "表現",
    "焦点",
    "中心",
    "手前",
    "背景",
    "構図",
    "トーン",
    "アングル",
    "ローアングル",
    "クローズアップ",
    "スローモーション",
    "シネマティック",
    "テクスチャ",
    "グラデーション",
    "色彩",
    "質感",
    "強調",
    "演出",
}


# Japanese does not put spaces between words, so a visual prompt like
# "鮮やかな青い空に白い雲が広がる" is one token to a whitespace split - and
# one token is a useless search query. The subject words are the runs that
# are *not* hiragana, because the hiragana between them is the grammar:
# particles, adjective and verb endings, auxiliaries.
#
# Three shapes, because the useful length differs: a single kanji is often
# the whole word (空, 海, 光), katakana needs two characters before it means
# anything, and a Latin fragment needs three.
_SUBJECT_RUNS = (
    re.compile(r"[\u4e00-\u9fff]+"),
    re.compile(r"[\u30a0-\u30ff\uff66-\uff9f]{2,}"),
    re.compile(r"[A-Za-z]{3,}"),
)

# Single kanji that are whole nouns worth searching for. A one-character run
# is otherwise far more likely to be the stem of an inflected adjective or
# verb - "鮮やか" yields 鮮, "流れる" yields 流 - and a stock index returns
# nothing useful for those. Rather than guess at Japanese morphology, only
# these are accepted on their own.
_SINGLE_KANJI_NOUNS = {
    "海", "空", "山", "川", "花", "星", "森", "雲", "光", "夜", "街", "雨",
    "雪", "犬", "猫", "島", "波", "岩", "木", "橋", "城", "塔", "港", "湖",
    "滝", "道", "駅", "船", "車", "人", "顔", "手", "月", "日", "朝", "夕",
    "春", "夏", "秋", "冬", "風", "food",
}


def shortage_keywords(scene: Scene) -> list[str]:
    """Search words for a beat no user material covered.

    Taken from the scene's own visual prompt, because that is the sentence
    the writer produced to describe what should be on screen. Longer runs
    come first: they are the more specific subjects, and the web search
    widens from the front of this list until it finds something.
    """
    text = f"{scene.visual_prompt or ''} {scene.subtitle_text or ''}"
    found: list[str] = []
    for pattern in _SUBJECT_RUNS:
        for token in pattern.findall(text):
            token = token.strip()
            if not token or token in _STOPWORDS or token in found:
                continue
            if len(token) == 1 and token not in _SINGLE_KANJI_NOUNS:
                continue
            found.append(token)

    found.sort(key=len, reverse=True)
    return found[:6]


# -------------------------------------------------------------- planning


def _candidates(
    db, project_id: str, mode: str, selected_ids: list[str]
) -> list[tuple[MediaAsset, MaterialAnalysis]]:
    assets = media_service.list_user_material(db, project_id)
    if mode == "selected":
        wanted = set(selected_ids or [])
        assets = [a for a in assets if a.id in wanted]

    pairs: list[tuple[MediaAsset, MaterialAnalysis]] = []
    for asset in assets:
        analysis = material_analysis.load_analysis(asset)
        if analysis is None:
            # Never analysed (or the analysis failed): the file is still
            # the user's material and still outranks anything generated, so
            # it goes in with what metadata we have.
            analysis = MaterialAnalysis(
                asset_id=asset.id,
                kind=asset.kind,
                width=asset.width,
                height=asset.height,
                duration=asset.duration or 0.0,
                tags=material_analysis.tags_from_filename(asset.original_filename),
                analyzed_by="metadata",
                notes="解析前のため、ファイル名から推定しています。",
            )
        pairs.append((asset, analysis))
    return pairs


def build_plan(
    db,
    project_id: str,
    scenes: list[Scene],
    *,
    mode: str = "ai_auto",
    selected_ids: list[str] | None = None,
    orientation: str = "vertical",
    check_web: bool = True,
) -> MaterialPlan:
    """Matches the user's material onto a designed set of scenes."""
    pairs = _candidates(db, project_id, mode, selected_ids or [])
    sources = available_fill_sources(check_web=check_web)
    fill_method, fill_reason = _fill_method(sources)

    plan = MaterialPlan(
        mode=mode,  # type: ignore[arg-type]
        user_photo_count=sum(1 for a, _ in pairs if a.kind == "image"),
        user_video_count=sum(1 for a, _ in pairs if a.kind == "video"),
        available_fill_sources=sources,
    )

    # Pass 1 - subject matching. Every (scene, material) pair is scored and
    # the strongest pairs are taken first, so the best photo of the sea
    # lands in the scene about the sea rather than in whichever scene came
    # first and happened to mention water.
    scored: list[tuple[float, int, str, list[str]]] = []
    for i, scene in enumerate(scenes):
        text = _scene_text(scene)
        for asset, analysis in pairs:
            score, matched = _score(analysis, asset, text, orientation)
            if score >= MATCH_THRESHOLD:
                scored.append((score, i, asset.id, matched))
    scored.sort(key=lambda row: (-row[0], row[1]))

    by_id = {asset.id: (asset, analysis) for asset, analysis in pairs}
    assigned_scene: dict[int, tuple[str, list[str], float]] = {}
    used_assets: set[str] = set()
    for score, scene_index, asset_id, matched in scored:
        if scene_index in assigned_scene or asset_id in used_assets:
            continue
        assigned_scene[scene_index] = (asset_id, matched, score)
        used_assets.add(asset_id)

    # Pass 2 - leftover placement. Material the user gave us that matched
    # nothing is still theirs, and requirement 7 forbids showing a generated
    # background while it sits unused.
    # Videos first among the leftovers: they are above photos in the
    # priority order, and this is the one pass where subject relevance is
    # not deciding the outcome, so the stated order is the tie-break.
    # Ordered by kind (videos first, per the priority order) and then by
    # measured quality, so the leftover that gets a beat is the best of
    # them rather than whichever was uploaded first. Material below the
    # floor is left out entirely: showing an out-of-focus frame to avoid a
    # generated background is not honouring the user's material, it is
    # putting a bad shot in their video.
    def _leftover_rank(pair):
        asset, analysis = pair
        quality = analysis.quality_score if analysis.quality_score is not None else 60.0
        return (0 if asset.kind == "video" else 1, -quality)

    leftovers = []
    skipped_for_quality: list[str] = []
    for asset, analysis in sorted(pairs, key=_leftover_rank):
        if asset.id in used_assets:
            continue
        quality = analysis.quality_score
        # Two separate gates, because they catch different things. The
        # overall score catches a shot that is bad in several small ways;
        # the sharpness threshold catches one that is simply out of focus,
        # which can still score acceptably if it is bright and steady. A
        # blurred frame used purely to fill a beat is worse than the
        # generated background it displaced.
        blurred = (
            analysis.sharpness is not None and analysis.sharpness < BLUR_THRESHOLD
        )
        if (quality is not None and quality < LEFTOVER_QUALITY_FLOOR) or blurred:
            skipped_for_quality.append(asset.original_filename)
            continue
        leftovers.append(asset.id)
    if skipped_for_quality:
        plan.notes.append(
            "画質が低いため使わなかった素材: "
            + "、".join(skipped_for_quality[:5])
        )
    if leftovers:
        for i in range(len(scenes)):
            if i in assigned_scene or not leftovers:
                continue
            asset_id = leftovers.pop(0)
            assigned_scene[i] = (asset_id, [], 0.0)
            used_assets.add(asset_id)

    # Build the assignments and shortages in scene order.
    cursor = 0.0
    for i, scene in enumerate(scenes):
        duration = float(scene.estimated_duration or 0.0)
        entry = assigned_scene.get(i)
        if entry is None:
            keywords = shortage_keywords(scene)
            plan.shortages.append(
                MaterialShortage(
                    scene_index=i,
                    scene_number=i + 1,
                    need=(scene.visual_prompt or scene.subtitle_text or f"Scene {i + 1}")[:60],
                    keywords=keywords,
                    fill_method=fill_method,  # type: ignore[arg-type]
                    fill_reason=fill_reason,
                )
            )
            plan.assignments.append(
                MaterialAssignment(
                    scene_index=i,
                    scene_number=i + 1,
                    subtitle=scene.subtitle_text or "",
                    visual_prompt=scene.visual_prompt or "",
                    duration=duration,
                    start_time=round(cursor, 2),
                    origin=fill_method,  # type: ignore[arg-type]
                    reason=fill_reason,
                )
            )
        else:
            asset_id, matched, score = entry
            asset, analysis = by_id[asset_id]
            source_start, source_end = _usable_slice(analysis, duration)
            if matched:
                reason = f"「{'・'.join(matched[:3])}」が一致しました"
            else:
                reason = "ユーザー素材を優先して使用します（内容の一致は確認できていません）"
            caveats = quality_caveats(analysis)
            if caveats:
                reason += "（" + "、".join(caveats) + "）"
            plan.assignments.append(
                MaterialAssignment(
                    scene_index=i,
                    scene_number=i + 1,
                    subtitle=scene.subtitle_text or "",
                    visual_prompt=scene.visual_prompt or "",
                    duration=duration,
                    start_time=round(cursor, 2),
                    origin="user",
                    asset_id=asset_id,
                    filename=asset.original_filename,
                    source_start=source_start,
                    source_end=source_end,
                    reason=reason,
                    matched_tags=matched,
                    score=round(score, 2),
                )
            )
        cursor += duration

    plan.used_photo_count = sum(
        1 for a in plan.assignments if a.origin == "user" and by_id[a.asset_id][0].kind == "image"
    )
    plan.used_video_count = sum(
        1 for a in plan.assignments if a.origin == "user" and by_id[a.asset_id][0].kind == "video"
    )
    plan.unused_asset_ids = [asset.id for asset, _ in pairs if asset.id not in used_assets]

    counts: dict[str, int] = {}
    for shortage in plan.shortages:
        counts[shortage.fill_method] = counts.get(shortage.fill_method, 0) + 1
    plan.fill_counts = counts

    if plan.unused_asset_ids:
        plan.notes.append(
            f"シーン数より素材が多いため、{len(plan.unused_asset_ids)}点は使用されません。"
        )
    if mode == "use_all" and plan.unused_asset_ids:
        plan.notes.append(
            "「できるだけ全部使う」を選んでいますが、シーン数が足りませんでした。"
            "尺を長くするか、シーンを増やすと全て使えます。"
        )
    if not pairs:
        plan.notes.append("ユーザー素材がないため、必要な素材はKairoが用意します。")
    if "web" not in sources:
        plan.notes.append("Web素材は利用できません（ネットワーク未接続、または取得に失敗）。")
    if "ai_generated" not in sources:
        plan.notes.append("AI画像生成モデル（Stable Diffusion）は未導入です。")
    return plan


def preliminary_plan(
    db,
    project_id: str,
    *,
    mode: str = "ai_auto",
    selected_ids: list[str] | None = None,
    target_seconds: float = 30.0,
    average_scene_seconds: float = 3.2,
    check_web: bool = True,
) -> MaterialPlan:
    """The pre-production estimate shown on the start screen.

    The real plan needs the script, which does not exist before the run
    starts, so this one is explicitly `provisional`: it reports the
    material the user actually has (a fact) and an estimate of how many
    additional shots will be needed (clearly labelled as one). Presenting
    the estimate as a finished plan would be exactly the kind of confident
    claim Kairo is not allowed to make.
    """
    pairs = _candidates(db, project_id, mode, selected_ids or [])
    sources = available_fill_sources(check_web=check_web)
    fill_method, fill_reason = _fill_method(sources)

    estimated_scenes = max(1, round(target_seconds / max(1.0, average_scene_seconds)))
    usable = len(pairs)
    shortfall = max(0, estimated_scenes - usable)

    plan = MaterialPlan(
        mode=mode,  # type: ignore[arg-type]
        user_photo_count=sum(1 for a, _ in pairs if a.kind == "image"),
        user_video_count=sum(1 for a, _ in pairs if a.kind == "video"),
        used_photo_count=min(sum(1 for a, _ in pairs if a.kind == "image"), estimated_scenes),
        used_video_count=min(sum(1 for a, _ in pairs if a.kind == "video"), estimated_scenes),
        available_fill_sources=sources,
        provisional=True,
        estimated_scene_count=estimated_scenes,
        fill_counts={fill_method: shortfall} if shortfall else {},
    )
    if not usable:
        # Requirement 10: a user with nothing to upload must be told, in as
        # many words, that they can still make the video - the estimate
        # below reads as a list of things missing otherwise.
        plan.notes.append(
            "素材がなくても制作できます。必要な素材はKairoがすべて用意します。"
        )
    if shortfall:
        plan.notes.append(
            f"約{estimated_scenes}シーンの想定に対して素材が{usable}点のため、"
            f"およそ{shortfall}カットをKairoが用意する見込みです。{fill_reason}。"
        )
    elif usable:
        plan.notes.append(
            f"約{estimated_scenes}シーンの想定に対して素材が{usable}点あるため、"
            "ほとんどのカットをユーザー素材でまかなえる見込みです。"
        )
    if "web" not in sources:
        plan.notes.append("Web素材は利用できません（ネットワーク未接続、または取得に失敗）。")
    if "ai_generated" not in sources:
        plan.notes.append("AI画像生成モデル（Stable Diffusion）は未導入です。")

    unanalyzed = [a.id for a, _ in pairs if a.analysis_status != "done"]
    if unanalyzed:
        plan.notes.append(f"{len(unanalyzed)}点はまだ解析していません。制作開始時に解析します。")
    return plan


# ------------------------------------------------------------ persistence


def apply_plan(db, plan: MaterialPlan, scenes: list[Scene]) -> int:
    """Writes a plan's decisions onto the scene rows.

    The scene row - not the plan JSON - is what the asset stage reads, so
    this is the point at which a plan becomes the thing that will actually
    be rendered.
    """
    applied = 0
    for assignment in plan.assignments:
        if assignment.scene_index >= len(scenes):
            continue
        scene = scenes[assignment.scene_index]
        if assignment.origin == "user" and assignment.asset_id:
            scene.asset_source = "user"
            scene.user_asset_id = assignment.asset_id
            scene.user_asset_start = assignment.source_start
            scene.user_asset_end = assignment.source_end
            scene.material_origin = "user"
            scene.material_note = assignment.reason
            applied += 1
        elif scene.asset_source == "user" and scene.user_asset_id:
            # The user's material moved to a scene it fits better. Release
            # this one so it does not still claim a photo it no longer has;
            # the asset stage will fill it.
            scene.asset_source = "auto"
            scene.user_asset_id = None
            scene.user_asset_start = None
            scene.user_asset_end = None
            scene.material_origin = ""
            scene.material_note = ""
        # A scene that had no user material and still has none is left
        # exactly as it was, keeping whatever the asset stage produced for
        # it - a downloaded web image, or a composed background. Clearing
        # it here would make every re-plan re-download and re-encode
        # material that nothing about the plan actually changed.
    db.commit()
    return applied


def to_json(plan: MaterialPlan) -> str:
    return plan.model_dump_json()


def from_json(raw: str | None) -> MaterialPlan | None:
    if not raw:
        return None
    try:
        return MaterialPlan.model_validate(json.loads(raw))
    except Exception:
        return None
