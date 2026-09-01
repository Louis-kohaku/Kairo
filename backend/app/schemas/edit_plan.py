"""The AI edit instruction JSON contract (design doc section 14): the LLM
is only ever allowed to produce documents matching this schema. Validation
here is what keeps "AI decides, the existing safe services execute" true -
an unknown op, a wrong type, or an out-of-range value is rejected before
anything touches ffmpeg or the timeline.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from app.core.config import (
    DEFAULT_SILENCE_MIN_DURATION,
    DEFAULT_SILENCE_NOISE_DB,
)


class RemoveSilenceOp(BaseModel):
    op: Literal["remove_silence"]
    media_asset_id: str
    noise_db: float = Field(default=DEFAULT_SILENCE_NOISE_DB, ge=-70, le=-5)
    min_duration: float = Field(default=DEFAULT_SILENCE_MIN_DURATION, ge=0.1, le=5.0)


class GenerateSubtitlesOp(BaseModel):
    op: Literal["generate_subtitles"]


class SetBgmVolumeOp(BaseModel):
    op: Literal["set_bgm_volume"]
    volume: float = Field(ge=0.0, le=2.0)


EditOp = Annotated[
    Union[RemoveSilenceOp, GenerateSubtitlesOp, SetBgmVolumeOp],
    Field(discriminator="op"),
]


class EditPlan(BaseModel):
    operations: list[EditOp] = Field(default_factory=list)
