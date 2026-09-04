"""The Creative Asset Library: fonts, music and sound effects Kairo may use.

One table for all three kinds, because everything that matters about them is
the same: where the file is, where it came from, what its licence permits,
and what it sounds/looks like. A per-kind table would have duplicated the
licence columns three times, and the licence columns are the point - design
rule 13 says an automatic production must never reach for an asset whose
terms Kairo cannot state.

`license_status` is the gate. Only `usable` and `attribution_required`
assets are eligible for automatic selection (and the second kind puts its
attribution into the production's assets-used record). `unknown` is a real,
common state - a file the user dropped in without telling Kairo its terms -
and it is deliberately *not* treated as permissive.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LibraryAsset(Base):
    __tablename__ = "library_assets"
    __table_args__ = (
        UniqueConstraint("kind", "path", name="uq_library_kind_path"),
        Index("ix_library_kind_status", "kind", "license_status"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # font | music | sfx

    name: Mapped[str] = mapped_column(String, nullable=False)
    # Font family, or track/effect title. Kept separate from `name` because a
    # font file's own name ("NotoSansJP-Bold") is not the family a renderer
    # needs ("Noto Sans JP").
    family: Mapped[str] = mapped_column(String, default="")

    # Absolute path for system-installed fonts (Kairo does not copy them);
    # LIBRARY_ROOT-relative for everything Kairo downloaded or the user
    # imported. `is_system` says which.
    path: Mapped[str] = mapped_column(Text, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    # Set false when a scan finds the file gone. The row is kept so a
    # production's assets-used record still resolves to something.
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0)

    # --- provenance and licence -----------------------------------------
    source: Mapped[str] = mapped_column(String, default="")
    source_url: Mapped[str] = mapped_column(Text, default="")
    license_id: Mapped[str] = mapped_column(String, default="unknown")
    license_name: Mapped[str] = mapped_column(String, default="")
    license_url: Mapped[str] = mapped_column(Text, default="")
    # usable | attribution_required | conditional | non_commercial |
    # not_usable | unknown  (see services/library/licenses.py)
    license_status: Mapped[str] = mapped_column(String, default="unknown")
    attribution_required: Mapped[bool] = mapped_column(Boolean, default=False)
    attribution_text: Mapped[str] = mapped_column(Text, default="")
    commercial_use: Mapped[bool] = mapped_column(Boolean, default=False)
    # Path to the licence file that shipped with the asset, when one did.
    license_file: Mapped[str] = mapped_column(Text, default="")

    # --- what it is ------------------------------------------------------
    # JSON arrays, stored as text: languages, styles, genres, tags, moods.
    languages_json: Mapped[str] = mapped_column(Text, default="[]")
    styles_json: Mapped[str] = mapped_column(Text, default="[]")
    genres_json: Mapped[str] = mapped_column(Text, default="[]")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")

    # Fonts: 100-900 OS/2 weight class, and Kairo's readability heuristic.
    weight: Mapped[int] = mapped_column(Integer, default=400)
    readability: Mapped[int] = mapped_column(Integer, default=0)
    supports_japanese: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_latin: Mapped[bool] = mapped_column(Boolean, default=True)

    # --- Fonts: impression axes (0-100) ---------------------------------
    # Derived by services/library/font_profile.py from the font's own
    # metrics and PANOSE classification - never from its name alone, and
    # never asserted as fact: each is a repeatable heuristic that lets the
    # edit director ask for "上品な細い書体" or "力強い太いゴシック" and get a
    # ranking it can justify. They are the reason a Vlog and a game short
    # no longer land on the same face.
    luxury: Mapped[int] = mapped_column(Integer, default=0)
    casual: Mapped[int] = mapped_column(Integer, default=0)
    cinematic: Mapped[int] = mapped_column(Integer, default=0)
    impact: Mapped[int] = mapped_column(Integer, default=0)
    friendliness: Mapped[int] = mapped_column(Integer, default=0)
    authority: Mapped[int] = mapped_column(Integer, default=0)
    # Per-use-case fitness (0-100), keyed by edit style id. JSON object.
    use_cases_json: Mapped[str] = mapped_column(Text, default="{}")
    # sans | serif | rounded | display | handwritten | mono | unknown
    classification: Mapped[str] = mapped_column(String, default="unknown")

    # Audio: measured, not declared. NULL means "not analysed yet", which is
    # different from 0 and is never rendered as a number in the UI.
    duration: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bpm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    loudness_lufs: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mood: Mapped[str] = mapped_column(String, default="")
    category: Mapped[str] = mapped_column(String, default="")

    # Full analysis payload (beat grid, name-table dump, ...) as JSON.
    analysis_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    analysis_status: Mapped[str] = mapped_column(String, default="pending")
    # pending | ok | failed | skipped
    analysis_error: Mapped[str] = mapped_column(Text, default="")

    notes: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)
