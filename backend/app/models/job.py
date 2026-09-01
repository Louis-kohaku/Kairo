from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.project import Project


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Every long-running operation (currently just "render") is tracked as a Job
# row so progress survives across requests and, per the design doc's
# resumability requirement, so a crashed/interrupted job is visible instead
# of silently vanishing.
class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    type: Mapped[str] = mapped_column(String)  # "render"
    status: Mapped[str] = mapped_column(String, default="pending")
    # pending | running | completed | failed
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0-100
    message: Mapped[str] = mapped_column(String, default="")
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Short human-readable summary (kept for simple/back-compat display).
    # The full structured Diagnosis JSON (facts/cause/ai_context/etc.) lives
    # in error_detail so clients don't have to guess-parse `error`.
    error_detail: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Which pipeline step was in progress when the job finished/failed, e.g.
    # "planning" / "scene_generation" for a production job.
    step: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    output_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)

    project: Mapped["Project"] = relationship(back_populates="jobs")
