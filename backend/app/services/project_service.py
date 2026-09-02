from __future__ import annotations

import shutil

from sqlalchemy.orm import Session

from app.core.paths import create_project_layout, project_dir
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


def update_project(
    db: Session,
    project: Project,
    name: str | None = None,
    fps: float | None = None,
    width: int | None = None,
    height: int | None = None,
) -> Project:
    """Updates a project's output settings (used by the editor's video
    settings panel to change aspect ratio/resolution/fps after creation).
    Does not touch already-rendered files - the next render simply uses the
    new values.
    """
    if name is not None:
        project.name = name
    if fps is not None:
        project.fps = fps
    if width is not None:
        project.width = width
    if height is not None:
        project.height = height
    db.commit()
    db.refresh(project)
    return project


def list_projects(db: Session) -> list[Project]:
    return db.query(Project).order_by(Project.updated_at.desc()).all()


def get_project(db: Session, project_id: str) -> Project | None:
    return db.get(Project, project_id)


def delete_project(db: Session, project: Project) -> None:
    """Deletes a project's DB rows (cascades to media assets, tracks/clips,
    jobs, subtitles, chapters/scenes and generations - see the relationship
    cascades on Project) and its on-disk directory.

    Everything under `project_dir(project_id)` was created by Kairo itself
    (imported media is copied in on upload, generated output is written
    there directly) - nothing there is a user's original file living
    elsewhere, so removing the whole tree is safe.
    """
    project_id = project.id
    db.delete(project)
    db.commit()

    shutil.rmtree(project_dir(project_id), ignore_errors=True)
