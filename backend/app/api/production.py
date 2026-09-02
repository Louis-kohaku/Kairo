from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_project_or_404
from app.core.db import get_db
from app.models.production import Chapter, ProductionSpec, Scene
from app.schemas.schemas import JobOut
from app.services import job_manager

router = APIRouter(prefix="/api", tags=["production"])


class ProduceRequest(BaseModel):
    instruction: str
    target_duration_minutes: float = 10.0


class SceneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    chapter_id: str
    project_id: str
    order_index: int
    narration: str
    visual_type: str
    visual_prompt: str
    estimated_duration: float
    status: str


class ChapterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    order_index: int
    title: str
    summary: str
    scenes: list[SceneOut] = []


class ProductionSpecOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    instruction: str
    target_duration_minutes: float
    title: str
    target_audience: str
    tone: str


class ProductionOut(BaseModel):
    spec: Optional[ProductionSpecOut]
    chapters: list[ChapterOut]


class SceneUpdate(BaseModel):
    narration: Optional[str] = None
    visual_type: Optional[str] = None
    visual_prompt: Optional[str] = None
    estimated_duration: Optional[float] = None
    status: Optional[str] = None


@router.post("/projects/{project_id}/produce", response_model=JobOut)
async def produce(project_id: str, payload: ProduceRequest, db: Session = Depends(get_db)):
    get_project_or_404(db, project_id)
    return job_manager.enqueue_production_job(
        db, project_id, payload.instruction, payload.target_duration_minutes
    )


@router.get("/projects/{project_id}/production", response_model=ProductionOut)
def get_production(project_id: str, db: Session = Depends(get_db)):
    get_project_or_404(db, project_id)
    spec = db.get(ProductionSpec, project_id)
    chapters = (
        db.query(Chapter)
        .filter(Chapter.project_id == project_id)
        .order_by(Chapter.order_index)
        .all()
    )
    return ProductionOut(spec=spec, chapters=chapters)


@router.patch("/scenes/{scene_id}", response_model=SceneOut)
def update_scene(scene_id: str, payload: SceneUpdate, db: Session = Depends(get_db)):
    scene = db.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="Scene not found")
    for field in ("narration", "visual_type", "visual_prompt", "estimated_duration", "status"):
        value = getattr(payload, field)
        if value is not None:
            setattr(scene, field, value)
    db.commit()
    db.refresh(scene)
    return scene


@router.delete("/scenes/{scene_id}")
def delete_scene(scene_id: str, db: Session = Depends(get_db)):
    scene = db.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="Scene not found")
    db.delete(scene)
    db.commit()
    return {"ok": True}


@router.post("/scenes/{scene_id}/regenerate", response_model=JobOut)
async def regenerate_scene(scene_id: str, db: Session = Depends(get_db)):
    scene = db.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="Scene not found")
    return job_manager.enqueue_scene_regenerate_job(db, scene.project_id, scene_id)
