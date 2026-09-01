from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from app.api.deps import get_project_or_404
from app.core.db import get_db
from app.models.subtitle import SubtitleCue
from app.schemas.schemas import JobOut
from app.services import job_manager
from app.services.srt import build_srt

router = APIRouter(prefix="/api", tags=["subtitles"])


class SubtitleCueOut(BaseModel):
    id: str
    project_id: str
    order_index: int
    start: float
    end: float
    text: str

    class Config:
        from_attributes = True


class SubtitleCueUpdate(BaseModel):
    start: Optional[float] = None
    end: Optional[float] = None
    text: Optional[str] = None


@router.post("/projects/{project_id}/subtitles/generate", response_model=JobOut)
async def generate_subtitles(project_id: str, db: Session = Depends(get_db)):
    get_project_or_404(db, project_id)
    return job_manager.enqueue_subtitle_job(db, project_id)


@router.get("/projects/{project_id}/subtitles", response_model=list[SubtitleCueOut])
def list_subtitles(project_id: str, db: Session = Depends(get_db)):
    get_project_or_404(db, project_id)
    return (
        db.query(SubtitleCue)
        .filter(SubtitleCue.project_id == project_id)
        .order_by(SubtitleCue.order_index)
        .all()
    )


@router.patch("/subtitles/{cue_id}", response_model=SubtitleCueOut)
def update_subtitle(cue_id: str, payload: SubtitleCueUpdate, db: Session = Depends(get_db)):
    cue = db.get(SubtitleCue, cue_id)
    if cue is None:
        raise HTTPException(status_code=404, detail="Subtitle cue not found")
    if payload.start is not None:
        cue.start = payload.start
    if payload.end is not None:
        cue.end = payload.end
    if payload.text is not None:
        cue.text = payload.text
    db.commit()
    db.refresh(cue)
    return cue


@router.delete("/subtitles/{cue_id}")
def delete_subtitle(cue_id: str, db: Session = Depends(get_db)):
    cue = db.get(SubtitleCue, cue_id)
    if cue is None:
        raise HTTPException(status_code=404, detail="Subtitle cue not found")
    db.delete(cue)
    db.commit()
    return {"ok": True}


@router.get("/projects/{project_id}/subtitles/srt", response_class=PlainTextResponse)
def export_srt(project_id: str, db: Session = Depends(get_db)):
    get_project_or_404(db, project_id)
    cues = (
        db.query(SubtitleCue)
        .filter(SubtitleCue.project_id == project_id)
        .order_by(SubtitleCue.order_index)
        .all()
    )
    return PlainTextResponse(build_srt(cues), media_type="text/plain; charset=utf-8")
