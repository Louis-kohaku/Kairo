"""Turning a review into changes, and knowing when to stop.

The loop the design asks for is Generate → Render → Review → Improve →
Render → Review → best version. The dangerous word in that sentence is
"loop", so the stopping rules are as much of this module as the fixes:

* a hard ceiling on iterations (`settings.refinement.max_iterations`),
* an early exit once the score clears `target_score`,
* an early exit when a pass gains less than `min_gain` - if a re-render
  bought half a point, the next one will not buy more,
* and an early exit when a pass produced no applicable changes at all.

The best version is adopted, not the last one. A refinement pass can make
things worse (shortening a scene to hit a target can cost the story more
than the pacing gains), and silently shipping a regression because it
happened to be last would be the worst possible behaviour for an automatic
system.
"""
from __future__ import annotations

import logging

from app.models.timeline import Clip, Track
from app.schemas.review import IterationRecord, ReviewFinding, VideoReview
from app.schemas.settings import RefinementSettings

logger = logging.getLogger(__name__)


def _shorten(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    for mark in ("、", "。", "！", "？", " "):
        index = text.rfind(mark, 0, limit + 1)
        if index >= limit * 0.5:
            return text[:index].strip()
    return text[:limit].strip()


def reduce_transitions(plan, keep: int) -> tuple[object, str]:
    """Thins a transition plan down to its `keep` best-justified boundaries.

    The review's "Transitionが多すぎる" finding is only worth reporting if
    something can act on it, and the thing that can act on it is the plan -
    the renderer executes exactly what the plan says. Dropped in order of
    how weak the reason was, so an act change keeps its transition and an
    incidental location change loses one.

    Returns (plan, description). The plan is a new object; the caller
    stores it, which is what makes the next render actually different.
    """
    from app.schemas.edit_style import TRANSITION_LABELS, TRANSITION_REASON_LABELS
    from app.services.studio.transition_planner import _REASON_PRIORITY

    non_cut = [c for c in plan.choices if c.transition != "cut"]
    if len(non_cut) <= max(0, keep):
        return plan, ""

    ranked = sorted(
        non_cut, key=lambda c: (-_REASON_PRIORITY.get(c.reason, 0), c.index)
    )
    survivors = {c.index for c in ranked[: max(0, keep)]}
    removed = 0
    for choice in plan.choices:
        if choice.transition == "cut" or choice.index in survivors:
            continue
        choice.transition = "cut"
        choice.label = TRANSITION_LABELS["cut"]
        choice.duration = 0.0
        choice.reason = "none"
        choice.reason_label = TRANSITION_REASON_LABELS["none"]
        choice.detail = "切り替えが多すぎたため、カットに戻しました"
        removed += 1
    plan.non_cut_count = len(non_cut) - removed
    plan.summary = (
        f"{plan.boundary_count}箇所のうち{plan.non_cut_count}箇所だけ画面切り替えを使います"
        f"（レビュー指摘により{removed}箇所をカットに戻しました）"
    )
    return plan, f"画面切り替えを{len(non_cut)}箇所 → {plan.non_cut_count}箇所に削減"


def apply_findings(
    db,
    scenes: list,
    findings: list[ReviewFinding],
    *,
    project_id: str,
    max_chars_per_line: int,
    target_seconds: float,
    scene_seconds_max: float,
) -> tuple[list[str], set[int]]:
    """Applies every fixable finding.

    Returns (change descriptions, indices of scenes whose material must be
    re-encoded). A finding with no `fix` is not a failure - it is reported
    to the user as something Kairo found but cannot fix itself, which is
    exactly what the design asks for.
    """
    changes: list[str] = []
    dirty: set[int] = set()

    for finding in findings:
        if finding.fix is None:
            continue
        index = finding.scene_index
        scene = scenes[index] if index is not None and 0 <= index < len(scenes) else None

        if finding.fix == "set_duration" and scene is not None and finding.fix_value:
            before = float(scene.estimated_duration or 0.0)
            after = round(max(0.8, float(finding.fix_value)), 2)
            if abs(before - after) < 0.05:
                continue
            scene.estimated_duration = after
            dirty.add(index)  # type: ignore[arg-type]
            changes.append(f"Scene {index + 1}の尺: {before:.1f}秒 → {after:.1f}秒")

        elif finding.fix == "fill_subtitle" and scene is not None:
            source = (scene.narration or scene.visual_prompt or "").strip()
            if not source:
                continue
            scene.subtitle_text = _shorten(source, max_chars_per_line * 2)
            changes.append(f"Scene {index + 1}に字幕を追加: 「{scene.subtitle_text}」")

        elif finding.fix == "shorten_subtitle" and scene is not None:
            before = scene.subtitle_text or ""
            after = _shorten(before, max_chars_per_line * 2)
            if after == before:
                continue
            scene.subtitle_text = after
            changes.append(f"Scene {index + 1}の字幕を短縮: 「{after}」")

        elif finding.fix == "rescale_total" and finding.fix_value:
            total = sum(float(s.estimated_duration or 0.0) for s in scenes)
            if total <= 0:
                continue
            factor = float(finding.fix_value) / total
            if abs(factor - 1.0) < 0.03:
                continue
            for i, s in enumerate(scenes):
                new_duration = round(
                    max(1.0, min(float(s.estimated_duration or 0.0) * factor, scene_seconds_max + 2)),
                    2,
                )
                if abs(new_duration - float(s.estimated_duration or 0.0)) >= 0.05:
                    s.estimated_duration = new_duration
                    dirty.add(i)
            changes.append(
                f"全体の尺: {total:.0f}秒 → {sum(float(s.estimated_duration or 0) for s in scenes):.0f}秒"
            )

        elif finding.fix in ("raise_bgm", "lower_bgm") and finding.fix_value:
            # Volume lives on the timeline clip, which is what the renderer
            # reads - changing a number anywhere else would not reach the
            # output file.
            track = (
                db.query(Track)
                .filter(Track.project_id == project_id, Track.type == "audio")
                .order_by(Track.order_index)
                .first()
            )
            if track is None:
                continue
            clips = db.query(Clip).filter(Clip.track_id == track.id).all()
            if not clips:
                continue
            # fix_value is a linear gain ratio (see reviewer._score_audio).
            # The renderer multiplies clip.volume by DEFAULT_BGM_VOLUME and
            # clamps the product to 1.0, so 4.0 here is full scale - the
            # ceiling is that clamp, not an arbitrary number.
            ratio = float(finding.fix_value)
            before = clips[0].volume
            for clip in clips:
                clip.volume = round(max(0.1, min(clip.volume * ratio, 4.0)), 2)
            changes.append(f"BGM音量: {before:.2f} → {clips[0].volume:.2f}（x{ratio:.2f}）")

    if changes:
        db.commit()
    return changes, dirty


def should_continue(
    settings: RefinementSettings,
    history: list[IterationRecord],
    latest: VideoReview,
) -> tuple[bool, str]:
    """Whether another pass is worth a full re-render."""
    if not settings.enabled:
        return False, "設定で自動改善が無効になっています。"
    completed = len(history)
    if completed >= max(1, settings.max_iterations):
        return False, f"設定の最大反復回数({settings.max_iterations}回)に達しました。"
    if latest.overall_score >= settings.target_score:
        return False, (
            f"目標スコア{settings.target_score:.0f}点に到達しました"
            f"（{latest.overall_score:.0f}点）。"
        )
    fixable = sum(1 for f in latest.findings if f.fix is not None)
    if fixable == 0:
        return False, "自動で修正できる指摘が残っていません。"
    if completed >= 2:
        gain = history[-1].score - history[-2].score
        if gain < settings.min_gain:
            return False, (
                f"前回の改善幅が{gain:+.1f}点と小さいため、これ以上の反復は行いません。"
            )
    return True, f"{fixable}件の修正可能な指摘があるため、もう一度改善します。"


def best_iteration(history: list[IterationRecord]) -> IterationRecord | None:
    """The highest-scoring pass. Ties go to the earlier one, which was
    reached with fewer changes and is therefore closer to the plan."""
    if not history:
        return None
    return max(history, key=lambda record: (record.score, -record.iteration))
