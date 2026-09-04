"""The first three seconds (requirement 9).

On Shorts, TikTok and Reels the opening decides whether the rest of the
video is watched at all, and the ways it goes wrong are specific and
checkable: the strongest picture is somewhere in the middle, the opening
shot is too long, there is no caption to read with the sound off, or the
first thing on screen is a dark or static frame.

So this runs after the scenes exist and before the material is built,
scores the opening against those failure modes, and applies the fixes it
can actually make:

* **Move the strongest shot to the front.** Measured from the material
  analysis - brightness, sharpness, motion and how well the shot matched
  its scene - not from an opinion about the content.
* **Shorten an over-long opening.**
* **Write a hook caption** when the opening has none.
* **Speed up the first cuts** when the style asks for it.

Every change is returned with its reason, and the whole pass is skipped for
formats where it does not apply - a 16:9 explainer is not watched under the
same rules and forcing a hook onto it would make it worse.

What it deliberately does not do is reorder freely. Moving one shot to the
front is a decision a human editor makes; shuffling the whole video to
maximise a score is not editing, and the story structure the planner built
would not survive it.
"""
from __future__ import annotations

import logging

from app.schemas.edit_style import EditDirective

logger = logging.getLogger(__name__)

# Platforms where the opening genuinely decides retention. A 16:9 YouTube
# video is found by title and thumbnail, so the same rules do not apply.
SHORT_FORM_PLATFORMS = ("youtube_shorts", "tiktok", "instagram_reels")


class HookReport:
    """What the pass found and what it did about it."""

    def __init__(self) -> None:
        self.applicable: bool = True
        self.skipped_reason: str = ""
        self.score: float = 0.0
        self.findings: list[str] = []
        self.changes: list[str] = []
        self.dirty: set[int] = set()
        self.moved_from: int | None = None

    def to_dict(self) -> dict:
        return {
            "applicable": self.applicable,
            "skipped_reason": self.skipped_reason,
            "score": round(self.score, 1),
            "findings": self.findings,
            "changes": self.changes,
            "moved_from": self.moved_from,
        }


def _shot_strength(scene, analysis) -> tuple[float, list[str]]:
    """How strong an opening this shot would make, 0-100.

    Built only from things that were measured. A shot with no analysis
    scores from what the scene design says about it, which is less
    information and is treated as such rather than as a low score.
    """
    score = 40.0
    why: list[str] = []

    if analysis is not None:
        if analysis.quality_score is not None:
            score += (analysis.quality_score - 60.0) * 0.35
            if analysis.quality_score >= 80:
                why.append(f"画質{analysis.quality_score:.0f}")
        if analysis.brightness is not None:
            # A bright frame reads on a phone in daylight; a dark one does
            # not, and the opening is the one place that matters most.
            if 0.42 <= analysis.brightness <= 0.78:
                score += 14.0
                why.append("明るさが適正")
            elif analysis.brightness < 0.25:
                score -= 22.0
        if analysis.motion is not None and analysis.motion > 0.08:
            score += 16.0
            why.append("動きがある")
        if analysis.sharpness is not None and analysis.sharpness >= 0.3:
            score += 8.0
        if analysis.duplicate_of:
            score -= 10.0

    caption = (getattr(scene, "subtitle_text", "") or "").strip()
    if caption:
        score += 10.0
    emotion = (getattr(scene, "emotion", "") or "").strip()
    if emotion and emotion not in ("普通", "中立", "neutral"):
        score += 6.0
        why.append(f"感情「{emotion}」")

    return max(0.0, min(100.0, score)), why


def _hook_caption(scene, directive: EditDirective) -> str:
    """A short caption for an opening that has none.

    Built from what the scene already says rather than invented: the
    subtitle if there is one, else the first clause of the narration, else
    the visual description. Nothing is fabricated - a hook that claims
    something the video does not show is worse than no hook.
    """
    for source in (
        getattr(scene, "subtitle_text", ""),
        getattr(scene, "narration", ""),
        getattr(scene, "purpose", ""),
        getattr(scene, "visual_prompt", ""),
    ):
        text = " ".join((source or "").split())
        if not text:
            continue
        for mark in ("。", "、", "！", "？", "!", "?"):
            index = text.find(mark)
            if 4 <= index <= 18:
                return text[:index]
        return text[:16]
    return ""


def optimize(
    db,
    scenes: list,
    directive: EditDirective,
    *,
    analyses_by_asset: dict | None = None,
) -> HookReport:
    """Scores and improves the opening. Returns what it found and changed.

    Mutates the scene rows (durations, captions, order) and commits, but
    never rebuilds material - the caller re-renders the scenes named in
    `report.dirty`, which is what keeps this cheap.
    """
    report = HookReport()
    analyses_by_asset = analyses_by_asset or {}

    if directive.platform not in SHORT_FORM_PLATFORMS:
        report.applicable = False
        report.skipped_reason = (
            f"{directive.platform_label}は冒頭で離脱が決まる形式ではないため、"
            "冒頭最適化は行いません。"
        )
        return report
    if len(scenes) < 3:
        report.applicable = False
        report.skipped_reason = "シーンが少ないため、並べ替えの余地がありません。"
        return report

    def analysis_for(scene):
        asset_id = getattr(scene, "user_asset_id", None)
        return analyses_by_asset.get(asset_id) if asset_id else None

    strengths = [_shot_strength(s, analysis_for(s)) for s in scenes]
    first_score, first_why = strengths[0]
    report.score = first_score

    # --- 1. is the strongest shot at the front? ------------------------
    # Only the first third is considered as a source. Pulling the closing
    # shot to the front would give away the ending, which is a worse video
    # even if the frame is stronger.
    window = max(1, len(scenes) // 3)
    best_index = 0
    best_score = first_score
    for i in range(1, window + 1):
        if i >= len(scenes):
            break
        if strengths[i][0] > best_score + 12.0:
            best_index, best_score = i, strengths[i][0]

    if best_index > 0:
        moved = scenes.pop(best_index)
        scenes.insert(0, moved)
        strengths.insert(0, strengths.pop(best_index))
        for i, scene in enumerate(scenes):
            scene.order_index = i
            scene.is_hook = i == 0
        report.moved_from = best_index
        report.dirty.update({0, best_index})
        report.changes.append(
            f"Scene {best_index + 1}を冒頭に移動しました"
            f"（強さ{best_score:.0f} > 元の冒頭{first_score:.0f}）"
        )
        report.findings.append(
            "冒頭より強い画が"
            + "・".join(strengths[0][1][:2])
            + "という理由で後ろにありました"
        )
        report.score = best_score
    elif first_score < 45:
        report.findings.append(
            f"冒頭の画が弱めです（強さ{first_score:.0f}）。"
            "より明るい・動きのある素材があると改善します。"
        )

    opening = scenes[0]

    # --- 2. is the opening too long? -----------------------------------
    limit = max(1.6, directive.hook_seconds)
    duration = float(opening.estimated_duration or 0.0)
    if duration > limit + 0.6:
        after = round(max(1.4, limit), 2)
        opening.estimated_duration = after
        report.dirty.add(0)
        report.changes.append(
            f"冒頭シーンの尺: {duration:.1f}秒 → {after:.1f}秒"
        )
        report.findings.append(
            f"冒頭が{duration:.1f}秒あり、{directive.platform_label}の"
            f"目安({limit:.1f}秒)を超えていました。"
        )

    # --- 3. is there something to read with the sound off? -------------
    if not (opening.subtitle_text or "").strip():
        caption = _hook_caption(opening, directive)
        if caption:
            opening.subtitle_text = caption
            report.changes.append(f"冒頭に字幕を追加: 「{caption}」")
            report.findings.append(
                "冒頭に字幕がありませんでした。無音再生が多い形式では"
                "内容が伝わりません。"
            )
        else:
            report.findings.append(
                "冒頭に字幕がなく、シーン設計にも字幕にできる文が"
                "ありませんでした。"
            )

    # --- 4. do the first cuts move fast enough? ------------------------
    if directive.tempo == "fast" and len(scenes) >= 3:
        target = directive.scene_seconds
        for i in (1, 2):
            current = float(scenes[i].estimated_duration or 0.0)
            if current > target * 1.5:
                after = round(max(directive.scene_seconds_min, target), 2)
                scenes[i].estimated_duration = after
                report.dirty.add(i)
                report.changes.append(
                    f"Scene {i + 1}の尺: {current:.1f}秒 → {after:.1f}秒"
                    "（冒頭のテンポを上げるため）"
                )

    if report.changes:
        db.commit()
    if not report.findings and not report.changes:
        report.findings.append(
            f"冒頭は良好です（強さ{report.score:.0f}、{opening.estimated_duration:.1f}秒）。"
        )
    return report
