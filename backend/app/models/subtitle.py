from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.project import Project


def _uuid() -> str:
    return uuid.uuid4().hex


class SubtitleCue(Base):
    """A single caption line, positioned in absolute project-timeline
    seconds (i.e. against the assembled video track, the same time axis
    the render pipeline and the playhead use)."""

    __tablename__ = "subtitle_cues"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    start: Mapped[float] = mapped_column(Float)
    end: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(String, default="")

    project: Mapped["Project"] = relationship(back_populates="subtitle_cues")
