from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.media_asset import MediaAsset
    from app.models.project import Project


def _uuid() -> str:
    return uuid.uuid4().hex


class Track(Base):
    """A single track in a project's timeline (one video track, optionally
    one background-music audio track for Phase 1)."""

    __tablename__ = "tracks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    type: Mapped[str] = mapped_column(String)  # "video" | "audio"
    name: Mapped[str] = mapped_column(String, default="")
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    project: Mapped["Project"] = relationship(back_populates="tracks")
    clips: Mapped[list["Clip"]] = relationship(
        back_populates="track",
        cascade="all, delete-orphan",
        order_by="Clip.order_index",
    )


class Clip(Base):
    """A trimmed reference to a MediaAsset placed at a position in a track.

    Clips within a track are laid out back-to-back in `order_index` order;
    Phase 1 does not support free-form overlapping placement.
    """

    __tablename__ = "clips"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    track_id: Mapped[str] = mapped_column(ForeignKey("tracks.id"), nullable=False)
    media_asset_id: Mapped[str] = mapped_column(
        ForeignKey("media_assets.id"), nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    in_point: Mapped[float] = mapped_column(Float, default=0.0)
    out_point: Mapped[float] = mapped_column(Float, default=0.0)
    volume: Mapped[float] = mapped_column(Float, default=1.0)

    track: Mapped["Track"] = relationship(back_populates="clips")
    media_asset: Mapped["MediaAsset"] = relationship()

    @property
    def duration(self) -> float:
        return max(0.0, self.out_point - self.in_point)
