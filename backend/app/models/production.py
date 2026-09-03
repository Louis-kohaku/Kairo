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

    # --- Short-form scene design (design doc section 20) ---
    # Why this beat exists and what it should make the viewer feel; the
    # asset, audio and quality stages all read these rather than
    # re-deriving intent from the narration text.
    purpose: Mapped[str] = mapped_column(Text, default="")
    emotion: Mapped[str] = mapped_column(String, default="")
    camera: Mapped[str] = mapped_column(String, default="")
    # The on-screen caption, which is deliberately NOT the narration: a
    # short-form subtitle is a punchy fragment, not a transcript.
    subtitle_text: Mapped[str] = mapped_column(Text, default="")
    sfx: Mapped[str] = mapped_column(String, default="")
    bgm_cue: Mapped[str] = mapped_column(String, default="")
    transition: Mapped[str] = mapped_column(String, default="cut")
    continuity: Mapped[str] = mapped_column(Text, default="")

    # --- Produced material (filled in by the asset/narration stages) ---
    # "auto" lets the asset stage choose; "user" pins a clip the user
    # supplied so a re-run never silently replaces their own footage
    # (section 24).
    asset_source: Mapped[str] = mapped_column(String, default="auto")
    # The footage the user pinned to this scene, if any. Kept separate from
    # `media_asset_id` (the rendered clip) so re-rendering the scene never
    # loses the source it was rendered from.
    user_asset_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # The slice of the pinned footage this scene uses. A 40-second clip
    # dropped into a 3-second beat has to start *somewhere*, and the
    # material analysis has an opinion about where the usable part is;
    # without these the clip would always be taken from 0:00.
    user_asset_start: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    user_asset_end: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Where this scene's visual came from, for the "使用素材" report:
    # user | web | ai_generated | procedural. Set by the asset stage, so a
    # finished video can always say which of its shots were the user's own.
    material_origin: Mapped[str] = mapped_column(String, default="")
    # One line explaining the choice ("海のタグが一致", "不足のためAI生成").
    material_note: Mapped[str] = mapped_column(Text, default="")
    media_asset_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    narration_asset_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    narration_duration: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Absolute position on the finished timeline, recomputed whenever any
    # scene duration changes.
    start_time: Mapped[float] = mapped_column(Float, default=0.0)
    is_hook: Mapped[bool] = mapped_column(Boolean, default=False)

    chapter: Mapped["Chapter"] = relationship(back_populates="scenes")
