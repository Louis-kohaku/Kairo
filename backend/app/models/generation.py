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


class Generation(Base):
    """One AI media-generation attempt (section 36/44 "生成履歴").

    Kept separate from Job: a Job row is the generic "something is running
    in the background" record used for polling, while Generation is the
    domain record of *what was generated* - engine, prompt, params, and
    result - so it survives as history even after the Job row's relevance
    fades.
    """

    __tablename__ = "generations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)

    kind: Mapped[str] = mapped_column(String)  # "image_to_video" (more kinds later)
    engine_id: Mapped[str] = mapped_column(String)
    prompt: Mapped[str] = mapped_column(String, default="")
    source_image_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    params_json: Mapped[str] = mapped_column(String, default="{}")

    status: Mapped[str] = mapped_column(String, default="pending")
    # pending | running | completed | failed
    job_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    output_media_asset_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("media_assets.id"), nullable=True
    )
    elapsed_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Short human-readable summary; the full Diagnosis JSON lives in
    # error_detail (see app.models.job.Job for the same split).
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    error_detail: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)

    project: Mapped["Project"] = relationship(back_populates="generations")
