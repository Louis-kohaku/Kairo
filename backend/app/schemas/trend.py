"""Wire/­storage shapes for Trend Intelligence."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

TrendPlatform = Literal[
    "google_trends", "wikipedia", "youtube", "web_research", "manual"
]


class RawTrend(BaseModel):
    """What a provider returns, before normalisation and storage."""

    platform: TrendPlatform
    keyword: str
    region: str = "JP"
    # Provider-native number (search volume, view count, rank score...).
    raw_score: float = 0.0
    # 0-100 after the provider's own normalisation.
    score: float = 0.0
    source: str = ""
    source_url: str = ""
    category_hint: str = ""
    metadata: dict = Field(default_factory=dict)


class TrendSignalOut(BaseModel):
    id: str
    platform: str
    keyword: str
    category: str
    category_label: str = ""
    region: str
    score: float
    growth_rate: float
    observation_count: int
    observed_at: Optional[str] = None
    expires_at: Optional[str] = None
    source: str
    source_url: str
    metadata: dict = Field(default_factory=dict)
    # Score after time decay, i.e. what the planner actually ranks on.
    effective_score: float = 0.0
    stale: bool = False


class GenreProfileData(BaseModel):
    """How videos in one genre are typically built.

    Every field is optional-by-default because a profile derived from thin
    evidence must be allowed to say "we don't know" rather than fill in a
    plausible number. `evidence` names the keywords it was derived from.
    """

    genre: str = ""
    label: str = ""
    duration_seconds: Optional[float] = None
    scene_seconds: Optional[float] = None
    hook_seconds: Optional[float] = None
    hook_patterns: list[str] = Field(default_factory=list)
    opening_patterns: list[str] = Field(default_factory=list)
    cut_tempo: str = ""
    subtitle_density: str = ""
    subtitle_position: str = ""
    subtitle_style: str = ""
    font_style: list[str] = Field(default_factory=list)
    bgm_mood: str = ""
    bgm_bpm_range: list[float] = Field(default_factory=list)
    sfx_usage: list[str] = Field(default_factory=list)
    transitions: list[str] = Field(default_factory=list)
    title_patterns: list[str] = Field(default_factory=list)
    cta_patterns: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    notes: str = ""
    evidence: list[str] = Field(default_factory=list)


class GenreProfileOut(BaseModel):
    genre: str
    label: str
    region: str
    profile: GenreProfileData
    sample_size: int
    derived_from: str
    updated_at: Optional[str] = None


class TrendSourceStatus(BaseModel):
    id: str
    label: str
    kind: str  # "public_feed" | "official_api" | "derived"
    enabled: bool
    configured: bool
    requires_key: bool
    key_env: str = ""
    endpoint: str = ""
    terms_url: str = ""
    note: str = ""
    last_ok: Optional[str] = None
    last_error: str = ""
    last_count: int = 0


class TrendOverview(BaseModel):
    enabled: bool
    region: str
    interval_minutes: int
    last_run_at: Optional[str] = None
    last_run_status: str = ""
    next_run_at: Optional[str] = None
    total_signals: int = 0
    fresh_signals: int = 0
    sources: list[TrendSourceStatus] = Field(default_factory=list)
    top: list[TrendSignalOut] = Field(default_factory=list)
    by_category: dict[str, int] = Field(default_factory=dict)


class TrendContext(BaseModel):
    """The slice of trend intelligence one production run used.

    Stored on the run so the finished video can always say which trend data
    informed it - and so a report never has to re-query and get a different
    answer than the one the planner saw.
    """

    used: bool = False
    reason: str = ""
    genre: str = "unknown"
    genre_label: str = ""
    region: str = "JP"
    signals: list[TrendSignalOut] = Field(default_factory=list)
    profile: Optional[GenreProfileData] = None
    profile_source: str = ""
    collected_at: Optional[str] = None
