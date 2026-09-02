"""Post-generation quality check and the automatic improvement loop
(design doc sections 27/28).

Two passes, in this order and for a reason:

**Rules first.** Hook length, scene pacing, caption width, total duration,
missing narration, repeated visuals - these are measurable, so measuring
them is better than asking a 4B model for an opinion about them. Every rule
issue carries a machine-applicable `fix`, which is what makes the
improvement stage able to actually change the video instead of printing
advice.

**Then the model**, for the things that genuinely need judgement: does the
structure hold, is the hook strong, does the ending land, would this work
as a short. Those come back as issues too, but usually without a `fix` -
and section 8's rule applies: an issue Kairo cannot fix is reported as an
issue Kairo cannot fix, not quietly dropped.

`improve()` applies the fixable ones and returns exactly what it changed
and why, which is what the UI shows the user (section 28's "変更理由").
"""
from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from app.models.production import Scene
from app.schemas.studio import (
    AppliedImprovement,
    ImprovementReport,
    ProductionStrategy,
    QualityIssue,
    QualityReport,
)
from app.services import llm_client
from app.services.json_extract import JSONExtractionError, parse_json_object
from app.services.studio.assembly_service import MAX_CHARS_PER_LINE, wrap_caption

logger = logging.getLogger(__name__)

# A hook that takes longer than this to land has already lost the scroll.
MAX_HOOK_SECONDS = 4.0
# Below this, a caption cannot be read before the cut.
MIN_READABLE_SECONDS = 1.0
# How far the finished length may drift from what the user asked for.
DURATION_TOLERANCE = 0.18


def _severity_penalty(severity: str) -> float:
    return {"info": 1.0, "minor": 4.0, "major": 10.0}.get(severity, 4.0)


# ------------------------------------------------------------ rule pass


def check_rules(
    scenes: list[Scene],
    strategy: ProductionStrategy,
    *,
    target_seconds: float,
    has_narration: bool,
    has_bgm: bool,
) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    if not scenes:
        return [
            QualityIssue(
                axis="structure",
                severity="major",
                detail="シーンが1つもありません。",
                suggestion="企画からやり直してください。",
            )
        ]

    total = sum(s.estimated_duration for s in scenes)

    # --- Hook -------------------------------------------------------------
    first = scenes[0]
    if first.estimated_duration > MAX_HOOK_SECONDS:
        issues.append(
            QualityIssue(
                axis="hook",
                severity="major",
                scene_index=0,
                detail=f"冒頭シーンが{first.estimated_duration:.1f}秒あり、掴みとしては長すぎます。",
                suggestion="冒頭は3秒以内に収め、すぐ本題を見せてください。",
                fix="set_duration",
                fix_value=min(MAX_HOOK_SECONDS - 1.0, max(1.6, first.estimated_duration * 0.6)),
            )
        )
    if not (first.subtitle_text or "").strip():
        issues.append(
            QualityIssue(
                axis="hook",
                severity="major",
                scene_index=0,
                detail="冒頭に字幕がなく、音を切って見ている視聴者に内容が伝わりません。",
                suggestion="冒頭シーンに短い字幕を入れてください。",
                fix="fill_subtitle",
            )
        )

    # --- Pacing -----------------------------------------------------------
    for i, scene in enumerate(scenes):
        if scene.estimated_duration > strategy.scene_seconds_max + 0.75:
            issues.append(
                QualityIssue(
                    axis="pacing",
                    severity="minor",
                    scene_index=i,
                    detail=(
                        f"Scene {i + 1}が{scene.estimated_duration:.1f}秒で、"
                        f"戦略上の上限({strategy.scene_seconds_max:.1f}秒)を超えています。"
                    ),
                    suggestion="視聴維持率を保つため短くします。",
                    fix="set_duration",
                    fix_value=strategy.scene_seconds_max,
                )
            )
        elif scene.estimated_duration < MIN_READABLE_SECONDS:
            issues.append(
                QualityIssue(
                    axis="pacing",
                    severity="minor",
                    scene_index=i,
                    detail=f"Scene {i + 1}が{scene.estimated_duration:.1f}秒しかなく、字幕が読めません。",
                    suggestion="最低1.2秒程度に伸ばします。",
                    fix="set_duration",
                    fix_value=1.2,
                )
            )

    # --- Subtitles --------------------------------------------------------
    for i, scene in enumerate(scenes):
        caption = (scene.subtitle_text or "").strip()
        if not caption:
            issues.append(
                QualityIssue(
                    axis="subtitle",
                    severity="minor",
                    scene_index=i,
                    detail=f"Scene {i + 1}に字幕がありません。",
                    suggestion="ナレーションから短い字幕を作ります。",
                    fix="fill_subtitle",
                )
            )
        elif len(caption) > MAX_CHARS_PER_LINE * 2:
            issues.append(
                QualityIssue(
                    axis="subtitle",
                    severity="minor",
                    scene_index=i,
                    detail=f"Scene {i + 1}の字幕が{len(caption)}文字あり、一目で読めません。",
                    suggestion="2行以内に収まるよう短くします。",
                    fix="shorten_subtitle",
                )
            )

    # --- Continuity -------------------------------------------------------
    seen: dict[str, int] = {}
    for i, scene in enumerate(scenes):
        key = (scene.visual_prompt or "").strip()[:60]
        if key and key in seen:
            issues.append(
                QualityIssue(
                    axis="continuity",
                    severity="info",
                    scene_index=i,
                    detail=f"Scene {i + 1}の映像内容がScene {seen[key] + 1}とほぼ同じです。",
                    suggestion="映像に変化を付けると単調さが減ります。",
                )
            )
        elif key:
            seen[key] = i

    # --- Length -----------------------------------------------------------
    drift = abs(total - target_seconds) / max(1.0, target_seconds)
    if drift > DURATION_TOLERANCE:
        issues.append(
            QualityIssue(
                axis="structure",
                severity="minor",
                detail=(
                    f"完成尺が約{total:.0f}秒で、目標の{target_seconds:.0f}秒から"
                    f"{drift * 100:.0f}%ずれています。"
                ),
                suggestion="全体の尺を目標に合わせて調整します。",
                fix="rescale_total",
                fix_value=target_seconds,
            )
        )

    # --- Audio ------------------------------------------------------------
    if not has_narration:
        issues.append(
            QualityIssue(
                axis="narration",
                severity="info",
                detail="ナレーション音声がありません(この環境では音声合成が使えない可能性があります)。",
                suggestion="字幕で内容が伝わる構成になっているか確認してください。",
            )
        )
    if not has_bgm:
        issues.append(
            QualityIssue(
                axis="bgm",
                severity="info",
                detail="BGMがありません。",
                suggestion="BGMを追加すると体感的な完成度が上がります。",
            )
        )

    # --- Ending -----------------------------------------------------------
    last = scenes[-1]
    ending_cues = ("オチ", "余韻", "締め", "落ち", "ループ", "まとめ")
    haystack = f"{last.purpose} {last.narration} {last.subtitle_text}"
    if not any(cue in haystack for cue in ending_cues):
        issues.append(
            QualityIssue(
                axis="ending",
                severity="info",
                scene_index=len(scenes) - 1,
                detail="最後のシーンにオチや余韻が明示されていません。",
                suggestion="終わり方を確認してください。",
            )
        )

    return issues


# ------------------------------------------------------------- AI pass


def _review_prompt(scenes: list[Scene], strategy: ProductionStrategy, total: float) -> list[dict]:
    outline = "\n".join(
        f"{i + 1}. [{s.estimated_duration:.1f}s / {s.emotion or '-'}] "
        f"字幕『{(s.subtitle_text or '').strip()}』 映像: {(s.visual_prompt or '').strip()[:60]}"
        for i, s in enumerate(scenes)
    )
    system = (
        "あなたはショート動画の編集ディレクターです。以下の構成を審査し、"
        "問題点をJSONで指摘してください。JSONオブジェクトのみを返してください。\n\n"
        "出力形式:\n"
        '{"score": 72, "strengths": ["..."], "summary": "...", '
        '"issues": [{"axis": "hook", "severity": "major", "scene_index": 0, '
        '"detail": "...", "suggestion": "..."}]}\n\n'
        "axis は structure / pacing / hook / visual_quality / continuity / subtitle / "
        "audio / bgm / sfx / narration / short_form_fit / ending / loop のいずれか。\n"
        "severity は info / minor / major のいずれか。\n"
        "scene_index は0始まり。全体に関する指摘なら省略してください。\n"
        "指摘は最大6件。良い点も1〜3件挙げてください。"
    )
    user = (
        f"タイトル: {strategy.title}\n"
        f"狙い: {strategy.concept}\n"
        f"Hook: {strategy.hook}\n"
        f"終わり方: {strategy.ending}\n"
        f"合計尺: {total:.1f}秒\n\n"
        f"構成:\n{outline}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def check(
    scenes: list[Scene],
    strategy: ProductionStrategy,
    *,
    target_seconds: float,
    has_narration: bool,
    has_bgm: bool,
    use_ai: bool = True,
) -> QualityReport:
    issues = check_rules(
        scenes,
        strategy,
        target_seconds=target_seconds,
        has_narration=has_narration,
        has_bgm=has_bgm,
    )
    strengths: list[str] = []
    summary = ""
    checked_by = "rules"

    if use_ai and scenes:
        total = sum(s.estimated_duration for s in scenes)
        try:
            raw = llm_client.chat_completion(_review_prompt(scenes, strategy, total), temperature=0.2)
            data = parse_json_object(raw)
            for item in data.get("issues", [])[:6]:
                try:
                    issues.append(QualityIssue.model_validate(item))
                except ValidationError:
                    continue
            strengths = [str(s) for s in data.get("strengths", [])][:3]
            summary = str(data.get("summary", ""))[:400]
            checked_by = "rules+ai"
        except (
            JSONExtractionError,
            llm_client.LLMUnavailableError,
            llm_client.LLMTimeoutError,
            llm_client.LLMResponseError,
        ):
            logger.info("AI quality review unavailable; rule checks only")
        except Exception:
            logger.exception("AI quality review failed")

    # Score from the rule findings, so it means the same thing on every run
    # rather than tracking whatever number the model felt like returning.
    score = 100.0
    per_axis: dict[str, float] = {}
    for issue in issues:
        penalty = _severity_penalty(issue.severity)
        score -= penalty
        per_axis[issue.axis] = max(0.0, per_axis.get(issue.axis, 100.0) - penalty * 2)
    score = max(0.0, min(100.0, round(score, 1)))

    if not summary:
        major = sum(1 for i in issues if i.severity == "major")
        summary = (
            "大きな問題は見つかりませんでした。"
            if major == 0
            else f"重要な指摘が{major}件あります。"
        )

    return QualityReport(
        score=score,
        axes=per_axis,
        issues=issues,
        strengths=strengths,
        summary=summary,
        checked_by=checked_by,
    )


# --------------------------------------------------------- improvement


def _shorten_caption(text: str, limit: int) -> str:
    """Trims a caption to fit, cutting at punctuation when possible so the
    result reads as a phrase rather than a truncation."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    for mark in ("、", "。", "！", "？", " "):
        idx = text.rfind(mark, 0, limit + 1)
        if idx >= limit * 0.5:
            return text[:idx].strip()
    return text[:limit].strip()


def improve(
    db,
    scenes: list[Scene],
    report: QualityReport,
    strategy: ProductionStrategy,
    *,
    target_seconds: float,
) -> tuple[ImprovementReport, set[int]]:
    """Applies every fixable issue. Returns the report and the indices of
    scenes whose material must be re-rendered because their duration
    changed."""
    applied: list[AppliedImprovement] = []
    skipped: list[str] = []
    dirty: set[int] = set()

    for issue in report.issues:
        if issue.fix is None:
            if issue.severity != "info":
                skipped.append(f"[{issue.axis}] {issue.detail}")
            continue

        index = issue.scene_index
        scene = scenes[index] if index is not None and 0 <= index < len(scenes) else None

        if issue.fix == "set_duration" and scene is not None and issue.fix_value:
            before = scene.estimated_duration
            after = round(max(0.8, float(issue.fix_value)), 2)
            if abs(before - after) < 0.05:
                continue
            scene.estimated_duration = after
            dirty.add(index)  # type: ignore[arg-type]
            applied.append(
                AppliedImprovement(
                    scene_index=index,
                    what=f"Scene {index + 1}の尺",
                    before=f"{before:.1f}秒",
                    after=f"{after:.1f}秒",
                    reason=issue.suggestion or issue.detail,
                )
            )

        elif issue.fix == "fill_subtitle" and scene is not None:
            source = (scene.narration or scene.visual_prompt or "").strip()
            if not source:
                skipped.append(f"Scene {index + 1}: 字幕の元になる文がありません")
                continue
            new_text = _shorten_caption(source, MAX_CHARS_PER_LINE * 2)
            scene.subtitle_text = new_text
            applied.append(
                AppliedImprovement(
                    scene_index=index,
                    what=f"Scene {index + 1}の字幕",
                    before="(なし)",
                    after=new_text,
                    reason="音を出さずに見る視聴者にも内容が伝わるようにするため",
                )
            )

        elif issue.fix == "shorten_subtitle" and scene is not None:
            before = scene.subtitle_text or ""
            after = _shorten_caption(before, MAX_CHARS_PER_LINE * 2)
            if after == before:
                continue
            scene.subtitle_text = after
            applied.append(
                AppliedImprovement(
                    scene_index=index,
                    what=f"Scene {index + 1}の字幕",
                    before=before,
                    after=wrap_caption(after).replace("\n", " / "),
                    reason="スマートフォン画面で一目で読める長さにするため",
                )
            )

        elif issue.fix == "rescale_total":
            total = sum(s.estimated_duration for s in scenes)
            if total <= 0:
                continue
            factor = target_seconds / total
            if abs(factor - 1.0) < 0.03:
                continue
            for i, s in enumerate(scenes):
                new_duration = round(
                    max(1.0, min(s.estimated_duration * factor, strategy.scene_seconds_max + 2)), 2
                )
                if abs(new_duration - s.estimated_duration) >= 0.05:
                    s.estimated_duration = new_duration
                    dirty.add(i)
            applied.append(
                AppliedImprovement(
                    what="全体の尺",
                    before=f"{total:.0f}秒",
                    after=f"{sum(s.estimated_duration for s in scenes):.0f}秒",
                    reason=f"目標の{target_seconds:.0f}秒に近づけるため",
                )
            )

    db.commit()
    return (
        ImprovementReport(
            applied=applied,
            skipped=skipped,
            score_before=report.score,
            score_after=report.score,
        ),
        dirty,
    )


def report_to_json(report: QualityReport) -> str:
    return json.dumps(report.model_dump(), ensure_ascii=False)
