"""Accumulated trend intelligence (動画制作エージェント Kairo).

Trends are *stored*, not searched-on-demand. A production run that had to
go to the network before it could plan would be offline-fragile and slow,
and it would only ever see the moment it happened to run. A background
worker collects from the sources in `services/trends/sources.py` on an
interval and writes here; the planner reads what has accumulated.

Two tables:

* `TrendSignal` - one observed keyword on one platform in one region.
  Deduplicated on (platform, keyword_norm, region) so re-collecting the
  same keyword updates the existing row (and its growth rate) instead of
  piling up duplicates.
* `GenreProfile` - what videos in a genre tend to look like (duration,
  hook, cut tempo, subtitle style, audio). Derived, cached, and always
  carrying the evidence count it was derived from, so the UI can say how
  much it is actually based on.

Nothing in here is ever invented: a signal row exists because a named
source returned it, and `source_url` is the address it came from.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TrendSignal(Base):
    """One trend observation from one source."""

    __tablename__ = "trend_signals"
    __table_args__ = (
        UniqueConstraint("platform", "keyword_norm", "region", name="uq_trend_identity"),
        Index("ix_trend_category_score", "category", "score"),
        Index("ix_trend_observed", "observed_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)

    # Where it was observed: google_trends | wikipedia | youtube | web_research
    platform: Mapped[str] = mapped_column(String, nullable=False)
    keyword: Mapped[str] = mapped_column(String, nullable=False)
    # Case-folded / whitespace-collapsed form, used only for dedupe so the
    # display keyword keeps the source's own capitalisation.
    keyword_norm: Mapped[str] = mapped_column(String, nullable=False)

    # Kairo's own genre taxonomy (services/trends/genre.py). "unknown" when
    # the classifier could not place it - never guessed into a real genre.
    category: Mapped[str] = mapped_column(String, default="unknown")
    region: Mapped[str] = mapped_column(String, default="JP")

    # 0-100, comparable across sources because every provider normalises to
    # this range. `raw_score` keeps the provider's own number for auditing.
    score: Mapped[float] = mapped_column(Float, default=0.0)
    raw_score: Mapped[float] = mapped_column(Float, default=0.0)
    # Change in `score` since the previous observation of the same signal,
    # in points. 0.0 on a first sighting (no previous value to compare to).
    growth_rate: Mapped[float] = mapped_column(Float, default=0.0)
    # How many times this signal has been seen. A keyword that keeps coming
    # back is a stronger signal than one that appeared once.
    observation_count: Mapped[int] = mapped_column(Integer, default=1)

    observed_at: Mapped[datetime] = mapped_column(default=_now)
    first_seen_at: Mapped[datetime] = mapped_column(default=_now)
    # After this, the row is stale and excluded from planning. Rows are not
    # deleted at expiry (history is useful); they are filtered.
    expires_at: Mapped[datetime] = mapped_column(default=_now)

    source: Mapped[str] = mapped_column(String, default="")
    source_url: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class GenreProfile(Base):
    """Cached "how videos in this genre are built" analysis."""

    __tablename__ = "genre_profiles"
    __table_args__ = (
        UniqueConstraint("genre", "region", name="uq_genre_profile"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    genre: Mapped[str] = mapped_column(String, nullable=False)
    region: Mapped[str] = mapped_column(String, default="JP")

    # A serialised GenreProfileData (app/schemas/trend.py).
    profile_json: Mapped[str] = mapped_column(Text, default="{}")
    # How many trend signals the analysis was built from. 0 means the
    # profile is Kairo's built-in short-form convention, not a finding.
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    # "defaults" (built-in conventions) | "llm" (analysed from signals)
    derived_from: Mapped[str] = mapped_column(String, default="defaults")

    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class TrendCollectionRun(Base):
    """One pass of the background collector, so the UI can show when the
    trend data was last refreshed and what failed."""

    __tablename__ = "trend_collection_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    started_at: Mapped[datetime] = mapped_column(default=_now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String, default="running")
    # running | ok | partial | failed
    collected: Mapped[int] = mapped_column(Integer, default=0)
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    # Per-source outcome, JSON: [{"id":..,"ok":bool,"count":int,"error":str}]
    detail_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
