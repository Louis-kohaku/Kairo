from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Local-only record of how long a task actually took on *this* machine
# (design doc section 37): never sent anywhere, used only by
# time_estimate_service to narrow its estimate ranges once enough samples
# exist for a given task/engine/resolution combination.
class PerfRecord(Base):
    __tablename__ = "perf_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    task_type: Mapped[str] = mapped_column(String)  # "image_to_video" | "production"
    engine_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    model_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    num_frames: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_seconds_requested: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    elapsed_seconds: Mapped[float] = mapped_column(Float)
    ram_gb: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gpu_names: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=_now)
