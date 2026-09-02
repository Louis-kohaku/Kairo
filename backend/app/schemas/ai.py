"""Response shapes for the AI model management endpoints (design doc
sections 3-20): available models, PC-based recommendation, and processing
time estimates.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ModelInfo(BaseModel):
    id: str
    loaded: bool
    recommended: bool
    catalog_tier_label: Optional[str] = None
    is_current: bool


class ModelsListOut(BaseModel):
    connected: bool
    base_url: str
    models: list[ModelInfo] = []
    current_model: Optional[str] = None
    current_model_source: Optional[str] = None
    diagnosis: dict | None = None


class SetupCandidate(BaseModel):
    id: str
    display_name: str
    purpose: str
    size_gb: float
    quant: str
    tier_label: str
    required_free_gb: float
    current_free_gb: float
    enough_disk_space: bool
    estimated_download_minutes_low: float
    estimated_download_minutes_high: float
    recommendation_stars: int  # 1-5
    already_available: bool


class RecommendationOut(BaseModel):
    ram_gb: float
    gpu_names: list[str]
    gpu_dedicated: bool
    recommended_tier_label: str
    reasons: list[str]
    recommended_model_id: Optional[str] = None
    recommended_model_source: str  # "existing" | "catalog" | "none"
    setup_candidates: list[SetupCandidate] = []


class EstimateRangeOut(BaseModel):
    low_seconds: float
    high_seconds: float


class EstimateOut(BaseModel):
    planning: EstimateRangeOut
    generation: EstimateRangeOut
    total: EstimateRangeOut
    based_on_history: bool
    note: str


class VideoSettingWarningOut(BaseModel):
    level: str  # "recommended" | "caution" | "not_recommended"
    reason: str
