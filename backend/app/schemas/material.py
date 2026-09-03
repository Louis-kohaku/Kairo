"""JSON contracts for user-supplied material.

Three shapes live here, one per stage of the material pipeline:

* `MaterialAnalysis` - what Kairo worked out about one uploaded file. It is
  cached on the asset row, so the fields have to be stable enough to read
  back a week later; anything the analysis could not determine is left
  empty rather than guessed, and `analyzed_by` says which method produced
  it so the UI never implies an AI looked at a photo when none did.
* `MaterialPlan` - the decision the planning stage made: which material
  goes where, what is missing, and how each gap will be filled. This is the
  thing the user confirms before a production starts.
* `MaterialUsage` - the same information after the fact, keyed by time on
  the finished video, which is what "この素材はどこから来たのか" answers.

The vocabulary is shared with the frontend verbatim, so a change here is a
change to both sides at once rather than two definitions drifting apart.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

# Where a piece of material came from. Ordered here in the same priority
# the asset stage applies it (design requirement 7): the user's own footage
# first, then their photos, then anything Kairo had to find or make.
#
# "local" is reserved for a shared local stock library, which Kairo does
# not have. It is kept in the vocabulary so the order is complete and a
# library can slot in later, but nothing ever produces it today - and
# `available_fill_sources` therefore never offers it, so the plan the user
# confirms cannot promise a source that does not exist.
MaterialOrigin = Literal["user", "local", "web", "ai_generated", "procedural"]

ORIGIN_LABELS: dict[str, str] = {
    "user": "ユーザー素材",
    "local": "ローカル素材",
    "web": "Web素材",
    "ai_generated": "AI生成",
    "procedural": "抽象背景",
}

# How the user wants their material used.
MaterialMode = Literal["ai_auto", "use_all", "selected"]

MATERIAL_MODE_LABELS: dict[str, str] = {
    "ai_auto": "AIにおまかせ",
    "use_all": "できるだけ全部使う",
    "selected": "選択した素材だけ使う",
}


class UsableRange(BaseModel):
    """The part of a video worth cutting from.

    Both ends default to the whole clip; the analysis narrows them only
    when it has a measured reason to (a black lead-in, a static tail).
    """

    start: float = 0.0
    end: float = 0.0
    reason: str = ""


class MaterialAnalysis(BaseModel):
    """What one uploaded file contains, as far as Kairo could determine."""

    asset_id: str = ""
    kind: str = "image"  # image | video | audio

    # Tags are the matching currency: a scene asks for "海", a photo
    # tagged 海 wins. Kept as plain Japanese words, deduplicated, in
    # descending confidence order.
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    scene_summary: str = ""

    width: Optional[int] = None
    height: Optional[int] = None
    orientation: str = ""  # vertical | horizontal | square
    duration: float = 0.0
    fps: Optional[float] = None
    has_audio: bool = False

    # 0.0-1.0. Measured from actual pixels (Pillow for stills, sampled
    # frames for video), not guessed from the file name.
    brightness: Optional[float] = None
    # 0.0-1.0, video only: mean frame-to-frame difference across samples.
    motion: Optional[float] = None
    dominant_colors: list[str] = Field(default_factory=list)

    usable: UsableRange = Field(default_factory=UsableRange)

    # "vision_ai" | "metadata" | "metadata+filename". The UI shows this
    # verbatim so an analysis produced without a vision model is never
    # presented as though a model had looked at the image.
    analyzed_by: str = "metadata"
    notes: str = ""


class MaterialAssignment(BaseModel):
    """One scene's material decision."""

    scene_index: int = 0
    scene_number: int = 1
    subtitle: str = ""
    visual_prompt: str = ""
    duration: float = 0.0
    start_time: float = 0.0

    origin: MaterialOrigin = "procedural"
    asset_id: Optional[str] = None
    filename: str = ""
    # For video material: the slice used.
    source_start: Optional[float] = None
    source_end: Optional[float] = None
    # Why this material was chosen, in the user's language.
    reason: str = ""
    matched_tags: list[str] = Field(default_factory=list)
    score: float = 0.0


class MaterialShortage(BaseModel):
    """A scene the user's material could not cover."""

    scene_index: int = 0
    scene_number: int = 1
    need: str = ""
    keywords: list[str] = Field(default_factory=list)
    # How this gap is planned to be filled, using the first source in the
    # priority order that is actually available in this environment.
    fill_method: MaterialOrigin = "procedural"
    fill_reason: str = ""


class MaterialPlan(BaseModel):
    """The full picture the user confirms before production starts."""

    mode: MaterialMode = "ai_auto"
    user_photo_count: int = 0
    user_video_count: int = 0
    used_photo_count: int = 0
    used_video_count: int = 0
    unused_asset_ids: list[str] = Field(default_factory=list)

    assignments: list[MaterialAssignment] = Field(default_factory=list)
    shortages: list[MaterialShortage] = Field(default_factory=list)

    # Counts per fill method, for the "補完方法" summary.
    fill_counts: dict[str, int] = Field(default_factory=dict)
    # Sources that are genuinely usable right now. A source missing from
    # this list is one Kairo will not silently pretend to have used.
    available_fill_sources: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    # Set when the plan is an estimate made before the script exists.
    provisional: bool = False
    estimated_scene_count: int = 0


class MaterialUsageEntry(BaseModel):
    """One row of the finished video's material credits."""

    scene_index: int = 0
    scene_number: int = 1
    start: float = 0.0
    end: float = 0.0
    origin: MaterialOrigin = "procedural"
    origin_label: str = ""
    asset_id: Optional[str] = None
    filename: str = ""
    subtitle: str = ""
    note: str = ""
    source_start: Optional[float] = None
    source_end: Optional[float] = None


class MaterialUsageReport(BaseModel):
    entries: list[MaterialUsageEntry] = Field(default_factory=list)
    total_duration: float = 0.0
    counts: dict[str, int] = Field(default_factory=dict)
