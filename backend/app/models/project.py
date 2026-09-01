from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Float, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    fps: Mapped[float] = mapped_column(Float, default=30.0)
    width: Mapped[int] = mapped_column(default=1920)
    height: Mapped[int] = mapped_column(default=1080)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)

    media_assets: Mapped[list["MediaAsset"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    tracks: Mapped[list["Track"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    jobs: Mapped[list["Job"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    subtitle_cues: Mapped[list["SubtitleCue"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="SubtitleCue.order_index",
    )
    chapters: Mapped[list["Chapter"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="Chapter.order_index",
    )
    production_spec: Mapped["ProductionSpec | None"] = relationship(
        back_populates="project", cascade="all, delete-orphan", uselist=False
    )
    generations: Mapped[list["Generation"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="Generation.created_at.desc()",
        foreign_keys="Generation.project_id",
    )


from app.models.generation import Generation  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.media_asset import MediaAsset  # noqa: E402
from app.models.production import Chapter, ProductionSpec  # noqa: E402
from app.models.subtitle import SubtitleCue  # noqa: E402
from app.models.timeline import Track  # noqa: E402
