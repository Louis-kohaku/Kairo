from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_project_or_404
from app.core.db import get_db
from app.core.paths import project_dir
from app.models.job import Job
from app.models.project import Project
from app.schemas.schemas import JobOut
from app.services import job_log, job_manager

router = APIRouter(prefix="/api", tags=["jobs"])


def _submission_filename(project_name: str, job: Job) -> str:
    """Builds the "提出用" filename a downloaded render is saved as:
    kairo_<slugified project name>_<date>.mp4. Falls back to the job id if
    the project name has no usable ASCII/Japanese-safe characters once
    filesystem-unsafe characters are stripped.
    """
    slug = re.sub(r"[^\w\-]+", "_", project_name, flags=re.UNICODE).strip("_")
    date_part = job.updated_at.strftime("%Y%m%d") if job.updated_at else datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"kairo_{slug or job.id}_{date_part}.mp4"


@router.post("/projects/{project_id}/render", response_model=JobOut)
async def start_render(
    project_id: str,
    burn_subtitles: bool = False,
    crf: int = 18,
    db: Session = Depends(get_db),
):
    get_project_or_404(db, project_id)
    crf = max(0, min(51, crf))
    return job_manager.enqueue_render_job(db, project_id, burn_subtitles, crf)


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


@router.get("/jobs/{job_id}/log")
def get_job_log(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    log_text = job_log.read_log(job.project_id, job.type, job_id)
    if log_text is None:
        raise HTTPException(status_code=404, detail="Log not available for this job")
    return {"log": log_text}


@router.api_route("/jobs/{job_id}/download", methods=["GET", "HEAD"])
def download_render(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None or not job.output_path:
        raise HTTPException(status_code=404, detail="Render output not available")

    path = project_dir(job.project_id) / job.output_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="Render file missing on disk")

    project = db.get(Project, job.project_id)
    filename = _submission_filename(project.name if project else job.project_id, job)
    return FileResponse(path, media_type="video/mp4", filename=filename)
