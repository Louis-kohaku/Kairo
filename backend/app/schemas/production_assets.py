"""What the agent chose for one production, and under what terms.

Stored on the run and rendered into `assets-used.json` and the production
report. The point is traceability: for any finished video, "what did this
use and was I allowed to use it" must be answerable from the record alone,
without re-deriving anything.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class LicenseRef(BaseModel):
    id: str = "unknown"
    name: str = ""
    status: str = "unknown"
    status_label: str = ""
    url: str = ""
    attribution_required: bool = False
    attribution: str = ""
    commercial_use: bool = False


class AssetChoice(BaseModel):
    """One asset the production used, plus why it was chosen."""

    kind: str  # font | music | sfx
    found: bool = False
    asset_id: str = ""
    name: str = ""
    family: str = ""
    path: str = ""
    category: str = ""
    source: str = ""
    source_url: str = ""
    reason: str = ""
    reasons: list[str] = Field(default_factory=list)
    score: float = 0.0
    license: LicenseRef = LicenseRef()
    # Music only, and measured or declared - never assumed.
    bpm: Optional[float] = None
    duration: Optional[float] = None
    loudness_lufs: Optional[float] = None
    # How many candidates were looked at, and how many were dropped for
    # licence reasons. Shown in the UI so "1件しか候補がなかった" is visible
    # rather than looking like a confident pick.
    considered: int = 0
    rejected_for_license: int = 0
    unavailable_reason: str = ""


class SfxPlacement(BaseModel):
    """One effect, at one moment, for one stated reason."""

    at: float
    category: str
    asset_id: str = ""
    name: str = ""
    trigger: str = ""  # scene_change | hook | subtitle | ending
    scene_index: Optional[int] = None
    gain: float = 0.7
    reason: str = ""


class BeatSyncResult(BaseModel):
    applied: bool = False
    reason: str = ""
    bpm: Optional[float] = None
    bpm_source: str = ""  # declared | detected
    beat_seconds: Optional[float] = None
    # Beats per cut. 2 means "cut every other beat".
    beats_per_cut: int = 0
    adjusted_scenes: int = 0
    total_drift_seconds: float = 0.0
    cut_points: list[float] = Field(default_factory=list)


class SubtitleDecision(BaseModel):
    font: str = ""
    size: int = 0
    position: str = ""
    style: str = ""
    color: str = ""
    max_chars_per_line: int = 0
    reason: str = ""
    from_trend_profile: bool = False


class AssetDecisions(BaseModel):
    """Everything the Creative Director decided for one run."""

    genre: str = "unknown"
    genre_label: str = ""
    font: Optional[AssetChoice] = None
    music: Optional[AssetChoice] = None
    sfx: list[SfxPlacement] = Field(default_factory=list)
    sfx_assets: list[AssetChoice] = Field(default_factory=list)
    subtitle: Optional[SubtitleDecision] = None
    beat_sync: BeatSyncResult = BeatSyncResult()
    notes: list[str] = Field(default_factory=list)

    def attribution_lines(self) -> list[str]:
        """Credits the finished video is obliged to carry."""
        lines: list[str] = []
        for choice in [self.font, self.music, *self.sfx_assets]:
            if choice is None or not choice.found:
                continue
            if not choice.license.attribution_required:
                continue
            credit = choice.license.attribution or choice.name
            lines.append(f"{choice.name} - {credit} ({choice.license.name})")
        return lines
