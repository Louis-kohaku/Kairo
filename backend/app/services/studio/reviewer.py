"""The AI Video Reviewer: scoring the file that actually came out.

The existing `quality_service` reviews the plan - the scene design, before
anything is encoded - and it stays exactly as it was. This module opens the
rendered MP4 and scores what is in it, which is a different question and
sometimes a different answer: a sound plan can render dark, silent, or two
seconds longer than asked.

Every axis says what it is based on:

* `measured` - read out of the file (ffprobe, EBU R128 loudness, sampled
  frame statistics). These are facts about the render.
* `planned`  - read from the scene design, because the file cannot answer
  it (whether the hook *says* the right thing, for example).
* `ai`       - the local model's judgement, when it is available.

That labelling is the point. A number the user cannot trace back to
something real is worse than no number, so the UI shows the basis next to
every score, and an axis that could not be evaluated scores nothing rather
than defaulting to a flattering value.
"""
from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

from app.schemas.review import (
    AXES,
    AXIS_LABELS,
    AxisScore,
    ReviewFinding,
    VideoReview,
)
from app.schemas.trend import GenreProfileData, TrendContext
from app.services import llm_client
from app.services.ffmpeg import compose
from app.services.ffmpeg.probe import ProbeError, probe_media
from app.services.json_extract import JSONExtractionError, parse_json_object
from app.services.library import audio_analysis

logger = logging.getLogger(__name__)

# How many stills are pulled out of the render for the visual pass. Enough
# to catch a dark or static video, few enough that the review costs seconds.
_FRAME_SAMPLES = 8
# A short-form frame below this mean luma reads as underexposed on a phone
# in daylight.
_DARK_THRESHOLD = 45.0
_BRIGHT_THRESHOLD = 225.0
# Integrated loudness targets. Short-form platforms normalise around
# -14 LUFS; a mix far below that is quiet even after normalisation.
_TARGET_LUFS = -14.0
_LUFS_TOLERANCE = 6.0


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, round(value, 1)))


def _measure_frames(path: Path) -> dict:
    """Mean luma and contrast over sampled frames, via Pillow."""
    try:
        from PIL import Image, ImageStat
    except ImportError:
        return {"available": False, "reason": "Pillowが利用できません"}

    try:
        info = probe_media(path)
    except ProbeError as exc:
        return {"available": False, "reason": str(exc)}
    if info.duration <= 0:
        return {"available": False, "reason": "尺を取得できませんでした"}

    timestamps = [
        info.duration * (i + 0.5) / _FRAME_SAMPLES for i in range(_FRAME_SAMPLES)
    ]
    with tempfile.TemporaryDirectory(prefix="kairo_review_") as tmp:
        try:
            frames = compose.extract_frames(path, Path(tmp), timestamps, width=320)
        except Exception as exc:  # noqa: BLE001 - a review must not fail a run
            return {"available": False, "reason": f"フレームを抽出できません: {exc}"}

        luma: list[float] = []
        spread: list[float] = []
        for frame in frames:
            try:
                with Image.open(frame) as image:
                    grey = image.convert("L")
                    stat = ImageStat.Stat(grey)
                    luma.append(float(stat.mean[0]))
                    spread.append(float(stat.stddev[0]))
            except Exception:
                continue

    if not luma:
        return {"available": False, "reason": "フレームを読み取れませんでした"}

    # Frame-to-frame luma change is a cheap, honest proxy for "does the
    # picture actually move" - it does not know about motion, only that
    # consecutive samples differ.
    variation = (
        sum(abs(b - a) for a, b in zip(luma, luma[1:])) / max(1, len(luma) - 1)
        if len(luma) > 1
        else 0.0
    )
    return {
        "available": True,
        "samples": len(luma),
        "mean_luma": round(sum(luma) / len(luma), 1),
        "min_luma": round(min(luma), 1),
        "max_luma": round(max(luma), 1),
        "mean_contrast": round(sum(spread) / len(spread), 1),
        "frame_variation": round(variation, 2),
    }


def measure(path: Path) -> dict:
    """Everything the reviewer can read out of the rendered file."""
    out: dict = {"path": str(path), "exists": path.exists()}
    if not path.exists():
        out["error"] = "レンダリング結果のファイルが見つかりません"
        return out

    out["size_bytes"] = path.stat().st_size
    try:
        info = probe_media(path)
        out.update(
            {
                "duration": round(info.duration, 3),
                "width": info.width,
                "height": info.height,
                "fps": round(info.fps, 2) if info.fps else None,
                "has_audio": info.has_audio,
                "video_codec": info.video_codec,
                "audio_codec": info.audio_codec,
            }
        )
    except ProbeError as exc:
        out["error"] = str(exc)
        return out

    if info.has_audio:
        lufs, peak = audio_analysis.measure_loudness(path)
        out["loudness_lufs"] = lufs
        out["peak_dbfs"] = peak
    out["frames"] = _measure_frames(path)
    return out


# ------------------------------------------------------------ rule axes


def _score_hook(scenes: list, measured: dict) -> tuple[AxisScore, list[ReviewFinding]]:
    findings: list[ReviewFinding] = []
    if not scenes:
        return AxisScore(axis="hook", label=AXIS_LABELS["hook"], score=0.0, basis="planned",
                         detail="シーンがありません"), findings

    first = scenes[0]
    duration = float(first.estimated_duration or 0.0)
    caption = (first.subtitle_text or "").strip()
    score = 100.0
    details: list[str] = [f"冒頭{duration:.1f}秒"]

    if duration > 4.0:
        score -= 30.0
        findings.append(
            ReviewFinding(
                axis="hook",
                severity="major",
                problem=f"冒頭シーンが{duration:.1f}秒あります。",
                cause="掴みが長いと、内容が始まる前に離脱されます。",
                suggestion="冒頭は3秒以内に収め、すぐ本題を見せてください。",
                fix="set_duration",
                fix_value=min(3.0, max(1.6, duration * 0.6)),
                scene_index=0,
            )
        )
    elif duration > 3.0:
        score -= 12.0

    if not caption:
        score -= 30.0
        findings.append(
            ReviewFinding(
                axis="hook",
                severity="major",
                problem="冒頭に字幕がありません。",
                cause="ショート動画は音を切ったまま見られることが多く、冒頭の字幕がないと内容が伝わりません。",
                suggestion="冒頭シーンに短い字幕を入れてください。",
                fix="fill_subtitle",
                scene_index=0,
            )
        )
    else:
        details.append(f"冒頭字幕「{caption[:16]}」")

    frames = measured.get("frames") or {}
    if frames.get("available") and frames.get("min_luma", 100) < _DARK_THRESHOLD:
        score -= 8.0
        details.append("暗いフレームあり")

    return (
        AxisScore(axis="hook", label=AXIS_LABELS["hook"], score=_clamp(score),
                  basis="planned", detail=" / ".join(details)),
        findings,
    )


def _score_pacing(scenes: list, measured: dict, profile: GenreProfileData | None):
    findings: list[ReviewFinding] = []
    if not scenes:
        return AxisScore(axis="pacing", label=AXIS_LABELS["pacing"], score=0.0,
                         basis="planned", detail="シーンがありません"), findings

    durations = [float(s.estimated_duration or 0.0) for s in scenes]
    total = sum(durations)
    mean = total / len(durations)
    target = (profile.scene_seconds if profile and profile.scene_seconds else 3.0) or 3.0

    score = 100.0 - min(40.0, abs(mean - target) / max(target, 0.5) * 60.0)
    details = [f"平均{mean:.1f}秒/カット（目安{target:.1f}秒）", f"{len(scenes)}カット"]

    long_scenes = [i for i, d in enumerate(durations) if d > target * 2.2]
    for i in long_scenes[:3]:
        score -= 6.0
        findings.append(
            ReviewFinding(
                axis="pacing",
                severity="minor",
                problem=f"Scene {i + 1}が{durations[i]:.1f}秒で、他より大幅に長いです。",
                cause=f"このジャンルの目安({target:.1f}秒)の2倍を超えています。",
                suggestion="分割するか短くするとテンポが揃います。",
                fix="set_duration",
                fix_value=round(target * 1.4, 2),
                scene_index=i,
            )
        )

    # A render whose real length disagrees with the plan means something
    # downstream did not do what the plan said, which is worth reporting
    # even though it does not change the score much.
    real = measured.get("duration")
    if real and abs(real - total) > max(1.0, total * 0.08):
        details.append(f"実測{real:.1f}秒 / 計画{total:.1f}秒")
        findings.append(
            ReviewFinding(
                axis="pacing",
                severity="info",
                problem=f"書き出された尺({real:.1f}秒)が計画({total:.1f}秒)とずれています。",
                cause="素材の実長がシーンの計画尺と異なるためです。",
                suggestion="素材の切り出し範囲を確認してください。",
            )
        )
    return (
        AxisScore(axis="pacing", label=AXIS_LABELS["pacing"], score=_clamp(score),
                  basis="measured" if real else "planned", detail=" / ".join(details)),
        findings,
    )


def _score_visual(measured: dict):
    findings: list[ReviewFinding] = []
    frames = measured.get("frames") or {}
    if not frames.get("available"):
        return (
            AxisScore(axis="visual", label=AXIS_LABELS["visual"], score=0.0, basis="measured",
                      detail=f"映像を解析できませんでした（{frames.get('reason', '理由不明')}）"),
            findings,
        )

    score = 100.0
    mean_luma = frames.get("mean_luma", 0.0)
    contrast = frames.get("mean_contrast", 0.0)
    variation = frames.get("frame_variation", 0.0)
    details = [f"平均輝度{mean_luma:.0f}", f"コントラスト{contrast:.0f}"]

    if mean_luma < _DARK_THRESHOLD:
        score -= 30.0
        findings.append(
            ReviewFinding(
                axis="visual",
                severity="major",
                problem=f"全体的に暗い映像です（平均輝度{mean_luma:.0f}/255）。",
                cause="素材が暗いか、暗いシーンが続いています。",
                suggestion="明るい素材を冒頭に置くか、明るさ補正を検討してください。",
            )
        )
    elif mean_luma > _BRIGHT_THRESHOLD:
        score -= 15.0
        findings.append(
            ReviewFinding(
                axis="visual",
                severity="minor",
                problem=f"白飛びぎみです（平均輝度{mean_luma:.0f}/255）。",
                cause="露出過多の素材が続いています。",
                suggestion="露出を抑えた素材に差し替えてください。",
            )
        )

    if contrast < 30:
        score -= 12.0
        details.append("コントラストが低い")
    if variation < 3.0:
        score -= 18.0
        findings.append(
            ReviewFinding(
                axis="visual",
                severity="minor",
                problem="画に変化が乏しく、同じような絵が続いています。",
                cause="サンプリングしたフレーム間の輝度差がほとんどありません。",
                suggestion="別のカットを挟むか、動きのある素材を追加してください。",
            )
        )
    else:
        details.append(f"フレーム間変化{variation:.1f}")

    if measured.get("width") and measured.get("height"):
        details.append(f"{measured['width']}x{measured['height']}")
    return (
        AxisScore(axis="visual", label=AXIS_LABELS["visual"], score=_clamp(score),
                  basis="measured", detail=" / ".join(details)),
        findings,
    )


def _score_subtitle(scenes: list, cues: list, measured: dict, max_chars: int):
    findings: list[ReviewFinding] = []
    total = sum(float(s.estimated_duration or 0.0) for s in scenes) or 1.0
    covered = sum(max(0.0, (c.end or 0.0) - (c.start or 0.0)) for c in cues)
    coverage = min(1.0, covered / total)

    score = 60.0 + coverage * 40.0
    details = [f"字幕{len(cues)}件", f"表示率{coverage * 100:.0f}%"]

    missing = [i for i, s in enumerate(scenes) if not (s.subtitle_text or "").strip()]
    for i in missing[:3]:
        score -= 8.0
        findings.append(
            ReviewFinding(
                axis="subtitle",
                severity="minor",
                problem=f"Scene {i + 1}に字幕がありません。",
                cause="無音視聴では内容が伝わりません。",
                suggestion="ナレーションから短い字幕を作ります。",
                fix="fill_subtitle",
                scene_index=i,
            )
        )

    overlong = [
        i
        for i, s in enumerate(scenes)
        if len((s.subtitle_text or "").strip()) > max_chars * 2
    ]
    for i in overlong[:3]:
        score -= 6.0
        findings.append(
            ReviewFinding(
                axis="subtitle",
                severity="minor",
                problem=f"Scene {i + 1}の字幕が長すぎます（{len(scenes[i].subtitle_text or '')}文字）。",
                cause=f"この解像度・文字サイズでは1行{max_chars}文字が上限です。",
                suggestion="2行以内に収まるよう短くします。",
                fix="shorten_subtitle",
                scene_index=i,
            )
        )

    if coverage < 0.4:
        findings.append(
            ReviewFinding(
                axis="subtitle",
                severity="major",
                problem=f"字幕が出ている時間が全体の{coverage * 100:.0f}%しかありません。",
                cause="字幕のないシーンが多く残っています。",
                suggestion="主要なシーンすべてに字幕を入れてください。",
            )
        )
    return (
        AxisScore(axis="subtitle", label=AXIS_LABELS["subtitle"], score=_clamp(score),
                  basis="planned", detail=" / ".join(details)),
        findings,
    )


def _score_audio(measured: dict, has_bgm: bool, has_narration: bool):
    findings: list[ReviewFinding] = []
    if not measured.get("has_audio"):
        findings.append(
            ReviewFinding(
                axis="audio",
                severity="major",
                problem="書き出された動画に音声トラックがありません。",
                cause="BGMもナレーションも合成されていません。",
                suggestion="BGMを有効にするか、ナレーション用の音声合成を設定してください。",
            )
        )
        return (
            AxisScore(axis="audio", label=AXIS_LABELS["audio"], score=0.0, basis="measured",
                      detail="音声トラックなし"),
            findings,
        )

    lufs = measured.get("loudness_lufs")
    score = 100.0
    details: list[str] = []
    if lufs is None:
        score = 70.0
        details.append("ラウドネスを測定できませんでした")
    else:
        details.append(f"{lufs:.1f} LUFS")
        deviation = abs(lufs - _TARGET_LUFS)
        if deviation > _LUFS_TOLERANCE:
            score -= min(45.0, (deviation - _LUFS_TOLERANCE) * 4.0)
            direction = "小さい" if lufs < _TARGET_LUFS else "大きい"
            findings.append(
                ReviewFinding(
                    axis="audio",
                    severity="minor" if deviation < 12 else "major",
                    problem=f"音量が目安(-14 LUFS)より{deviation:.0f}dB{direction}です（{lufs:.1f} LUFS）。",
                    cause=(
                        "BGMのみで構成されており、全体の音量が低いままです。"
                        if not has_narration
                        else "ミックス後の音量が配信プラットフォームの基準から外れています。"
                    ),
                    suggestion="BGM音量を上げるか、書き出し時にノーマライズしてください。",
                    fix="raise_bgm" if lufs < _TARGET_LUFS else "lower_bgm",
                    # A linear gain *ratio*, not a dB delta: the clip volume
                    # the renderer reads is a multiplier, so the correction
                    # has to be converted out of dB here. Capped at 8x in
                    # either direction so one odd measurement cannot drive
                    # the whole mix into the limiter.
                    fix_value=round(
                        min(8.0, max(0.125, 10 ** ((_TARGET_LUFS - lufs) / 20.0))), 3
                    ),
                )
            )

    peak = measured.get("peak_dbfs")
    if peak is not None and peak > -0.5:
        score -= 10.0
        findings.append(
            ReviewFinding(
                axis="audio",
                severity="minor",
                problem=f"ピークが{peak:.1f} dBFSでクリップ寸前です。",
                cause="ミックス時の合計音量が高すぎます。",
                suggestion="全体を数dB下げてください。",
            )
        )
    if not has_bgm:
        score -= 15.0
        details.append("BGMなし")
    if not has_narration:
        details.append("ナレーションなし")
    return (
        AxisScore(axis="audio", label=AXIS_LABELS["audio"], score=_clamp(score),
                  basis="measured", detail=" / ".join(details)),
        findings,
    )


def _score_story(scenes: list, strategy):
    findings: list[ReviewFinding] = []
    if not scenes:
        return AxisScore(axis="story", label=AXIS_LABELS["story"], score=0.0,
                         basis="planned", detail="シーンがありません"), findings

    score = 100.0
    details = [f"{len(scenes)}シーン構成"]
    if len(scenes) < 3:
        score -= 25.0
        findings.append(
            ReviewFinding(
                axis="story",
                severity="minor",
                problem=f"シーンが{len(scenes)}個しかなく、展開が作れていません。",
                cause="構成が短すぎます。",
                suggestion="導入・展開・締めの3つ以上に分けてください。",
            )
        )

    last = scenes[-1]
    haystack = f"{last.purpose} {last.narration} {last.subtitle_text}"
    if not any(cue in haystack for cue in ("オチ", "余韻", "締め", "まとめ", "ループ", "落ち")):
        score -= 10.0
        findings.append(
            ReviewFinding(
                axis="story",
                severity="info",
                problem="最後のシーンにオチや余韻が明示されていません。",
                cause="終わり方が設計上定義されていません。",
                suggestion="終わり方を一言決めてください。",
            )
        )

    prompts = [(s.visual_prompt or "").strip()[:50] for s in scenes]
    duplicates = len(prompts) - len(set(p for p in prompts if p))
    if duplicates > 0:
        score -= min(20.0, duplicates * 7.0)
        details.append(f"同内容のカット{duplicates}件")

    if strategy is not None and getattr(strategy, "hook", ""):
        details.append(f"Hook方針: {strategy.hook[:24]}")
    return (
        AxisScore(axis="story", label=AXIS_LABELS["story"], score=_clamp(score),
                  basis="planned", detail=" / ".join(details)),
        findings,
    )


def _score_trend(scenes: list, measured: dict, trend: TrendContext | None):
    findings: list[ReviewFinding] = []
    if trend is None or not trend.used or trend.profile is None:
        return (
            AxisScore(
                axis="trend_alignment",
                label=AXIS_LABELS["trend_alignment"],
                score=0.0,
                basis="measured",
                detail=(
                    trend.reason
                    if trend is not None and trend.reason
                    else "トレンドデータを使用していないため評価しません"
                ),
            ),
            findings,
        )

    profile = trend.profile
    total = measured.get("duration") or sum(float(s.estimated_duration or 0.0) for s in scenes)
    score = 100.0
    details: list[str] = []

    if profile.duration_seconds:
        drift = abs(total - profile.duration_seconds) / max(profile.duration_seconds, 1.0)
        score -= min(35.0, drift * 70.0)
        details.append(
            f"尺{total:.0f}秒（{trend.genre_label}の傾向{profile.duration_seconds:.0f}秒）"
        )
        if drift > 0.4:
            findings.append(
                ReviewFinding(
                    axis="trend_alignment",
                    severity="minor",
                    problem=(
                        f"尺が{total:.0f}秒で、{trend.genre_label}ジャンルの傾向"
                        f"({profile.duration_seconds:.0f}秒)から離れています。"
                    ),
                    cause="ジャンルの標準的な尺と大きく異なります。",
                    suggestion=f"{profile.duration_seconds:.0f}秒前後に調整すると傾向に近づきます。",
                    fix="rescale_total",
                    fix_value=profile.duration_seconds,
                )
            )

    if profile.scene_seconds and scenes:
        mean = sum(float(s.estimated_duration or 0.0) for s in scenes) / len(scenes)
        drift = abs(mean - profile.scene_seconds) / max(profile.scene_seconds, 0.5)
        score -= min(25.0, drift * 45.0)
        details.append(f"カット{mean:.1f}秒（傾向{profile.scene_seconds:.1f}秒）")

    if trend.signals:
        details.append(f"参照トレンド{len(trend.signals)}件")

    return (
        AxisScore(
            axis="trend_alignment",
            label=AXIS_LABELS["trend_alignment"],
            score=_clamp(score),
            basis="measured" if measured.get("duration") else "planned",
            detail=" / ".join(details),
        ),
        findings,
    )


# --------------------------------------------------------------- AI pass


def _ai_prompt(scenes: list, measured: dict, axes: list[AxisScore]) -> list[dict]:
    outline = "\n".join(
        f"{i + 1}. [{float(s.estimated_duration or 0):.1f}s] "
        f"字幕『{(s.subtitle_text or '').strip()[:24]}』 映像: {(s.visual_prompt or '').strip()[:40]}"
        for i, s in enumerate(scenes[:20])
    )
    facts = "\n".join(f"- {a.label}: {a.score:.0f}点 ({a.detail})" for a in axes)
    system = (
        "あなたはショート動画のレビュアーです。実測値と構成をもとに、"
        "改善すべき点を最大4件、JSONで返してください。JSONオブジェクトのみを出力すること。\n\n"
        "出力形式:\n"
        '{"summary": "...", "strengths": ["..."], "findings": '
        '[{"axis": "hook", "severity": "major", "problem": "...", "cause": "...", '
        '"suggestion": "...", "scene_index": 0}]}\n\n'
        "axis は hook / pacing / visual / subtitle / audio / story / trend_alignment のいずれか。"
        "severity は info / minor / major。実測値と矛盾することを書かないこと。"
    )
    user = (
        f"実測:\n"
        f"- 尺: {measured.get('duration')}秒\n"
        f"- 解像度: {measured.get('width')}x{measured.get('height')}\n"
        f"- 音声: {'あり' if measured.get('has_audio') else 'なし'} "
        f"({measured.get('loudness_lufs')} LUFS)\n\n"
        f"ルール採点:\n{facts}\n\n構成:\n{outline}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _ai_pass(scenes: list, measured: dict, axes: list[AxisScore]):
    try:
        raw = llm_client.chat_completion(_ai_prompt(scenes, measured, axes), temperature=0.2)
        data = parse_json_object(raw)
    except (
        JSONExtractionError,
        llm_client.LLMUnavailableError,
        llm_client.LLMTimeoutError,
        llm_client.LLMResponseError,
        llm_client.LLMNotReadyError,
    ) as exc:
        logger.info("AI video review unavailable: %s", exc)
        return [], [], ""
    except Exception:
        logger.exception("AI video review failed")
        return [], [], ""

    findings: list[ReviewFinding] = []
    for item in data.get("findings", [])[:4]:
        try:
            finding = ReviewFinding.model_validate(item)
        except Exception:
            continue
        if finding.axis not in AXES:
            continue
        findings.append(finding)
    strengths = [str(s)[:120] for s in data.get("strengths", [])][:3]
    return findings, strengths, str(data.get("summary", ""))[:400]


# ----------------------------------------------------------------- entry


def review(
    output_path: Path,
    scenes: list,
    cues: list,
    *,
    strategy=None,
    trend: TrendContext | None = None,
    max_chars_per_line: int = 14,
    has_bgm: bool = False,
    has_narration: bool = False,
    iteration: int = 0,
    use_ai: bool = True,
) -> VideoReview:
    """Scores one rendered video. Never raises."""
    measured = measure(output_path)
    if measured.get("error"):
        return VideoReview(
            performed=False,
            iteration=iteration,
            error=str(measured["error"]),
            measured=measured,
            output_path=str(output_path),
            summary=f"完成動画を解析できませんでした: {measured['error']}",
        )

    profile = trend.profile if trend is not None else None
    axes: list[AxisScore] = []
    findings: list[ReviewFinding] = []
    for scorer in (
        lambda: _score_hook(scenes, measured),
        lambda: _score_pacing(scenes, measured, profile),
        lambda: _score_visual(measured),
        lambda: _score_subtitle(scenes, cues, measured, max_chars_per_line),
        lambda: _score_audio(measured, has_bgm, has_narration),
        lambda: _score_story(scenes, strategy),
        lambda: _score_trend(scenes, measured, trend),
    ):
        axis, axis_findings = scorer()
        axes.append(axis)
        findings.extend(axis_findings)

    reviewed_by = "rules"
    strengths: list[str] = []
    summary = ""
    if use_ai and scenes:
        ai_findings, strengths, summary = _ai_pass(scenes, measured, axes)
        if ai_findings or strengths or summary:
            reviewed_by = "rules+ai"
            findings.extend(ai_findings)

    # The overall score is the mean of the axes that could actually be
    # evaluated. An axis that scored 0 because it was not applicable
    # (trend alignment with no trend data) would otherwise drag the whole
    # video down for a reason that has nothing to do with the video.
    scored = [
        a
        for a in axes
        if not (a.axis == "trend_alignment" and (trend is None or not trend.used))
    ]
    overall = sum(a.score for a in scored) / len(scored) if scored else 0.0

    if not summary:
        major = sum(1 for f in findings if f.severity == "major")
        summary = (
            f"総合{overall:.0f}点。大きな問題は見つかりませんでした。"
            if major == 0
            else f"総合{overall:.0f}点。重要な指摘が{major}件あります。"
        )

    return VideoReview(
        performed=True,
        iteration=iteration,
        overall_score=_clamp(overall),
        axes=axes,
        findings=findings,
        strengths=strengths,
        summary=summary,
        measured=measured,
        reviewed_by=reviewed_by,
        output_path=str(output_path),
    )


def to_json(result: VideoReview) -> str:
    return json.dumps(result.model_dump(), ensure_ascii=False)
