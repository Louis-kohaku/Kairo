from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import (
    DEFAULT_MIN_KEEP_DURATION,
    DEFAULT_SILENCE_MIN_DURATION,
    DEFAULT_SILENCE_NOISE_DB,
    DEFAULT_SILENCE_PADDING,
)
from app.core.db import get_db
from app.core.paths import project_dir
from app.schemas.schemas import ClipOut
from app.services import media_service, timeline_service
from app.services.ffmpeg.silence import compute_keep_segments, detect_silence

router = APIRouter(prefix="/api", tags=["cut"])


class Segment(BaseModel):
    start: float
    end: float


class SilenceCutPlan(BaseModel):
    duration: float
    keep_segments: list[Segment]
    silence_segments: list[Segment]


class DetectSilenceRequest(BaseModel):
    noise_db: float = DEFAULT_SILENCE_NOISE_DB
    min_duration: float = DEFAULT_SILENCE_MIN_DURATION
    padding: float = DEFAULT_SILENCE_PADDING
    min_keep: float = DEFAULT_MIN_KEEP_DURATION


class ApplyCutPlanRequest(BaseModel):
    media_asset_id: str
    keep_segments: list[Segment]
    index: int | None = None


@router.post("/media/{asset_id}/detect-silence", response_model=SilenceCutPlan)
def detect_silence_endpoint(
    asset_id: str, payload: DetectSilenceRequest, db: Session = Depends(get_db)
):
    asset = media_service.get_media(db, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Media asset not found")

    path = project_dir(asset.project_id) / asset.stored_path
    silences = detect_silence(path, asset.duration, payload.noise_db, payload.min_duration)
    keep = compute_keep_segments(asset.duration, silences, payload.padding, payload.min_keep)

    return SilenceCutPlan(
        duration=asset.duration,
        keep_segments=[Segment(start=s, end=e) for s, e in keep],
        silence_segments=[Segment(start=s, end=e) for s, e in silences],
    )


@router.post("/tracks/{track_id}/apply-cut-plan", response_model=list[ClipOut])
def apply_cut_plan(track_id: str, payload: ApplyCutPlanRequest, db: Session = Depends(get_db)):
    if not payload.keep_segments:
        raise HTTPException(status_code=400, detail="keep_segments must not be empty")

    created = []
    try:
        insert_at = payload.index
        for seg in payload.keep_segments:
            clip = timeline_service.add_clip(
                db,
                track_id,
                payload.media_asset_id,
                seg.start,
                seg.end,
                1.0,
                insert_at,
            )
            created.append(clip)
            if insert_at is not None:
                insert_at += 1
    except timeline_service.TimelineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return created
