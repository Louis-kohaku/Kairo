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


class AppSettings(BaseModel):
    ai: AISettings = AISettings()
    video: VideoSettings = VideoSettings()
    performance: PerformanceSettings = PerformanceSettings()
    tts: TTSSettings = TTSSettings()
    subtitle: SubtitleSettings = SubtitleSettings()
    generation: GenerationSettings = GenerationSettings()


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


class AppSettingsPatch(BaseModel):
    ai: Optional[AISettingsPatch] = None
    video: Optional[VideoSettingsPatch] = None
    performance: Optional[PerformanceSettingsPatch] = None
    tts: Optional[TTSSettingsPatch] = None
    subtitle: Optional[SubtitleSettingsPatch] = None
    generation: Optional[GenerationSettingsPatch] = None
