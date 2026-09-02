"""JSON contracts for the AI production studio.

Every stage that asks the local LLM for structured output validates the
reply against a model here before anything acts on it - the same principle
`edit_plan.py` already established for AI editing: the model decides, but
only inside a shape Kairo defined. An unknown field, a wrong type or an
out-of-range duration is rejected up front instead of surfacing later as a
broken timeline or an ffmpeg failure.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field

from app.schemas.production import VisualType

# ---------------------------------------------------------------- research


class ResearchSource(BaseModel):
    """One page the research stage actually fetched. Kept with the report so
    the user can see what the analysis was built from rather than trusting
    an unattributed summary."""

    title: str = ""
    url: str = ""
    snippet: str = ""
    fetched: bool = False


class TrendReport(BaseModel):
    """Section 18: what everyone is doing vs. where the opening is.

    These are deliberately two separate lists. Merging them is how a
    "research-informed" video ends up being a copy of the top result -
    common_patterns is what the format expects, differentiation is what
    this specific video will do that the results did not.
    """

    query: str = ""
    common_patterns: list[str] = Field(default_factory=list)
    differentiation: list[str] = Field(default_factory=list)
    typical_duration_seconds: Optional[float] = None
    typical_scene_seconds: Optional[float] = None
    hook_patterns: list[str] = Field(default_factory=list)
    subtitle_patterns: list[str] = Field(default_factory=list)
    audio_patterns: list[str] = Field(default_factory=list)
    ending_patterns: list[str] = Field(default_factory=list)
    notes: str = ""


class ResearchResult(BaseModel):
    performed: bool = False
    # Why research was skipped, when it was - "オフラインのため" is a
    # legitimate outcome the pipeline continues from, not an error.
    skipped_reason: str = ""
    queries: list[str] = Field(default_factory=list)
    sources: list[ResearchSource] = Field(default_factory=list)
    trends: TrendReport = Field(default_factory=TrendReport)


# ---------------------------------------------------------------- strategy


class ProductionStrategy(BaseModel):
    """Section 19. Produced once, then handed to every later stage so the
    plan, script, assets, audio and quality check are all arguing from the
    same brief instead of each re-interpreting the user's one-line ask."""

    target: str = "short_form"
    title: str = ""
    concept: str = ""
    hook: str = ""
    pacing: str = ""
    scene_seconds_min: float = Field(default=2.0, gt=0.3, le=30)
    scene_seconds_max: float = Field(default=4.5, gt=0.3, le=60)
    subtitle_policy: str = ""
    audio_policy: str = ""
    bgm_mood: str = ""
    ending: str = ""
    differentiation: str = ""
    emotional_arc: list[str] = Field(default_factory=list)
    visual_style: str = ""


# ------------------------------------------------------------------ scenes


class ShortFormScene(BaseModel):
    """One designed beat. `subtitle` is separate from `narration` on
    purpose (section 25): the spoken line and the on-screen caption serve
    different jobs in short-form, and forcing them to be the same text is
    one of the things that made the old output feel flat."""

    narration: str = ""
    subtitle: str = ""
    purpose: str = ""
    emotion: str = ""
    visual_type: VisualType = "ai_image"
    visual_prompt: str = ""
    camera: str = ""
    sfx: str = ""
    transition: str = "cut"
    continuity: str = ""
    duration: float = Field(default=3.0, gt=0.4, le=30)


class SceneSet(BaseModel):
    scenes: list[ShortFormScene] = Field(min_length=1, max_length=40)


# ----------------------------------------------------------------- quality


QualityAxis = Literal[
    "structure",
    "pacing",
    "hook",
    "visual_quality",
    "continuity",
    "subtitle",
    "audio",
    "bgm",
    "sfx",
    "narration",
    "short_form_fit",
    "ending",
    "loop",
]

Severity = Literal["info", "minor", "major"]


class QualityIssue(BaseModel):
    axis: QualityAxis
    severity: Severity = "minor"
    scene_index: Optional[int] = None
    detail: str = ""
    suggestion: str = ""
    # Machine-readable fix the improvement stage knows how to apply. None
    # means "reported to the user but not auto-fixable", which is an
    # honest outcome rather than a silent no-op.
    fix: Optional[str] = None
    fix_value: Optional[float] = None


class QualityReport(BaseModel):
    score: float = Field(default=0.0, ge=0, le=100)
    axes: dict[str, float] = Field(default_factory=dict)
    issues: list[QualityIssue] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    summary: str = ""
    checked_by: str = ""  # "rules" | "rules+ai"


class AppliedImprovement(BaseModel):
    scene_index: Optional[int] = None
    what: str = ""
    before: str = ""
    after: str = ""
    reason: str = ""


class ImprovementReport(BaseModel):
    applied: list[AppliedImprovement] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    score_before: float = 0.0
    score_after: float = 0.0


# ----------------------------------------------------- AI Co-Creation ops
#
# The whole vocabulary the chat is allowed to speak. Anything outside this
# list cannot be produced by the model, which is what keeps "AIがプロジェク
# トを実際に変更する" (section 29) safe: each op maps onto an existing
# service call, never onto raw SQL, a shell command or a file path.
#
# `scene_number` is 1-based - the number the scene board and the subtitles
# actually display. A 0-based field here made "Scene 3をもっと面白くして"
# rewrite scene 4, which the user can see is the wrong scene. The internal
# 0-based index is derived at execution time instead.


class SetSceneDurationOp(BaseModel):
    op: Literal["set_scene_duration"]
    scene_number: int = Field(ge=1)
    duration: float = Field(gt=0.4, le=30)
    reason: str = ""


class ScaleAllDurationsOp(BaseModel):
    op: Literal["scale_all_durations"]
    factor: float = Field(gt=0.3, le=3.0)
    reason: str = ""


class SetSubtitleSizeOp(BaseModel):
    op: Literal["set_subtitle_size"]
    size: int = Field(ge=12, le=160)
    reason: str = ""


class SetSubtitleStyleOp(BaseModel):
    op: Literal["set_subtitle_style"]
    position: Optional[Literal["top", "middle", "bottom"]] = None
    style: Optional[Literal["outline", "box", "plain"]] = None
    color: Optional[str] = None
    reason: str = ""


class RewriteSceneOp(BaseModel):
    op: Literal["rewrite_scene"]
    scene_number: int = Field(ge=1)
    direction: str = ""
    reason: str = ""


class SetSceneSubtitleOp(BaseModel):
    op: Literal["set_scene_subtitle"]
    scene_number: int = Field(ge=1)
    text: str = ""
    reason: str = ""


class SetSceneNarrationOp(BaseModel):
    op: Literal["set_scene_narration"]
    scene_number: int = Field(ge=1)
    text: str = ""
    reason: str = ""


class StrengthenHookOp(BaseModel):
    op: Literal["strengthen_hook"]
    seconds: float = Field(default=2.5, gt=0.5, le=8)
    reason: str = ""


class SetBgmVolumeOp(BaseModel):
    op: Literal["set_bgm_volume"]
    volume: float = Field(ge=0.0, le=2.0)
    reason: str = ""


class RegenerateSceneAssetOp(BaseModel):
    op: Literal["regenerate_scene_asset"]
    scene_number: int = Field(ge=1)
    direction: str = ""
    reason: str = ""


class DeleteSceneOp(BaseModel):
    op: Literal["delete_scene"]
    scene_number: int = Field(ge=1)
    reason: str = ""


# Discriminated on "op" (same pattern as schemas/edit_plan.py) so an
# unknown operation name fails validation loudly instead of being coerced
# into whichever member happens to accept its fields.
StudioOp = Annotated[
    Union[
        SetSceneDurationOp,
        ScaleAllDurationsOp,
        SetSubtitleSizeOp,
        SetSubtitleStyleOp,
        RewriteSceneOp,
        SetSceneSubtitleOp,
        SetSceneNarrationOp,
        StrengthenHookOp,
        SetBgmVolumeOp,
        RegenerateSceneAssetOp,
        DeleteSceneOp,
    ],
    Field(discriminator="op"),
]


class StudioPlan(BaseModel):
    """What the co-creation model replies with: a plain-language summary of
    what it intends to do, the reason to show the user, and the operations
    to run if they accept."""

    summary: str = ""
    reason: str = ""
    operations: list[StudioOp] = Field(default_factory=list, max_length=24)
    # Set when the instruction was a question rather than an edit request,
    # so "この動画何秒？" gets an answer instead of a no-op proposal.
    answer: str = ""
