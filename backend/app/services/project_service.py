from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.paths import create_project_layout
from app.models.project import Project
from app.models.timeline import Track


def create_project(db: Session, name: str, fps: float, width: int, height: int) -> Project:
    project = Project(name=name, fps=fps, width=width, height=height)
    db.add(project)
    db.flush()  # assigns project.id

    create_project_layout(project.id)

    video_track = Track(project_id=project.id, type="video", name="Video", order_index=0)
    bgm_track = Track(project_id=project.id, type="audio", name="BGM", order_index=1)
    db.add_all([video_track, bgm_track])

    db.commit()
    db.refresh(project)
    return project


def list_projects(db: Session) -> list[Project]:
    return db.query(Project).order_by(Project.updated_at.desc()).all()


def get_project(db: Session, project_id: str) -> Project | None:
    return db.get(Project, project_id)
