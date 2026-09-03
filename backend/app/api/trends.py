"""HTTP surface for Trend Intelligence.

Everything the Trends screen needs: what has been collected, what it means
per genre, which sources are connected (and why the disconnected ones are
disconnected), and a manual refresh for a user who does not want to wait
for the next scheduled pass.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.services import settings_service
from app.services.trends import collector, genre as genre_module, service, sources, worker

router = APIRouter(prefix="/api/trends", tags=["trends"])


class CollectRequest(BaseModel):
    region: str | None = None
    sources: list[str] | None = None


class ProfileRefreshRequest(BaseModel):
    region: str | None = None
    force: bool = Field(
        default=False,
        description=(
            "証拠が少ないジャンルも解析する。既定ではKairo組み込みの定石のままにする。"
        ),
    )


@router.get("")
def overview(db: Session = Depends(get_db)):
    return service.overview(db).model_dump()


@router.get("/signals")
def signals(
    category: str | None = None,
    platform: str | None = None,
    region: str | None = None,
    include_stale: bool = False,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    settings = settings_service.get_settings().trends
    rows = service.store.query_signals(
        db,
        category=category,
        platform=platform,
        region=region or settings.region,
        include_stale=include_stale,
        limit=max(1, min(limit, 200)),
    )
    return {"signals": [s.model_dump() for s in rows]}


@router.get("/genres")
def genres(region: str | None = None, db: Session = Depends(get_db)):
    return {"genres": service.genre_breakdown(db, region=region)}


@router.get("/sources")
def source_list():
    """Connected and deliberately-unconnected trend sources.

    The unavailable platforms are included on purpose: a UI that simply
    omitted TikTok would look like an oversight rather than the licensing
    decision it is.
    """
    return {
        "sources": [s.model_dump() for s in service.source_statuses()],
        "unavailable": list(sources.UNAVAILABLE_PLATFORMS),
        "worker": worker.status(),
    }


@router.post("/collect")
def collect(payload: CollectRequest | None = None):
    """Runs a collection pass now, synchronously, and returns the outcome."""
    payload = payload or CollectRequest()
    result = collector.collect_once(region=payload.region, source_ids=payload.sources)
    if result.get("status") == "busy":
        raise HTTPException(409, result.get("detail", "既に実行中です"))
    return result


@router.post("/profiles/refresh")
def refresh_profiles(payload: ProfileRefreshRequest | None = None, db: Session = Depends(get_db)):
    payload = payload or ProfileRefreshRequest()
    settings = settings_service.get_settings().trends
    refreshed = collector.refresh_profiles(
        db, region=payload.region or settings.region, force=payload.force
    )
    return {
        "refreshed": refreshed,
        "labels": [genre_module.label(g) for g in refreshed],
    }


@router.get("/classify")
def classify(instruction: str):
    """Which genre a production brief falls into. Used by the launcher to
    show the user what trend data their video will be planned against."""
    genre_id = genre_module.classify_instruction(instruction)
    return {"genre": genre_id, "label": genre_module.label(genre_id)}


@router.get("/context")
def context(instruction: str, db: Session = Depends(get_db)):
    """A preview of the exact trend context a run with this brief would use."""
    return service.build_context(db, instruction).model_dump()
