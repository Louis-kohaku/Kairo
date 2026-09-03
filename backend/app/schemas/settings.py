"""Kairo's user-configurable settings (design doc sections 12/30-32/38-40).

Persisted locally only (see settings_service.py) - never sent anywhere
external. Every field has a Kairo-recommended default so a fresh install
starts in "Auto" mode end to end without the user having to configure
anything, while still being fully editable from the Settings UI.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

AIMode = Literal["auto", "manual"]
QualityPreset = Literal["fast", "standard", "high", "ultra", "custom"]
PerformanceProfile = Literal["auto", "speed", "balanced", "quality", "custom"]
TTSMode = Literal["auto", "off", "manual"]
SubtitlePosition = Literal["top", "middle", "bottom"]
SubtitleStyle = Literal["outline", "box", "plain"]


class AISettings(BaseModel):
    mode: AIMode = "auto"
    # Only meaningful when mode == "manual". None means "no explicit choice
    # yet" - resolve_model() then falls through to the auto recommendation.
    selected_model: Optional[str] = None


class TTSSettings(BaseModel):
    mode: TTSMode = "off"
    # Only meaningful when mode == "manual". None means "no explicit choice
    # yet" - the auto path picks the first installed voice matching the
    # project's language when one is needed.
    selected_voice: Optional[str] = None


class SubtitleSettings(BaseModel):
    enabled: bool = True
    font: str = "Yu Gothic UI"
    # Real output pixels (the em size of the caption), because the render
    # pipeline burns subtitles from an ASS whose PlayRes matches the frame -
    # see services/subtitle_style.py. 88 is what a 1080x1920 short wants:
    # legible at thumbnail size, ~10 Japanese characters per line, so a
    # 16-character caption becomes the two punchy lines the format expects.
    size: int = 88
    position: SubtitlePosition = "bottom"
    color: str = "#FFFFFF"
    style: SubtitleStyle = "outline"


class GenerationSettings(BaseModel):
    # 0 means "auto" (Kairo picks a limit from detected CPU core count).
    parallelism: int = 0
    cache_enabled: bool = True
    # Only meaningful as a pre-selection hint for the Generate panel - None
    # falls back to whatever the panel's own default engine is.
    default_engine_id: Optional[str] = None


class VideoSettings(BaseModel):
    aspect_ratio: str = "9:16"
    width: int = 1080
    height: int = 1920
    fps: float = 30.0
    quality_preset: QualityPreset = "standard"
    duration_seconds: float = 60.0


class PerformanceCustomOverrides(BaseModel):
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    num_inference_steps: Optional[int] = None


class PerformanceSettings(BaseModel):
    profile: PerformanceProfile = "auto"
    custom: Optional[PerformanceCustomOverrides] = None


class TrendSettings(BaseModel):
    """Trend Intelligence: what the background collector does.

    Off-by-default would make the feature invisible, but on-by-default with
    a short interval would hammer someone else's servers, so the interval is
    deliberately long: trending-search feeds update on the order of hours,
    and a three-hour cadence keeps "現在のトレンド" true without being a
    burden on the sources.
    """

    enabled: bool = True
    region: str = "JP"
    interval_minutes: int = 180
    # Source ids from services/trends/sources.py. A source needing a key the
    # user has not set stays listed here and reports itself as 未設定 rather
    # than silently disappearing.
    sources: list[str] = ["google_trends", "wikipedia", "youtube"]
    # Whether production runs read the accumulated trend data. Separate from
    # `enabled` so a user can keep collecting while producing a video that
    # deliberately ignores what is trending.
    use_in_production: bool = True
    max_signals_per_source: int = 30


class LibrarySettings(BaseModel):
    """Creative asset library behaviour."""

    # Downloading fonts is a network action that writes files, so it is
    # opt-in. Scanning what is already installed is not, and always runs.
    auto_download_fonts: bool = False
    # Assets whose licence Kairo could not establish are never used in an
    # automatic production. Flipping this off is not offered as a setting:
    # it is the rule (design rule 13), not a preference.
    prefer_commercial_safe: bool = True


class RefinementSettings(BaseModel):
    """The review -> improve -> re-review loop."""

    enabled: bool = True
    # Total quality passes over one production, including the first. 1 means
    # "check and improve once" (the behaviour before this existed).
    max_iterations: int = 2
    # Stop early once the reviewer scores at least this. Prevents spending
    # three re-renders improving a video that was already good.
    target_score: float = 85.0
    # Minimum score gain required to keep iterating; below it, further
    # passes are churn and the best version so far is adopted.
    min_gain: float = 2.0


class AppSettings(BaseModel):
    ai: AISettings = AISettings()
    video: VideoSettings = VideoSettings()
    performance: PerformanceSettings = PerformanceSettings()
    tts: TTSSettings = TTSSettings()
    subtitle: SubtitleSettings = SubtitleSettings()
    generation: GenerationSettings = GenerationSettings()
    trends: TrendSettings = TrendSettings()
    library: LibrarySettings = LibrarySettings()
    refinement: RefinementSettings = RefinementSettings()


class AISettingsPatch(BaseModel):
    mode: Optional[AIMode] = None
    selected_model: Optional[str] = None
    # Explicit flag (rather than relying on `selected_model is None`) so a
    # client can deliberately clear a manual selection back to "no choice".
    clear_selected_model: bool = False


class TTSSettingsPatch(BaseModel):
    mode: Optional[TTSMode] = None
    selected_voice: Optional[str] = None
    clear_selected_voice: bool = False


class SubtitleSettingsPatch(BaseModel):
    enabled: Optional[bool] = None
    font: Optional[str] = None
    size: Optional[int] = None
    position: Optional[SubtitlePosition] = None
    color: Optional[str] = None
    style: Optional[SubtitleStyle] = None


class GenerationSettingsPatch(BaseModel):
    parallelism: Optional[int] = None
    cache_enabled: Optional[bool] = None
    default_engine_id: Optional[str] = None
    clear_default_engine_id: bool = False


class VideoSettingsPatch(BaseModel):
    aspect_ratio: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    quality_preset: Optional[QualityPreset] = None
    duration_seconds: Optional[float] = None


class PerformanceSettingsPatch(BaseModel):
    profile: Optional[PerformanceProfile] = None
    custom: Optional[PerformanceCustomOverrides] = None


class TrendSettingsPatch(BaseModel):
    enabled: Optional[bool] = None
    region: Optional[str] = None
    interval_minutes: Optional[int] = None
    sources: Optional[list[str]] = None
    use_in_production: Optional[bool] = None
    max_signals_per_source: Optional[int] = None


class LibrarySettingsPatch(BaseModel):
    auto_download_fonts: Optional[bool] = None
    prefer_commercial_safe: Optional[bool] = None


class RefinementSettingsPatch(BaseModel):
    enabled: Optional[bool] = None
    max_iterations: Optional[int] = None
    target_score: Optional[float] = None
    min_gain: Optional[float] = None


class AppSettingsPatch(BaseModel):
    ai: Optional[AISettingsPatch] = None
    video: Optional[VideoSettingsPatch] = None
    performance: Optional[PerformanceSettingsPatch] = None
    tts: Optional[TTSSettingsPatch] = None
    subtitle: Optional[SubtitleSettingsPatch] = None
    generation: Optional[GenerationSettingsPatch] = None
    trends: Optional[TrendSettingsPatch] = None
    library: Optional[LibrarySettingsPatch] = None
    refinement: Optional[RefinementSettingsPatch] = None
