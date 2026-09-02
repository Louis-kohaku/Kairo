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


class AISettings(BaseModel):
    mode: AIMode = "auto"
    # Only meaningful when mode == "manual". None means "no explicit choice
    # yet" - resolve_model() then falls through to the auto recommendation.
    selected_model: Optional[str] = None


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


class AISettingsPatch(BaseModel):
    mode: Optional[AIMode] = None
    selected_model: Optional[str] = None
    # Explicit flag (rather than relying on `selected_model is None`) so a
    # client can deliberately clear a manual selection back to "no choice".
    clear_selected_model: bool = False


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
