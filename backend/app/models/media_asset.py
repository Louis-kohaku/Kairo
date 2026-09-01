from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.project import Project


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MediaAsset(Base):
    """A source file imported into a project (video or audio)."""

    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)

    kind: Mapped[str] = mapped_column(String)  # "video" | "audio"
    original_filename: Mapped[str] = mapped_column(String)
    stored_path: Mapped[str] = mapped_column(String)  # relative to project dir

    duration: Mapped[float] = mapped_column(Float, default=0.0)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    has_audio: Mapped[bool] = mapped_column(Boolean, default=False)
    video_codec: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    audio_codec: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    imported_at: Mapped[datetime] = mapped_column(default=_now)

    project: Mapped["Project"] = relationship(back_populates="media_assets")
