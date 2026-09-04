"""The AI edit director: deciding what kind of video this is, before cutting.

Requirement 1 asks for a stage that runs *before* editing and settles the
genre, audience, length, orientation, mood, tempo, story structure, caption
style, font direction, transition policy, music policy and colour. This is
that stage, and its output is an `EditDirective` every later stage reads.

It is built in four layers, each of which can only refine the one below:

1. **The edit style** for the genre (`edit_styles.py`) - format conventions
   as data. Always present, so a directive exists even with no model, no
   trend data and no material.
2. **The genre profile** Trend Intelligence derived - real measured
   tendencies (duration, scene seconds, BPM range, caption density) where
   they exist. Applied only where the profile actually has a value, so an
   empty profile changes nothing.
3. **The material** the user uploaded - the reality check. Four photos
   cannot support a six-act structure or 1.5-second cuts, dark footage
   should not be graded darker, and footage with no motion wants longer
   holds. This layer is the difference between a template and a decision.
4. **The local model**, last and optional. It may adjust a bounded set of
   fields (mood, tempo, colour, caption density, transition appetite, font
   feel, hook line) and must justify each; anything it returns outside the
   allowed vocabulary is discarded rather than coerced.

`decided_by` records how far up that stack the directive actually got, so
the UI never presents a defaults-only directive as an AI judgement.
"""
from __future__ import annotations

import json
import logging

from app.schemas.edit_style import (
    COLOR_GRADE_LABELS,
    PLATFORM_LABELS,
    STYLE_LABELS,
    EditDirective,
)
from app.schemas.material import MaterialAnalysis
from app.schemas.trend import GenreProfileData, TrendContext
from app.services import llm_client
from app.services.json_extract import JSONExtractionError, parse_json_object
from app.services.studio import edit_styles, platform_presets
from app.services.trends import genre as genre_service

logger = logging.getLogger(__name__)

_TEMPOS = ("slow", "medium", "fast")
_DENSITIES = ("minimal", "low", "medium", "high")
_ANIMATIONS = ("none", "fade", "pop", "slide_up")


# --------------------------------------------------------------- layer 2


def _apply_profile(directive: EditDirective, profile: GenreProfileData | None) -> None:
    """Lays measured genre tendencies over the style preset.

    Only fields the profile actually filled in are used. A profile derived
    from thin evidence leaves most of itself empty on purpose (see
    schemas/trend.py), and treating an empty field as "0 seconds" would be
    worse than ignoring it.
    """
    if profile is None:
        return

    if profile.scene_seconds and profile.scene_seconds > 0.4:
        before = directive.scene_seconds
        # Blended rather than replaced: the style's own tempo is a
        # deliberate choice about how this *kind* of video is cut, and the
        # profile is evidence about the genre. Neither should win outright.
        directive.scene_seconds = round((before + float(profile.scene_seconds)) / 2.0, 2)
        if abs(directive.scene_seconds - before) >= 0.2:
            directive.notes.append(
                f"1カット{before:.1f}秒→{directive.scene_seconds:.1f}秒"
                f"（{directive.genre_label}ジャンルの傾向{profile.scene_seconds:.1f}秒を反映）"
            )

    if profile.hook_seconds and profile.hook_seconds > 0.5:
        directive.hook_seconds = round(float(profile.hook_seconds), 2)

    if profile.cut_tempo in _TEMPOS:
        if profile.cut_tempo != directive.tempo:
            directive.notes.append(
                f"テンポ: {directive.tempo}→{profile.cut_tempo}（ジャンル傾向）"
            )
            directive.tempo = profile.cut_tempo  # type: ignore[assignment]

    if profile.subtitle_density in _DENSITIES:
        directive.subtitle.density = profile.subtitle_density  # type: ignore[assignment]
        directive.subtitle.coverage = {
            "minimal": 0.3,
            "low": 0.5,
            "medium": 0.72,
            "high": 0.92,
        }[profile.subtitle_density]
    if profile.subtitle_position in ("top", "middle", "bottom"):
        directive.subtitle.position = profile.subtitle_position  # type: ignore[assignment]
    if profile.subtitle_style in ("outline", "box", "plain"):
        directive.subtitle.style = profile.subtitle_style  # type: ignore[assignment]

    if profile.font_style:
        for tag in profile.font_style:
            if tag and tag not in directive.font.wanted:
                directive.font.wanted.append(tag)

    if profile.bgm_mood:
        directive.audio.bgm_mood = profile.bgm_mood
    if len(profile.bgm_bpm_range or []) == 2:
        directive.audio.bgm_bpm_range = [float(x) for x in profile.bgm_bpm_range]

    # Transitions the profile observed are *added* to what the style
    # allows, never substituted for it: a style that deliberately refuses
    # slides should not start sliding because the genre often does.
    for name in profile.transitions or []:
        mapped = _TRANSITION_ALIASES.get(name.strip().lower())
        if mapped and mapped not in directive.transitions.allowed:
            directive.transitions.allowed.append(mapped)  # type: ignore[arg-type]


_TRANSITION_ALIASES: dict[str, str] = {
    "cut": "cut",
    "カット": "cut",
    "fade": "fade",
    "フェード": "fade",
    "dissolve": "dissolve",
    "cross dissolve": "dissolve",
    "crossfade": "dissolve",
    "ディゾルブ": "dissolve",
    "dip_to_black": "dip_to_black",
    "dip to black": "dip_to_black",
    "黒落ち": "dip_to_black",
    "slide": "slide_left",
    "スライド": "slide_left",
    "push": "push_left",
    "プッシュ": "push_left",
    "zoom": "zoom",
    "ズーム": "zoom",
    "match_cut": "match_cut",
    "match cut": "match_cut",
    "マッチカット": "match_cut",
    "quick_cut": "cut",
}


# --------------------------------------------------------------- layer 3


def _summarise_material(analyses: list[MaterialAnalysis]) -> dict:
    """What the uploaded material is like, as numbers the director can act on."""
    photos = [a for a in analyses if a.kind == "image"]
    videos = [a for a in analyses if a.kind == "video"]
    brightness = [a.brightness for a in analyses if a.brightness is not None]
    motion = [a.motion for a in videos if a.motion is not None]
    footage_seconds = sum(max(0.0, a.duration) for a in videos)
    tags: list[str] = []
    for a in analyses:
        for t in a.tags:
            if t not in tags:
                tags.append(t)
    return {
        "count": len(analyses),
        "photos": len(photos),
        "videos": len(videos),
        "footage_seconds": round(footage_seconds, 1),
        "mean_brightness": round(sum(brightness) / len(brightness), 3) if brightness else None,
        "mean_motion": round(sum(motion) / len(motion), 3) if motion else None,
        "vertical": sum(1 for a in analyses if a.orientation == "vertical"),
        "horizontal": sum(1 for a in analyses if a.orientation == "horizontal"),
        "tags": tags[:20],
        "analyzed_by": analyses[0].analyzed_by if analyses else "",
    }


def _apply_material(directive: EditDirective, summary: dict) -> None:
    """The reality check: fits the directive to the material that exists.

    Every adjustment here is one a human editor makes without thinking -
    you cannot cut every 1.5 seconds with six photos, you do not push a
    dark clip darker, and a static shot needs to be held longer than a
    moving one. Doing it in the directive rather than at render time is
    what makes it visible to the user and to the review.
    """
    count = int(summary.get("count") or 0)
    if not count:
        directive.notes.append(
            "ユーザー素材がないため、AI生成・Web素材で構成する前提で方針を立てました"
        )
        return

    photos = int(summary.get("photos") or 0)
    videos = int(summary.get("videos") or 0)
    footage = float(summary.get("footage_seconds") or 0.0)
    target = max(4.0, directive.duration_seconds)

    # --- how many cuts the material can actually support ---------------
    # A photo can become several shots (different crops of the same Ken
    # Burns move read as one shot, so we count one), and footage can be cut
    # into roughly one shot per scene_seconds of runtime.
    supportable = photos + max(videos, int(footage / max(2.0, directive.scene_seconds)))
    wanted_cuts = int(target / max(0.8, directive.scene_seconds))
    # 1.15, not 1.6. At 1.6, eight photos and a 30-second short did not
    # trigger this at all - twelve wanted cuts against eight of material
    # sat just inside the threshold - and the eight uncovered beats were
    # filled from a web image search. A third more cuts than material is
    # already the point where filling starts to dominate the video.
    if supportable and wanted_cuts > supportable * 1.15:
        # Not enough distinct material: hold each shot longer rather than
        # showing the same picture four times.
        needed = round(target / max(1, supportable), 2)
        new_seconds = min(directive.scene_seconds_max, max(directive.scene_seconds, needed * 0.8))
        if new_seconds - directive.scene_seconds >= 0.2:
            directive.notes.append(
                f"素材が{supportable}カット相当のため、1カットを"
                f"{directive.scene_seconds:.1f}秒→{new_seconds:.1f}秒に伸ばします"
            )
            directive.scene_seconds = round(new_seconds, 2)
            directive.scene_seconds_min = round(
                min(directive.scene_seconds_min + 0.4, directive.scene_seconds), 2
            )
    elif supportable > wanted_cuts * 2 and directive.tempo != "fast":
        directive.notes.append(
            f"使える素材が{supportable}点あるため、カットを短めにして"
            "できるだけ多くの素材を見せます"
        )
        directive.scene_seconds = round(
            max(directive.scene_seconds_min, directive.scene_seconds * 0.85), 2
        )

    # --- structure has to fit the material -----------------------------
    # Requirement 8: do not force a structure the material cannot fill.
    max_beats = max(2, min(len(directive.story), supportable // 2 or 2))
    if max_beats < len(directive.story):
        dropped = [b.label for b in directive.story[max_beats - 1 : -1]]
        # The first and the last beat are kept - a video still needs an
        # opening and an ending - and the middle is collapsed.
        kept = directive.story[: max_beats - 1] + [directive.story[-1]]
        total = sum(b.share for b in kept) or 1.0
        for beat in kept:
            beat.share = round(beat.share / total, 3)
        directive.story = kept
        if dropped:
            directive.notes.append(
                f"素材が足りないため、構成を{len(kept)}段階に簡略化しました"
                f"（省略: {' / '.join(dropped)}）"
            )

    # --- photo-heavy material wants more movement ----------------------
    if photos and photos >= max(1, videos * 3):
        directive.photo_motion.intensity = round(
            min(1.5, directive.photo_motion.intensity * 1.15), 2
        )
        directive.photo_motion.reason += "（写真中心の構成のため、動きをやや強めます）"
        directive.notes.append(
            f"写真{photos}点が中心のため、Ken Burnsの動きを強めて静止感を避けます"
        )

    # --- brightness: never grade against the material ------------------
    brightness = summary.get("mean_brightness")
    if brightness is not None:
        if brightness < 0.28 and directive.color.brightness < 0:
            directive.color = edit_styles.grade(directive.color.id, 0.4)
            directive.color.brightness = abs(directive.color.brightness)
            directive.notes.append(
                f"素材が暗め（平均{brightness:.2f}）なので、暗くする色調整は弱め、"
                "明るさを持ち上げる方向に切り替えました"
            )
        elif brightness > 0.72 and directive.color.brightness > 0:
            directive.color.brightness = 0.0
            directive.notes.append(
                f"素材が明るい（平均{brightness:.2f}）ため、これ以上明るくしません"
            )

    # --- motion: static footage needs longer holds ---------------------
    motion = summary.get("mean_motion")
    if motion is not None and videos:
        if motion < 0.02:
            directive.notes.append(
                "動きの少ない映像が中心のため、カットを詰めすぎず写真的に見せます"
            )
            directive.photo_motion.intensity = round(
                min(1.5, directive.photo_motion.intensity * 1.2), 2
            )
        elif motion > 0.25:
            directive.notes.append(
                "動きの大きい映像が中心のため、Transitionを控えてカットで繋ぎます"
            )
            directive.transitions.max_ratio = round(
                max(0.08, directive.transitions.max_ratio * 0.6), 2
            )

    # --- orientation mismatch is worth saying out loud -----------------
    if directive.orientation == "vertical" and int(summary.get("horizontal") or 0) > int(
        summary.get("vertical") or 0
    ):
        directive.notes.append(
            "横向きの素材が多いため、縦型では上下を切り出して画面いっぱいに使います"
        )

    directive.material_summary = (
        f"写真{photos}点 / 動画{videos}点（合計{footage:.0f}秒）"
        + (f" / 平均明るさ{brightness:.2f}" if brightness is not None else "")
        + (f" / 平均動き{motion:.2f}" if motion is not None else "")
    )


# --------------------------------------------------------------- layer 4


def _ai_prompt(directive: EditDirective, instruction: str, summary: dict) -> list[dict]:
    system = (
        "あなたは動画編集ディレクターです。依頼内容と素材の状況を見て、"
        "編集方針の調整案をJSONで返してください。JSONオブジェクトのみを出力すること。\n\n"
        "出力形式:\n"
        '{"mood": "...", "tempo": "medium", "color_grade": "clean", '
        '"subtitle_density": "medium", "subtitle_animation": "fade", '
        '"transition_appetite": "low", "font_feel": "...", '
        '"hook": "...", "ending": "...", "audience": "...", "concept": "...", '
        '"reason": "..."}\n\n'
        "制約:\n"
        "- tempo は slow / medium / fast のいずれか。\n"
        "- color_grade は none / clean / warm / cinematic / bright / moody / retro / travel のいずれか。\n"
        "- subtitle_density は minimal / low / medium / high のいずれか。\n"
        "- subtitle_animation は none / fade / pop / slide_up のいずれか。\n"
        "- transition_appetite は none / low / medium / high のいずれか。"
        "画面切り替えは意味のある箇所だけに使うため、迷ったら low を選ぶこと。\n"
        "- font_feel は書体の印象を日本語で短く（例: 細めの明朝で上品に / 太いゴシックで力強く）。\n"
        "- hook は最初の3秒で何を見せるかを具体的に。\n"
        "- 素材にないものを前提にした方針は書かないこと。\n"
        "- reason には、この方針にした理由を1〜2文で書くこと。"
    )
    user = (
        f"依頼: {instruction}\n"
        f"想定尺: {directive.duration_seconds:.0f}秒 / "
        f"{'縦型9:16' if directive.orientation == 'vertical' else ('横型16:9' if directive.orientation == 'horizontal' else '正方形1:1')}\n"
        f"配信先: {directive.platform_label}\n"
        f"ジャンル判定: {directive.genre_label}\n"
        f"適用中の編集スタイル: {directive.style_label}（{directive.mood} / テンポ{directive.tempo}）\n"
        f"現在の色: {COLOR_GRADE_LABELS.get(directive.color.id, directive.color.id)}\n"
        f"現在の字幕量: {directive.subtitle.density}\n\n"
        f"素材の状況: {directive.material_summary or 'ユーザー素材なし'}\n"
        f"素材から読み取れた内容: {', '.join(summary.get('tags') or []) or '（タグなし）'}\n"
        f"構成案: {' → '.join(b.label for b in directive.story)}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


_APPETITE_RATIO = {"none": 0.0, "low": 0.15, "medium": 0.28, "high": 0.4}


def _apply_ai(directive: EditDirective, data: dict) -> bool:
    """Applies the model's adjustments. Returns whether anything changed.

    Every field is validated against the same vocabulary the rest of Kairo
    uses; an unrecognised value is dropped, never coerced into the nearest
    option. A model that answers "テンポ: すごく速い" gets no tempo change,
    which is correct - it did not answer the question that was asked.
    """
    changed = False

    mood = str(data.get("mood") or "").strip()[:40]
    if mood and mood != directive.mood:
        directive.mood = mood
        changed = True

    audience = str(data.get("audience") or "").strip()[:60]
    if audience:
        directive.audience = audience
        changed = True

    concept = str(data.get("concept") or "").strip()[:200]
    if concept:
        directive.concept = concept
        changed = True

    tempo = str(data.get("tempo") or "").strip().lower()
    if tempo in _TEMPOS and tempo != directive.tempo:
        # Tempo is a real edit decision, so it moves the cut length too -
        # a "fast" directive whose scenes stayed at 4 seconds would be a
        # label with nothing behind it.
        factor = {"slow": 1.25, "medium": 1.0, "fast": 0.8}[tempo] / {
            "slow": 1.25,
            "medium": 1.0,
            "fast": 0.8,
        }[directive.tempo]
        directive.notes.append(f"AI判断でテンポを{directive.tempo}→{tempo}に変更")
        directive.tempo = tempo  # type: ignore[assignment]
        directive.scene_seconds = round(
            max(
                directive.scene_seconds_min,
                min(directive.scene_seconds_max, directive.scene_seconds * factor),
            ),
            2,
        )
        changed = True

    grade_id = str(data.get("color_grade") or "").strip().lower()
    if grade_id in edit_styles.COLOR_GRADES and grade_id != directive.color.id:
        directive.notes.append(
            f"AI判断で色味を{COLOR_GRADE_LABELS.get(directive.color.id, directive.color.id)}"
            f"→{COLOR_GRADE_LABELS.get(grade_id, grade_id)}に変更"
        )
        directive.color = edit_styles.grade(grade_id, directive.color.strength or 1.0)
        changed = True

    density = str(data.get("subtitle_density") or "").strip().lower()
    if density in _DENSITIES and density != directive.subtitle.density:
        directive.subtitle.density = density  # type: ignore[assignment]
        directive.subtitle.coverage = {
            "minimal": 0.3,
            "low": 0.5,
            "medium": 0.72,
            "high": 0.92,
        }[density]
        directive.notes.append(f"AI判断で字幕量を{density}に変更")
        changed = True

    animation = str(data.get("subtitle_animation") or "").strip().lower()
    if animation in _ANIMATIONS:
        directive.subtitle.animation = animation  # type: ignore[assignment]
        changed = True

    appetite = str(data.get("transition_appetite") or "").strip().lower()
    if appetite in _APPETITE_RATIO:
        # Capped by the style: a style that says "never more than 20% of
        # boundaries" is a design rule, not a starting suggestion.
        ceiling = directive.transitions.max_ratio
        directive.transitions.max_ratio = round(min(ceiling, _APPETITE_RATIO[appetite]), 2)
        if _APPETITE_RATIO[appetite] < ceiling:
            directive.notes.append(
                f"AI判断で画面切り替えの割合を最大{directive.transitions.max_ratio * 100:.0f}%に抑制"
            )
        changed = True

    font_feel = str(data.get("font_feel") or "").strip()[:80]
    if font_feel:
        directive.font.reason = f"{font_feel}（AI判断）"
        # The feel also has to move the ranking, or it is decoration.
        low = font_feel.casefold()
        for word, tag in (
            ("明朝", "serif"), ("セリフ", "serif"), ("serif", "serif"),
            ("ゴシック", "sans"), ("sans", "sans"),
            ("丸", "rounded"), ("rounded", "rounded"),
            ("太", "bold"), ("力強", "bold"), ("bold", "bold"),
            ("細", "light"), ("繊細", "light"), ("light", "light"),
            ("上品", "elegant"), ("高級", "elegant"), ("エレガント", "elegant"),
            ("手書き", "handwritten"),
        ):
            if word in low and tag not in directive.font.wanted:
                directive.font.wanted.append(tag)
        if "上品" in low or "高級" in low:
            directive.font.luxury = max(directive.font.luxury, 0.8)
        if "力強" in low or "インパクト" in low:
            directive.font.impact = max(directive.font.impact, 0.85)
        changed = True

    hook = str(data.get("hook") or "").strip()[:200]
    if hook:
        directive.hook_direction = hook
        changed = True

    ending = str(data.get("ending") or "").strip()[:200]
    if ending:
        directive.ending_direction = ending
        changed = True

    directive.ai_note = str(data.get("reason") or "").strip()[:300]
    return changed


# ------------------------------------------------------------------ entry


def decide(
    instruction: str,
    *,
    duration_seconds: float,
    orientation: str,
    width: int,
    height: int,
    trend: TrendContext | None = None,
    analyses: list[MaterialAnalysis] | None = None,
    platform: str = "generic",
    style_override: str | None = None,
    use_ai: bool = True,
) -> EditDirective:
    """Produces the directive this production will be edited to.

    Never raises: a directive is a prerequisite for every later stage, so
    an unreachable model, an empty library or unanalysed material all
    degrade to a lower `decided_by` rather than failing the run.
    """
    analyses = analyses or []

    # --- layer 1: the style -------------------------------------------
    genre = (trend.genre if trend and trend.genre else "") or genre_service.classify_instruction(
        instruction
    )
    named = style_override or edit_styles.style_from_instruction(instruction)
    style = (
        edit_styles.STYLE_BY_ID.get(named)
        if named in edit_styles.STYLE_BY_ID
        else edit_styles.style_for_genre(genre)
    )
    directive = edit_styles.base_directive(style)
    directive.genre = genre
    directive.genre_label = genre_service.label(genre)
    directive.duration_seconds = max(4.0, float(duration_seconds))
    directive.orientation = orientation if orientation in (
        "vertical", "horizontal", "square"
    ) else "vertical"  # type: ignore[assignment]
    directive.width = width
    directive.height = height
    if named and named in edit_styles.STYLE_BY_ID:
        directive.notes.insert(
            0, f"依頼文から「{STYLE_LABELS.get(named, named)}」スタイルを選びました"
        )
    else:
        directive.notes.insert(
            0,
            f"{directive.genre_label}ジャンルの標準として"
            f"「{directive.style_label}」スタイルを選びました",
        )

    # --- platform ------------------------------------------------------
    platform_presets.apply(directive, platform)

    # --- layer 2: the genre profile -----------------------------------
    profile = trend.profile if trend is not None else None
    if profile is not None:
        _apply_profile(directive, profile)
        directive.decided_by = "defaults+profile"

    # --- layer 3: the material ----------------------------------------
    summary = _summarise_material(analyses)
    _apply_material(directive, summary)

    # Bounds have to hold after everything above moved them around.
    directive.scene_seconds = round(
        max(directive.scene_seconds_min, min(directive.scene_seconds_max, directive.scene_seconds)),
        2,
    )
    directive.hook_seconds = round(max(1.0, min(directive.hook_seconds, 6.0)), 2)

    # --- layer 4: the model -------------------------------------------
    if use_ai:
        try:
            raw = llm_client.chat_completion(
                _ai_prompt(directive, instruction, summary), temperature=0.35
            )
            data = parse_json_object(raw)
        except (
            JSONExtractionError,
            llm_client.LLMUnavailableError,
            llm_client.LLMTimeoutError,
            llm_client.LLMResponseError,
            llm_client.LLMNotReadyError,
        ) as exc:
            logger.info("Edit director AI pass unavailable: %s", exc)
            data = None
        except Exception:  # noqa: BLE001 - a directive must always exist
            logger.exception("Edit director AI pass failed")
            data = None
        if data:
            if _apply_ai(directive, data):
                directive.decided_by = (
                    "defaults+profile+ai" if profile is not None else "defaults+ai"
                )

    # Final clamps, again - the AI pass can move tempo and therefore cuts.
    directive.scene_seconds = round(
        max(directive.scene_seconds_min, min(directive.scene_seconds_max, directive.scene_seconds)),
        2,
    )
    if not directive.hook_direction:
        directive.hook_direction = (
            profile.hook_patterns[0]
            if profile and profile.hook_patterns
            else "最初の3秒で一番強い画を見せる"
        )
    directive.color.label = COLOR_GRADE_LABELS.get(directive.color.id, directive.color.id)
    directive.platform_label = PLATFORM_LABELS.get(directive.platform, "指定なし")
    return directive


# ------------------------------------------------------------ persistence


def to_json(directive: EditDirective) -> str:
    return json.dumps(directive.model_dump(), ensure_ascii=False)


def from_json(raw: str | None) -> EditDirective | None:
    if not raw:
        return None
    try:
        return EditDirective.model_validate(json.loads(raw))
    except Exception:  # noqa: BLE001
        logger.info("Could not restore an EditDirective from stored JSON")
        return None


def summary_lines(directive: EditDirective) -> list[str]:
    """The directive as the production log prints it.

    One line per decision the brief asks the user to be able to see, in the
    order the "今回のKairo編集方針" panel shows them.
    """
    return [
        f"ジャンル: {directive.genre_label}",
        f"編集スタイル: {directive.style_label}（{directive.mood}）",
        f"配信先: {directive.platform_label}",
        f"尺 / 画面: {directive.duration_seconds:.0f}秒 / {directive.width}x{directive.height}",
        f"テンポ: {directive.tempo}（1カット約{directive.scene_seconds:.1f}秒）",
        f"構成: {' → '.join(b.label for b in directive.story)}",
        f"字幕: {directive.subtitle.density}（{directive.subtitle.position} / "
        f"{directive.subtitle.style} / アニメーション{directive.subtitle.animation}）",
        f"フォント方針: {directive.font.reason}",
        f"画面切り替え: 既定{directive.transitions.default} / "
        f"最大{directive.transitions.max_ratio * 100:.0f}%のカットのみ",
        f"色味: {directive.color.label}",
        f"BGM: {directive.audio.bgm_mood}"
        f"（{directive.audio.bgm_bpm_range[0]:.0f}-{directive.audio.bgm_bpm_range[1]:.0f} BPM）",
        f"写真の動き: 強さ{directive.photo_motion.intensity:.2f}",
    ]
