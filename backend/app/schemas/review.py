"""The AI Video Reviewer's verdict, and the production report.

`VideoReview` is deliberately about the *rendered file*, not the plan. The
existing quality check (services/studio/quality_service.py) reviews the
scene design and stays exactly as it was; this one opens the MP4 that came
out of FFmpeg, measures it, samples frames from it, and scores what is
actually there. That distinction is why both exist: a plan can be sound and
the render still be too dark, too quiet, or the wrong length.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

# The axes the design brief asks for, in the order they are displayed.
AXES: tuple[str, ...] = (
    "hook",
    "pacing",
    "visual",
    "subtitle",
    "audio",
    "story",
    "trend_alignment",
)

AXIS_LABELS: dict[str, str] = {
    "hook": "Hook",
    "pacing": "テンポ",
    "visual": "映像",
    "subtitle": "字幕",
    "audio": "音",
    "story": "構成",
    "trend_alignment": "トレンド適合",
}


class AxisScore(BaseModel):
    axis: str
    label: str = ""
    score: float = 0.0
    # "measured" - derived from the rendered file; "planned" - derived from
    # the scene design because the file cannot answer it; "ai" - the local
    # model's judgement. Shown in the UI so a number is never mistaken for
    # a measurement it isn't.
    basis: str = "measured"
    detail: str = ""


class ReviewFinding(BaseModel):
    axis: str
    severity: str = "minor"  # info | minor | major
    problem: str = ""
    cause: str = ""
    suggestion: str = ""
    # A machine-applicable fix, when one exists. Consumed by
    # services/studio/refinement.py; None means "reported, not fixable".
    fix: Optional[str] = None
    fix_value: Optional[float] = None
    scene_index: Optional[int] = None


class VideoReview(BaseModel):
    performed: bool = False
    iteration: int = 0
    overall_score: float = 0.0
    axes: list[AxisScore] = Field(default_factory=list)
    findings: list[ReviewFinding] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    summary: str = ""
    # What was actually inspected, so the review can be trusted or doubted
    # on the right grounds.
    measured: dict = Field(default_factory=dict)
    reviewed_by: str = "rules"  # rules | rules+ai
    output_path: str = ""
    error: str = ""

    def axis_score(self, axis: str) -> float:
        for item in self.axes:
            if item.axis == axis:
                return item.score
        return 0.0


class IterationRecord(BaseModel):
    iteration: int
    score: float
    changes: list[str] = Field(default_factory=list)
    output_path: str = ""
    adopted: bool = False
    note: str = ""


class VariantRecord(BaseModel):
    """One A/B/C variant of the same brief."""

    id: str
    label: str
    strategy_note: str = ""
    score: float = 0.0
    output_path: str = ""
    best: bool = False


class ProductionReport(BaseModel):
    """Everything about how one video was made, in one object."""

    project_id: str = ""
    project_name: str = ""
    run_id: str = ""
    title: str = ""
    genre: str = ""
    genre_label: str = ""
    instruction: str = ""
    duration_seconds: float = 0.0
    orientation: str = ""
    resolution: str = ""

    llm_provider: str = ""
    llm_endpoint: str = ""
    llm_model: str = ""
    transcription_engine: str = ""
    tts_engine: str = ""
    rendering_engine: str = ""

    trend_used: bool = False
    trend_reason: str = ""
    trend_sources: list[str] = Field(default_factory=list)
    trend_keywords: list[str] = Field(default_factory=list)
    genre_profile_source: str = ""

    font: str = ""
    font_license: str = ""
    music: str = ""
    music_license: str = ""
    sfx: list[str] = Field(default_factory=list)
    attribution: list[str] = Field(default_factory=list)

    review: Optional[VideoReview] = None
    iterations: list[IterationRecord] = Field(default_factory=list)
    variants: list[VariantRecord] = Field(default_factory=list)
    final_score: float = 0.0
    output_path: str = ""
    assets_used_path: str = ""
    generated_at: str = ""
