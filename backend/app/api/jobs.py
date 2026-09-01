from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_project_or_404
from app.core.db import get_db
from app.core.paths import project_dir
from app.models.job import Job
from app.schemas.schemas import JobOut
from app.services import job_manager

router = APIRouter(prefix="/api", tags=["jobs"])


@router.post("/projects/{project_id}/render", response_model=JobOut)
async def start_render(
    project_id: str, burn_subtitles: bool = False, db: Session = Depends(get_db)
):
    get_project_or_404(db, project_id)
    return job_manager.enqueue_render_job(db, project_id, burn_subtitles)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/projects/{project_id}/jobs", response_model=list[JobOut])
def list_jobs(project_id: str, db: Session = Depends(get_db)):
    get_project_or_404(db, project_id)
    return (
        db.query(Job)
        .filter(Job.project_id == project_id)
        .order_by(Job.created_at.desc())
        .all()
    )


@router.get("/jobs/{job_id}/download")
def download_render(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None or not job.output_path:
        raise HTTPException(status_code=404, detail="Render output not available")

    path = project_dir(job.project_id) / job.output_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="Render file missing on disk")

    return FileResponse(path, media_type="video/mp4", filename=f"{job_id}.mp4")
