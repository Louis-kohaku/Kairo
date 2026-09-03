from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.project import Project


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MediaAsset(Base):
    """A source file imported into a project (video, image or audio).

    Two things beyond the file's own metadata are recorded here, both added
    for the material pipeline:

    * `origin` - where the material came from. Every stage that has to
      prefer the user's own footage over something Kairo produced reads
      this, and the completion screen's "どの素材を使ったか" list is built
      from it. Without it, a scene clip Kairo rendered and a photo the user
      uploaded are indistinguishable rows.
    * `analysis_*` - the result of the material analysis pass, cached on the
      asset so re-opening a project (or resuming a run) never re-analyses
      material that has not changed.
    """

    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)

    kind: Mapped[str] = mapped_column(String)  # "video" | "image" | "audio"
    original_filename: Mapped[str] = mapped_column(String)
    stored_path: Mapped[str] = mapped_column(String)  # relative to project dir

    duration: Mapped[float] = mapped_column(Float, default=0.0)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    has_audio: Mapped[bool] = mapped_column(Boolean, default=False)
    video_codec: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    audio_codec: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # user | web | ai_generated | kairo_clip | kairo_bgm
    # "user" is the default because it is the only value an import can have;
    # everything Kairo produces sets its own origin explicitly.
    origin: Mapped[str] = mapped_column(String, default="user")
    # Free-text provenance for non-user material: the source page/licence
    # for a web asset, the engine for a generated one.
    origin_detail: Mapped[str] = mapped_column(String, default="")

    # pending | done | failed | skipped
    analysis_status: Mapped[str] = mapped_column(String, default="pending")
    analysis_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    analysis_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    imported_at: Mapped[datetime] = mapped_column(default=_now)

    project: Mapped["Project"] = relationship(back_populates="media_assets")
