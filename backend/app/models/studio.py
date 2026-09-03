"""Persistent state for Kairo's AI production studio.

Three tables, all additive to the existing schema:

* `ProductionRun`  - one end-to-end production attempt (Full Auto or AI
  Co-Creation). It is the thing that can be paused, stopped and resumed,
  and it holds the artefacts the pipeline produces along the way (web
  research, production strategy, quality report) so a crash or a browser
  reload never loses them.
* `ProductionEvent` - the append-only structured event log every phase
  emits. This is the single source the progress UI, the "AI作業状況" panel,
  the user-facing log and the technical log are all rendered from, so
  Full Auto and Co-Creation cannot drift apart in what they report.
* `ChangeProposal` - an AI Co-Creation edit, with the operations it wants
  to perform, the reason, and a snapshot of the state it replaced so the
  change can be undone.

`Scene` (app/models/production.py) gains its extra short-form fields via
db.py's additive-column migration rather than a second table, so existing
projects keep working untouched.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ProductionRun(Base):
    """One AI production attempt for a project.

    A project has at most one *active* run; older runs stay as history.
    `phase` + `resume_phase` are what make section 34's "Scene 4の素材生成
    から再開します" possible: every phase writes its completion back here
    before moving on, so resuming restarts at the first unfinished phase
    instead of from the beginning.
    """

    __tablename__ = "production_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)

    mode: Mapped[str] = mapped_column(String, default="full_auto")
    # full_auto | co_creation

    status: Mapped[str] = mapped_column(String, default="pending")
    # pending | running | paused | pausing | stopping | stopped | completed | failed

    phase: Mapped[str] = mapped_column(String, default="environment")
    task: Mapped[str] = mapped_column(String, default="")
    progress: Mapped[float] = mapped_column(Float, default=0.0)

    instruction: Mapped[str] = mapped_column(Text, default="")
    target_duration_seconds: Mapped[float] = mapped_column(Float, default=60.0)
    orientation: Mapped[str] = mapped_column(String, default="vertical")
    # vertical (9:16) | horizontal (16:9) | square (1:1)

    # JSON blobs for the artefacts each stage produces. Stored as text so
    # the shape can evolve without a migration; the pydantic schemas in
    # app/schemas/studio.py are the contract for reading them back.
    # How the user wants their own material used: ai_auto (Kairo picks),
    # use_all (fit every uploaded file in), selected (only the ids below).
    material_mode: Mapped[str] = mapped_column(String, default="ai_auto")
    # JSON list of asset ids, only meaningful in "selected" mode.
    selected_asset_ids: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    material_plan_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    research_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    strategy_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quality_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_plan_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    improvement_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Phases already finished, comma-separated in execution order. Resume
    # skips everything listed here.
    completed_phases: Mapped[str] = mapped_column(Text, default="")
    resume_phase: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    render_job_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    output_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class ProductionEvent(Base):
    """One structured entry in a run's production log (section 8).

    `level` splits section 51's two logs apart at the source rather than in
    the UI: "user" events are the plain-language narrative ("Scene 3の映像を
    生成しています"), "tech" events are the request/command detail. Both are
    stored; the UI decides which to show by default.
    """

    __tablename__ = "production_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("production_runs.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, default=0)

    phase: Mapped[str] = mapped_column(String, default="")
    task: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="running")
    # running | done | failed | skipped | paused | info

    level: Mapped[str] = mapped_column(String, default="user")  # user | tech

    scene_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    target: Mapped[str] = mapped_column(String, default="")
    message: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    next_task: Mapped[str] = mapped_column(String, default="")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    model: Mapped[str] = mapped_column(String, default="")

    error_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class ChangeProposal(Base):
    """An AI Co-Creation change: what the AI wants to do, why, and what it
    replaced (so Undo works - section 43).

    Nothing here is applied until `status` becomes "applied", which is what
    makes section 32's confirm-before-applying behaviour possible without
    the executing code needing a separate "dry run" path.
    """

    __tablename__ = "change_proposals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    run_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    instruction: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    ops_json: Mapped[str] = mapped_column(Text, default="[]")
    preview_json: Mapped[str] = mapped_column(Text, default="[]")

    status: Mapped[str] = mapped_column(String, default="pending")
    # pending | applied | cancelled | undone | failed

    # State the apply overwrote, for Undo. Only the touched rows, not the
    # whole project.
    undo_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class ChatMessage(Base):
    """AI Co-Creation conversation history, kept per project so reopening a
    project restores the conversation that produced its current state."""

    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    role: Mapped[str] = mapped_column(String, default="user")  # user | assistant
    content: Mapped[str] = mapped_column(Text, default="")
    proposal_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)
