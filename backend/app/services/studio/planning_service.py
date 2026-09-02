"""Strategy -> plan -> script -> scene design.

This is the part of the pipeline that decides what the video *is*. It
replaces the old "one instruction -> chapters -> narration lines" path for
studio runs, because that path had no opinion about short-form: it wrote
even-length explanatory beats, which is exactly the "60秒を埋めただけの
動画" section 22 rules out.

What changed, concretely:

* A **strategy** is produced first (section 19) and every later prompt is
  conditioned on it, so hook, pacing, subtitle policy and ending are
  decided once rather than re-improvised per chapter.
* Chapters became **acts** (掴み / 展開 / オチ) with explicit second
  budgets, so structure is imposed rather than hoped for.
* Scenes carry purpose, emotion, camera, transition, SFX and a *separate*
  subtitle line (section 20/25).
* `retime_scenes` reconciles the model's guessed durations with the target
  length and the strategy's per-scene bounds - a model asked for "about 60
  seconds" reliably returns something between 30 and 120, and the timeline
  has to be exact.

Existing rows (ProductionSpec / Chapter / Scene) are reused rather than a
parallel schema introduced, so the manual scene editor, the production API
and every existing view keep working against studio-produced projects.
"""
from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from app.models.production import Chapter, ProductionSpec, Scene
from app.schemas.production import PlanOutline
from app.schemas.studio import ProductionStrategy, ResearchResult, SceneSet, ShortFormScene
from app.services import llm_client
from app.services.json_extract import JSONExtractionError, parse_json_object

logger = logging.getLogger(__name__)


class PlanningError(RuntimeError):
    pass


_VISUAL_TYPES = (
    "ai_video, ai_image, photo, diagram, chart, map, text_animation, "
    "existing_video, existing_image, screen_recording"
)


def _ask_json(messages: list[dict], what: str, temperature: float = 0.4) -> dict:
    raw = llm_client.chat_completion(messages, temperature=temperature)
    try:
        return parse_json_object(raw)
    except JSONExtractionError as exc:
        raise PlanningError(f"{what}をJSONとして解釈できませんでした: {exc}") from exc


# ------------------------------------------------------------- strategy


def _strategy_prompt(
    instruction: str, duration_seconds: float, research: ResearchResult, orientation: str
) -> list[dict]:
    trends = research.trends
    orientation_label = {
        "vertical": "縦型9:16 (TikTok / YouTube Shorts / Reels)",
        "horizontal": "横型16:9",
        "square": "正方形1:1",
    }.get(orientation, "縦型9:16")

    research_block = (
        "【調査で分かった共通トレンド】\n"
        + "\n".join(f"- {p}" for p in trends.common_patterns[:8])
        + "\n\n【差別化の余地】\n"
        + "\n".join(f"- {d}" for d in trends.differentiation[:6])
    )

    system = (
        "あなたはショート動画の制作ディレクターです。依頼と調査結果から、"
        "この動画の制作戦略をJSONで出力してください。JSONオブジェクトのみを返してください。\n\n"
        "出力形式:\n"
        '{"title": "...", "concept": "...", "hook": "...", "pacing": "...", '
        '"scene_seconds_min": 2.0, "scene_seconds_max": 4.5, '
        '"subtitle_policy": "...", "audio_policy": "...", "bgm_mood": "gentle", '
        '"ending": "...", "differentiation": "...", '
        '"emotional_arc": ["...", "...", "..."], "visual_style": "..."}\n\n'
        "制約:\n"
        "- bgm_mood は gentle / bright / playful / tense / emotional / calm のいずれか。\n"
        "- hook は「最初の2〜3秒で何を見せるか」を具体的に書くこと。\n"
        "- differentiation は調査結果の模倣にならない独自性を書くこと。\n"
        "- emotional_arc は動画全体の感情の流れを3〜5個の単語で書くこと。"
    )
    user = (
        f"依頼: {instruction}\n"
        f"想定尺: 約{duration_seconds:.0f}秒\n"
        f"フォーマット: {orientation_label}\n\n"
        f"{research_block}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def generate_strategy(
    instruction: str,
    duration_seconds: float,
    research: ResearchResult,
    orientation: str = "vertical",
) -> ProductionStrategy:
    data = _ask_json(
        _strategy_prompt(instruction, duration_seconds, research, orientation), "制作戦略"
    )
    try:
        strategy = ProductionStrategy.model_validate(data)
    except ValidationError as exc:
        raise PlanningError(f"制作戦略の形式が不正です: {exc}") from exc

    # A model that returns min > max, or bounds that make the requested
    # length impossible, would poison every later stage. Clamp rather than
    # fail: the numbers are a preference, not the deliverable.
    strategy.scene_seconds_min = max(1.2, min(strategy.scene_seconds_min, 8.0))
    strategy.scene_seconds_max = max(
        strategy.scene_seconds_min + 0.5, min(strategy.scene_seconds_max, 12.0)
    )
    if not strategy.title:
        strategy.title = instruction[:40]
    return strategy


# ----------------------------------------------------------------- plan


def _plan_prompt(
    instruction: str, strategy: ProductionStrategy, duration_seconds: float
) -> list[dict]:
    system = (
        "あなたはショート動画の構成作家です。制作戦略に沿って、動画全体の企画と"
        "「幕(チャプター)」構成をJSONで出力してください。JSONオブジェクトのみを返してください。\n\n"
        "出力形式:\n"
        '{"title": "...", "target_audience": "...", "tone": "...", '
        '"chapters": [{"title": "...", "summary": "...", "seconds": 12}, ...]}\n\n'
        "制約:\n"
        "- 幕は3〜5個。必ず「掴み」から始め、最後は「オチ/余韻」で終わること。\n"
        "- 各幕の seconds の合計が目標尺とほぼ一致すること。\n"
        "- 最初の幕は3〜6秒程度の短い掴みにすること。"
    )
    user = (
        f"依頼: {instruction}\n"
        f"目標尺: {duration_seconds:.0f}秒\n\n"
        f"タイトル案: {strategy.title}\n"
        f"コンセプト: {strategy.concept}\n"
        f"Hook: {strategy.hook}\n"
        f"感情の流れ: {' → '.join(strategy.emotional_arc) or '未指定'}\n"
        f"終わり方: {strategy.ending}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def generate_plan(
    instruction: str, strategy: ProductionStrategy, duration_seconds: float
) -> tuple[PlanOutline, list[float]]:
    """Returns the plan plus a per-chapter second budget.

    The budget is normalised here rather than trusted: chapter seconds that
    sum to 38 for a 60-second brief would silently produce a short video.
    """
    data = _ask_json(_plan_prompt(instruction, strategy, duration_seconds), "企画")
    try:
        plan = PlanOutline.model_validate(data)
    except ValidationError as exc:
        raise PlanningError(f"企画の形式が不正です: {exc}") from exc

    raw_chapters = data.get("chapters", [])
    budgets: list[float] = []
    for i in range(len(plan.chapters)):
        value = 0.0
        if i < len(raw_chapters) and isinstance(raw_chapters[i], dict):
            try:
                value = float(raw_chapters[i].get("seconds") or 0)
            except (TypeError, ValueError):
                value = 0.0
        budgets.append(max(0.0, value))

    total = sum(budgets)
    if total <= 0:
        # No usable budget: weight the opening short and split the rest.
        n = len(plan.chapters)
        hook = min(5.0, duration_seconds * 0.12)
        rest = (duration_seconds - hook) / max(1, n - 1) if n > 1 else duration_seconds
        budgets = [hook] + [rest] * (n - 1)
    else:
        scale = duration_seconds / total
        budgets = [b * scale for b in budgets]

    return plan, budgets


# --------------------------------------------------------------- scenes


def _scene_prompt(
    plan: PlanOutline,
    strategy: ProductionStrategy,
    chapter_title: str,
    chapter_summary: str,
    target_seconds: float,
    is_first_chapter: bool,
    is_last_chapter: bool,
    previous_tail: str,
    used_visuals: list[str],
) -> list[dict]:
    role_note = ""
    if is_first_chapter:
        role_note = (
            f"この幕は動画の掴みです。最初のシーンで「{strategy.hook}」を必ず成立させ、"
            "視聴者が離脱しないようにしてください。"
        )
    elif is_last_chapter:
        role_note = (
            f"この幕は締めです。「{strategy.ending}」で終わり、"
            "可能なら冒頭につながる余韻を残してください。"
        )

    system = (
        "あなたはショート動画の脚本家兼絵コンテ作家です。指定された幕を、"
        "シーン単位で設計してJSONで出力してください。JSONオブジェクトのみを返してください。\n\n"
        "出力形式:\n"
        '{"scenes": [{"narration": "...", "subtitle": "...", "purpose": "...", '
        '"emotion": "...", "visual_type": "<type>", "visual_prompt": "...", '
        '"camera": "...", "sfx": "...", "transition": "cut", "continuity": "...", '
        '"duration": 3.0}, ...]}\n\n'
        f"visual_type は次のいずれか: {_VISUAL_TYPES}\n\n"
        "重要な制約:\n"
        "- narration は読み上げる文章、subtitle は画面に出す短い言葉です。同じにしないでください。\n"
        "- subtitle は最大16文字程度。長い説明は禁止です。\n"
        f"- 各シーンの duration は{strategy.scene_seconds_min:.1f}〜{strategy.scene_seconds_max:.1f}秒。\n"
        f"- この幕の合計が約{target_seconds:.0f}秒になるようシーン数を決めてください。\n"
        "- emotion はそのシーンで視聴者に抱かせたい感情を1語で書いてください。\n"
        "- camera は close-up / wide / zoom_in / zoom_out / pan_left / pan_right / static から選んでください。\n"
        "- sfx は不要なら空文字にしてください。使うなら pop / ding / whoosh / thud / sparkle / surprise から選んでください。\n"
        "- transition は cut / fade / quick_cut のいずれかです。\n"
        "- visual_prompt は画面に写るものを具体的に描写してください(文章ではなく描写)。\n"
        "- すでに使用済みの映像は繰り返さず、必ず別の画・別の角度にしてください。\n"
        "- 同じナレーション・同じ字幕のシーンを複数作らないでください。各シーンは必ず別の内容にしてください。\n"
        "- 尺を埋めるためにシーンを水増しするより、シーン数を減らして1つを長くしてください。"
    )
    user = (
        f"動画タイトル: {plan.title}\n"
        f"対象視聴者: {plan.target_audience}\n"
        f"トーン: {plan.tone}\n"
        f"映像スタイル: {strategy.visual_style}\n"
        f"字幕方針: {strategy.subtitle_policy}\n\n"
        f"この幕: {chapter_title}\n"
        f"幕の概要: {chapter_summary}\n"
        f"この幕の長さ: 約{target_seconds:.0f}秒\n"
        f"{role_note}\n"
        + (f"\n直前のシーンの状況: {previous_tail}" if previous_tail else "")
        # Repetition across chapters was by far the most common
        # quality-check finding, because each chapter was written without
        # knowing what the earlier ones had already put on screen.
        + (
            "\n\nすでに使用済みの映像(繰り返さないでください):\n"
            + "\n".join(f"- {v}" for v in used_visuals[-12:])
            if used_visuals
            else ""
        )
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def generate_scenes(
    plan: PlanOutline,
    strategy: ProductionStrategy,
    chapter_title: str,
    chapter_summary: str,
    target_seconds: float,
    *,
    is_first_chapter: bool = False,
    is_last_chapter: bool = False,
    previous_tail: str = "",
    used_visuals: list[str] | None = None,
) -> list[ShortFormScene]:
    data = _ask_json(
        _scene_prompt(
            plan,
            strategy,
            chapter_title,
            chapter_summary,
            target_seconds,
            is_first_chapter,
            is_last_chapter,
            previous_tail,
            used_visuals or [],
        ),
        "シーン設計",
    )
    try:
        scene_set = SceneSet.model_validate(data)
    except ValidationError as exc:
        raise PlanningError(f"シーン設計の形式が不正です: {exc}") from exc

    for scene in scene_set.scenes:
        # A subtitle is required for short-form; fall back to a trimmed
        # narration rather than leaving the frame silent-and-blank.
        if not scene.subtitle.strip():
            scene.subtitle = scene.narration.strip()[:16]
        if not scene.visual_prompt.strip():
            scene.visual_prompt = scene.narration.strip()[:80]

    return _deduplicate(scene_set.scenes, target_seconds)


def _scene_key(scene: ShortFormScene) -> str:
    return f"{scene.subtitle.strip()}|{scene.narration.strip()}"


def _deduplicate(scenes: list[ShortFormScene], target_seconds: float) -> list[ShortFormScene]:
    """Drops scenes that repeat an earlier one verbatim.

    Asked to fill a fixed number of seconds, a small model reliably pads by
    emitting the same beat several times - six scenes all captioned
    「喜び」 with the same narration. The prompt asks it not to, but a
    prompt is not a guarantee, so the duplicates are removed here and the
    time they held is given back to the beats that survive (the caller's
    `retime_scenes` then fits the result to the target).

    Only exact repeats of *both* the caption and the narration are dropped:
    two scenes that say different things about a similar image are a
    legitimate pair of beats, not padding.
    """
    seen: set[str] = set()
    kept: list[ShortFormScene] = []
    dropped_seconds = 0.0

    for scene in scenes:
        key = _scene_key(scene)
        if key in seen:
            dropped_seconds += scene.duration
            continue
        seen.add(key)
        kept.append(scene)

    if not kept:
        return scenes[:1]

    if dropped_seconds > 0:
        logger.info(
            "Dropped %d duplicate scene(s) (%.1fs) from a chapter",
            len(scenes) - len(kept),
            dropped_seconds,
        )
        share = dropped_seconds / len(kept)
        for scene in kept:
            # Capped so reclaiming time from a heavily-padded chapter can't
            # produce one enormous shot.
            scene.duration = min(scene.duration + share, scene.duration * 2, 12.0)

    return kept


# ------------------------------------------------------------- retiming


def retime_scenes(
    scenes: list[Scene], target_seconds: float, strategy: ProductionStrategy
) -> None:
    """Scales scene durations so the video is actually the requested length.

    Applied proportionally and then clamped to the strategy's bounds, so
    the *relative* shape the writer intended (a beat that should linger
    still lingers) survives while the total becomes exact. Mutates in
    place; the caller commits.
    """
    if not scenes:
        return
    total = sum(s.estimated_duration for s in scenes)
    if total <= 0:
        even = target_seconds / len(scenes)
        for scene in scenes:
            scene.estimated_duration = even
        return

    scale = target_seconds / total
    for scene in scenes:
        scaled = scene.estimated_duration * scale
        scene.estimated_duration = round(
            max(strategy.scene_seconds_min, min(scaled, strategy.scene_seconds_max)), 2
        )

    # Clamping moves the total again; push the remaining difference onto
    # the longest scenes, which absorb it least noticeably.
    drift = target_seconds - sum(s.estimated_duration for s in scenes)
    if abs(drift) > 0.05:
        adjustable = sorted(scenes, key=lambda s: -s.estimated_duration)
        per = drift / len(adjustable)
        for scene in adjustable:
            scene.estimated_duration = round(max(1.0, scene.estimated_duration + per), 2)

    recompute_start_times(scenes)


def recompute_start_times(scenes: list[Scene]) -> None:
    cursor = 0.0
    for scene in scenes:
        scene.start_time = round(cursor, 3)
        cursor += scene.estimated_duration


# ------------------------------------------------------------ persistence


def persist_plan(
    db,
    project_id: str,
    instruction: str,
    duration_seconds: float,
    plan: PlanOutline,
    strategy: ProductionStrategy,
    chapter_scenes: list[tuple[Chapter, list[ShortFormScene]]],
) -> list[Scene]:
    """Writes the designed video into the existing production tables and
    returns the scenes in playback order."""
    spec = db.get(ProductionSpec, project_id)
    if spec is None:
        spec = ProductionSpec(project_id=project_id)
        db.add(spec)
    spec.instruction = instruction
    spec.target_duration_minutes = duration_seconds / 60.0
    spec.title = plan.title
    spec.target_audience = plan.target_audience
    spec.tone = plan.tone

    ordered: list[Scene] = []
    for chapter, designs in chapter_scenes:
        for j, design in enumerate(designs):
            scene = Scene(
                chapter_id=chapter.id,
                project_id=project_id,
                order_index=j,
                narration=design.narration,
                visual_type=design.visual_type,
                visual_prompt=design.visual_prompt,
                estimated_duration=design.duration,
                status="pending",
                purpose=design.purpose,
                emotion=design.emotion,
                camera=design.camera,
                subtitle_text=design.subtitle,
                sfx=design.sfx,
                bgm_cue=strategy.bgm_mood,
                transition=design.transition,
                continuity=design.continuity,
                asset_source="auto",
            )
            db.add(scene)
            ordered.append(scene)

    if ordered:
        ordered[0].is_hook = True
    db.commit()
    for scene in ordered:
        db.refresh(scene)
    return ordered


def clear_previous_plan(db, project_id: str) -> None:
    db.query(Scene).filter(Scene.project_id == project_id).delete()
    db.query(Chapter).filter(Chapter.project_id == project_id).delete()
    db.commit()


def ordered_scenes(db, project_id: str) -> list[Scene]:
    """Every scene of a project in playback order.

    Ordering is (chapter.order_index, scene.order_index): `Scene.order_index`
    restarts at 0 in each chapter, so sorting on it alone interleaves the
    acts - which is how a hook ends up in the middle of a video.
    """
    rows = (
        db.query(Scene, Chapter.order_index)
        .join(Chapter, Scene.chapter_id == Chapter.id)
        .filter(Scene.project_id == project_id)
        .order_by(Chapter.order_index, Scene.order_index)
        .all()
    )
    return [scene for scene, _ in rows]


def strategy_from_json(raw: str | None) -> ProductionStrategy:
    if not raw:
        return ProductionStrategy()
    try:
        return ProductionStrategy.model_validate(json.loads(raw))
    except Exception:
        return ProductionStrategy()
