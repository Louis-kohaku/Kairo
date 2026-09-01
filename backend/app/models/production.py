from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.project import Project


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ProductionSpec(Base):
    """The one-time brief a project's AI production run was made from."""

    __tablename__ = "production_specs"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id"), primary_key=True
    )
    instruction: Mapped[str] = mapped_column(String)
    target_duration_minutes: Mapped[float] = mapped_column(Float)
    title: Mapped[str] = mapped_column(String, default="")
    target_audience: Mapped[str] = mapped_column(String, default="")
    tone: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)

    project: Mapped["Project"] = relationship(back_populates="production_spec")


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String)
    summary: Mapped[str] = mapped_column(String, default="")

    project: Mapped["Project"] = relationship(back_populates="chapters")
    scenes: Mapped[list["Scene"]] = relationship(
        back_populates="chapter",
        cascade="all, delete-orphan",
        order_by="Scene.order_index",
    )


class Scene(Base):
    """A planned beat of the video: narration + what to show for it.

    Status mirrors section 7 of the design doc: pending (planned, not yet
    generated) -> planning -> generating -> generated -> checking ->
    approved, or failed. Phase 4 only ever produces "pending" scenes -
    the generation states are exercised starting Phase 5.
    """

    __tablename__ = "scenes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    narration: Mapped[str] = mapped_column(String, default="")
    visual_type: Mapped[str] = mapped_column(String, default="ai_image")
    visual_prompt: Mapped[str] = mapped_column(String, default="")
    estimated_duration: Mapped[float] = mapped_column(Float, default=5.0)
    status: Mapped[str] = mapped_column(String, default="pending")

    chapter: Mapped["Chapter"] = relationship(back_populates="scenes")
