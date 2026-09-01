"""JSON contracts for the AI production pipeline (design doc sections 4-8).

Two LLM calls are validated against these: one to produce the overall plan
(title/audience/tone/chapter outline), and one per chapter to produce that
chapter's scene-by-scene script + storyboard. Keeping generation scoped to
one chapter per call is what section 6 means by not generating a long
video in a single shot.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

VisualType = Literal[
    "ai_video",
    "ai_image",
    "photo",
    "diagram",
    "chart",
    "map",
    "text_animation",
    "existing_video",
    "existing_image",
    "screen_recording",
]

VISUAL_TYPE_LABELS: dict[str, str] = {
    "ai_video": "AI動画",
    "ai_image": "AI画像",
    "photo": "写真",
    "diagram": "図解",
    "chart": "チャート",
    "map": "地図",
    "text_animation": "テキストアニメーション",
    "existing_video": "既存動画",
    "existing_image": "既存画像",
    "screen_recording": "画面録画",
}


class ChapterOutline(BaseModel):
    title: str
    summary: str


class PlanOutline(BaseModel):
    title: str
    target_audience: str
    tone: str
    chapters: list[ChapterOutline] = Field(min_length=1, max_length=12)


class ScenePlan(BaseModel):
    narration: str
    visual_type: VisualType
    visual_prompt: str
    estimated_duration: float = Field(gt=0, le=90)


class ChapterScript(BaseModel):
    scenes: list[ScenePlan] = Field(min_length=1, max_length=20)
