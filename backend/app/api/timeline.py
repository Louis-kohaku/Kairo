from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_project_or_404
from app.core.db import get_db
from app.schemas.schemas import (
    ClipCreate,
    ClipOut,
    ClipSplit,
    ClipUpdate,
    TimelineOut,
    TrackOut,
)
from app.services import timeline_service

router = APIRouter(prefix="/api", tags=["timeline"])


@router.get("/projects/{project_id}/timeline", response_model=TimelineOut)
def get_timeline(project_id: str, db: Session = Depends(get_db)):
    get_project_or_404(db, project_id)
    tracks = timeline_service.get_tracks(db, project_id)
    return TimelineOut(
        tracks=[TrackOut.model_validate(t) for t in tracks],
        total_duration=timeline_service.timeline_duration(tracks),
    )


@router.post("/tracks/{track_id}/clips", response_model=ClipOut)
def add_clip(track_id: str, payload: ClipCreate, db: Session = Depends(get_db)):
    try:
        return timeline_service.add_clip(
            db,
            track_id,
            payload.media_asset_id,
            payload.in_point,
            payload.out_point,
            payload.volume,
            payload.index,
        )
    except timeline_service.TimelineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/clips/{clip_id}", response_model=ClipOut)
def update_clip(clip_id: str, payload: ClipUpdate, db: Session = Depends(get_db)):
    try:
        return timeline_service.update_clip(
            db, clip_id, payload.in_point, payload.out_point, payload.volume
        )
    except timeline_service.TimelineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/clips/{clip_id}")
def delete_clip(clip_id: str, db: Session = Depends(get_db)):
    try:
        timeline_service.delete_clip(db, clip_id)
    except timeline_service.TimelineError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/tracks/{track_id}/split", response_model=list[ClipOut])
def split_clip(track_id: str, payload: ClipSplit, db: Session = Depends(get_db)):
    try:
        first, second = timeline_service.split_clip(db, track_id, payload.time)
    except timeline_service.TimelineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [first, second]
