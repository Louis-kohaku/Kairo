from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    fps: float = 30.0
    width: int = 1920
    height: int = 1080


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    fps: float
    width: int
    height: int
    created_at: datetime
    updated_at: datetime


class MediaAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    kind: str
    original_filename: str
    duration: float
    width: Optional[int]
    height: Optional[int]
    fps: Optional[float]
    has_audio: bool
    video_codec: Optional[str]
    audio_codec: Optional[str]
    imported_at: datetime


class ClipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    track_id: str
    media_asset_id: str
    order_index: int
    in_point: float
    out_point: float
    volume: float


class ClipCreate(BaseModel):
    media_asset_id: str
    in_point: float = 0.0
    out_point: Optional[float] = None  # defaults to full asset duration
    volume: float = 1.0
    index: Optional[int] = None  # insert position; defaults to append


class ClipUpdate(BaseModel):
    in_point: Optional[float] = None
    out_point: Optional[float] = None
    volume: Optional[float] = None


class ClipSplit(BaseModel):
    time: float  # absolute timeline seconds at which to split


class TrackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    type: str
    name: str
    order_index: int
    clips: list[ClipOut] = []


class TimelineOut(BaseModel):
    tracks: list[TrackOut]
    total_duration: float


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    type: str
    status: str
    progress: float
    message: str
    error: Optional[str]
    output_path: Optional[str]
    created_at: datetime
    updated_at: datetime
