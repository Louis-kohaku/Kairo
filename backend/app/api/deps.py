from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.project import Project


def get_project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return project
