"""The production report and `assets-used.json`.

Two artefacts, one purpose: after the video exists, the user must be able to
ask "what made this, and what is in it" and get an answer that was recorded
at the time rather than reconstructed later.

`assets-used.json` is written into the project directory next to the render.
It is the licence audit trail - every external asset, its source, its
licence, and whether it obliges the video to carry a credit - and it is
generated from the decisions the pipeline actually acted on, not from a
fresh query that might now return something different.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import LLM_BASE_URL
from app.core.paths import project_dir
from app.schemas.production_assets import AssetDecisions
from app.schemas.review import IterationRecord, ProductionReport, VideoReview
from app.schemas.trend import TrendContext

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_assets_used(
    project_id: str,
    decisions: AssetDecisions | None,
    *,
    material_origins: dict[str, int] | None = None,
) -> dict:
    """The licence audit record for one finished video."""
    entries: list[dict] = []
    if decisions is not None:
        for choice in [decisions.font, decisions.music, *decisions.sfx_assets]:
            if choice is None or not choice.found:
                continue
            entries.append(
                {
                    "kind": choice.kind,
                    "name": choice.name,
                    "family": choice.family,
                    "path": choice.path,
                    "source": choice.source,
                    "source_url": choice.source_url,
                    "license": choice.license.model_dump(),
                    "selected_because": choice.reason,
                }
            )

    unresolved = []
    if decisions is not None:
        for choice in [decisions.font, decisions.music]:
            if choice is not None and not choice.found:
                unresolved.append({"kind": choice.kind, "reason": choice.reason})

    return {
        "schema": "kairo/assets-used@1",
        "project_id": project_id,
        "generated_at": _now(),
        "assets": entries,
        "unresolved": unresolved,
        "attribution_required": decisions.attribution_lines() if decisions else [],
        "user_material": material_origins or {},
        "note": (
            "この動画の制作に使用した外部素材の一覧です。ライセンス条件は各素材の "
            "license.url を確認してください。ユーザー自身がアップロードした素材の"
            "権利確認はユーザーの責任です。"
        ),
    }


def write_assets_used(project_id: str, payload: dict) -> Path:
    path = project_dir(project_id) / "assets-used.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_report(
    *,
    project,
    run,
    decisions: AssetDecisions | None,
    trend: TrendContext | None,
    review: VideoReview | None,
    iterations: list[IterationRecord],
    strategy=None,
    model_id: str = "",
    duration: float = 0.0,
    transcription_engine: str = "",
    tts_engine: str = "",
    assets_used_path: str = "",
) -> ProductionReport:
    report = ProductionReport(
        project_id=project.id,
        project_name=project.name,
        run_id=run.id,
        title=getattr(strategy, "title", "") or project.name,
        instruction=run.instruction,
        duration_seconds=round(duration, 2),
        orientation=run.orientation,
        resolution=f"{project.width}x{project.height}",
        llm_provider="LM Studio (OpenAI互換API)",
        llm_endpoint=LLM_BASE_URL,
        llm_model=model_id,
        transcription_engine=transcription_engine,
        tts_engine=tts_engine,
        rendering_engine="FFmpeg",
        output_path=run.output_path or "",
        assets_used_path=assets_used_path,
        generated_at=_now(),
    )

    if trend is not None:
        report.trend_used = trend.used
        report.trend_reason = trend.reason
        report.genre = trend.genre
        report.genre_label = trend.genre_label
        report.trend_keywords = [s.keyword for s in trend.signals[:10]]
        report.trend_sources = sorted({s.source for s in trend.signals if s.source})
        report.genre_profile_source = trend.profile_source

    if decisions is not None:
        if decisions.font and decisions.font.found:
            report.font = decisions.font.family or decisions.font.name
            report.font_license = decisions.font.license.name
        if decisions.music and decisions.music.found:
            report.music = decisions.music.name
            report.music_license = decisions.music.license.name
        report.sfx = sorted({p.name for p in decisions.sfx if p.name})
        report.attribution = decisions.attribution_lines()

    report.review = review
    report.iterations = iterations
    report.final_score = review.overall_score if review is not None else 0.0
    return report


def to_json(report: ProductionReport) -> str:
    return json.dumps(report.model_dump(), ensure_ascii=False)


def write_report(project_id: str, report: ProductionReport) -> Path:
    path = project_dir(project_id) / "production-report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path
