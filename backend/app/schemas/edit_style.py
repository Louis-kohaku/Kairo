"""The edit directive: what kind of video this is, decided before editing.

Kairo already had a `ProductionStrategy` (schemas/studio.py), but that is a
*writing* brief - hook, pacing prose, subtitle policy as a sentence. What
the編集 stages actually need is a set of typed decisions they can act on
without re-interpreting prose: which transitions are allowed and how often,
how much the photos may move, which colour grade, how heavy the captions
are, what the font should feel like.

That is what an `EditDirective` is. It is produced once, at the start of a
run, by `services/studio/edit_director.py`, from three inputs:

* the **edit style** for the genre (services/studio/edit_styles.py) - the
  format conventions, as data rather than as a prompt;
* the **genre profile** Trend Intelligence derived (schemas/trend.py) -
  real measured tendencies where they exist;
* the **material** the user actually uploaded - a directive that asks for
  fast cuts over four photos is a directive nothing can execute.

An LLM pass then adjusts it, but only inside these types: a model can say
"this should be warmer and slower", it cannot invent a transition FFmpeg
has no filter for.

Every field carries a reason, because the UI shows this panel as "今回の
Kairo編集方針" and a decision the user cannot understand is a decision they
cannot correct.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

# The ten styles the brief asks for. These are *edit* styles, not the trend
# taxonomy's content genres - "cinematic" and "luxury" say how a video is
# cut, not what it is about - so they are a separate vocabulary mapped onto
# the genre ids in edit_styles.py rather than added to services/trends/genre.py.
EditStyleId = Literal[
    "vlog",
    "travel",
    "cinematic",
    "food",
    "tutorial",
    "entertainment",
    "shorts",
    "documentary",
    "luxury",
    "casual",
]

STYLE_LABELS: dict[str, str] = {
    "vlog": "Vlog",
    "travel": "Travel",
    "cinematic": "Cinematic",
    "food": "Food",
    "tutorial": "Tutorial / 解説",
    "entertainment": "Entertainment",
    "shorts": "SNS Shorts",
    "documentary": "Documentary",
    "luxury": "Luxury",
    "casual": "Casual",
}

# Delivery targets. Aspect, length and caption weight differ enough between
# these that "縦型" alone is not a specification.
PlatformId = Literal[
    "youtube_shorts", "tiktok", "instagram_reels", "youtube_landscape", "generic"
]

PLATFORM_LABELS: dict[str, str] = {
    "youtube_shorts": "YouTube Shorts",
    "tiktok": "TikTok",
    "instagram_reels": "Instagram Reels",
    "youtube_landscape": "YouTube 16:9",
    "generic": "指定なし",
}

# Transitions Kairo can actually render. Every one of these maps onto a
# concrete FFmpeg operation in services/ffmpeg/engine.py - there is
# deliberately no entry here that the renderer would have to fake.
TransitionId = Literal[
    "cut",
    "fade",
    "dissolve",
    "dip_to_black",
    "slide_left",
    "slide_right",
    "slide_up",
    "push_left",
    "zoom",
    "match_cut",
]

TRANSITION_LABELS: dict[str, str] = {
    "cut": "カット",
    "fade": "フェード",
    "dissolve": "クロスディゾルブ",
    "dip_to_black": "ディップ・トゥ・ブラック",
    "slide_left": "スライド(左)",
    "slide_right": "スライド(右)",
    "slide_up": "スライド(上)",
    "push_left": "プッシュ",
    "zoom": "ズーム",
    "match_cut": "マッチカット",
}

# Why a transition was placed. A boundary with no reason gets a cut, which
# is the whole point of requirement 5: a transition has to mean something.
TransitionReason = Literal[
    "none",
    "location_change",
    "time_jump",
    "emotion_change",
    "act_change",
    "music_section",
    "opening",
    "ending",
    "match_subject",
]

TRANSITION_REASON_LABELS: dict[str, str] = {
    "none": "通常のつなぎ",
    "location_change": "場所が変わる",
    "time_jump": "時間が飛ぶ",
    "emotion_change": "感情が切り替わる",
    "act_change": "話の展開が変わる",
    "music_section": "音楽の区切り",
    "opening": "冒頭",
    "ending": "締め",
    "match_subject": "被写体がつながる",
}

ColorGradeId = Literal[
    "none", "clean", "warm", "cinematic", "bright", "moody", "retro", "travel"
]

COLOR_GRADE_LABELS: dict[str, str] = {
    "none": "無補正",
    "clean": "Clean（素材そのまま＋わずかな整え）",
    "warm": "Warm（暖色寄り）",
    "cinematic": "Cinematic（低コントラスト・シネマ調）",
    "bright": "Bright（明るく軽やか）",
    "moody": "Moody（暗く落ち着いた）",
    "retro": "Retro（褪せた色）",
    "travel": "Travel（青空と海が映える）",
}


class ColorGrade(BaseModel):
    """A colour look, expressed as the FFmpeg terms that produce it.

    Deliberately conservative numbers. Requirement 13 is explicit that the
    grade must not destroy the material's own colour, so every preset here
    is a nudge - a few percent of contrast and saturation - not a LUT.
    `strength` scales all of it and is what the director lowers when the
    footage is already stylised.
    """

    id: ColorGradeId = "clean"
    label: str = ""
    # eq filter terms.
    brightness: float = 0.0  # -1.0..1.0, practically ±0.06
    contrast: float = 1.0  # 1.0 = unchanged
    saturation: float = 1.0
    gamma: float = 1.0
    # colorbalance shadow/midtone/highlight red-blue push, -1..1.
    shadow_blue: float = 0.0
    highlight_red: float = 0.0
    strength: float = 1.0
    reason: str = ""

    def is_identity(self) -> bool:
        return (
            self.id == "none"
            or self.strength <= 0.01
            or (
                abs(self.brightness) < 0.002
                and abs(self.contrast - 1.0) < 0.002
                and abs(self.saturation - 1.0) < 0.002
                and abs(self.gamma - 1.0) < 0.002
                and abs(self.shadow_blue) < 0.002
                and abs(self.highlight_red) < 0.002
            )
        )


class TransitionPolicy(BaseModel):
    """How often this video is allowed to stop cutting.

    `max_ratio` is the rule requirement 5 asks for as a number: a cut is
    the default, and only this share of boundaries may be anything else.
    Without a cap, "choose an appropriate transition per boundary" turns
    into a transition at every boundary, which is what the brief rules out.
    """

    default: TransitionId = "cut"
    allowed: list[TransitionId] = Field(default_factory=lambda: ["cut", "dissolve"])
    max_ratio: float = 0.25
    duration: float = 0.4
    # Transition used when the *reason* is a hard break (act change, time
    # jump). Kept separate because those want a stronger mark than a
    # location change does.
    strong: TransitionId = "dip_to_black"
    reason: str = ""


class SubtitlePolicy(BaseModel):
    """How the captions are designed, not just what they say."""

    # low = only where it adds something (Vlog); high = nearly every beat.
    density: Literal["minimal", "low", "medium", "high"] = "medium"
    # Share of scenes that should carry a caption at all.
    coverage: float = 0.7
    position: Literal["top", "middle", "bottom"] = "bottom"
    style: Literal["outline", "box", "plain"] = "outline"
    # Multiplier on the user's configured caption size. The size itself is
    # still the user's setting (creative_director has always refused to
    # overwrite it); this scales it for the format.
    size_scale: float = 1.0
    max_lines: int = 2
    # Kinetic typography: emphasised words get their own size/weight.
    emphasis: bool = True
    emphasis_scale: float = 1.18
    # Per-cue entrance. "none" is a real answer for documentary/cinematic.
    animation: Literal["none", "fade", "pop", "slide_up"] = "fade"
    letter_spacing: float = 0.0
    line_spacing: float = 1.0
    reason: str = ""


class FontDirection(BaseModel):
    """What the caption face should feel like, as ranking inputs.

    This is not a font name. The point of requirement 3 is that the face is
    *ranked* from the video's needs rather than fixed, so the directive
    states the needs and `library/selector.py` does the ranking.
    """

    wanted: list[str] = Field(default_factory=list)  # style tags to reward
    avoid: list[str] = Field(default_factory=list)  # style tags to penalise
    # Impression axes, 0.0-1.0, scored against the font's own metrics.
    luxury: float = 0.0
    casual: float = 0.0
    cinematic: float = 0.0
    impact: float = 0.5
    weight_min: int = 400
    weight_max: int = 900
    min_readability: int = 55
    # Japanese is a hard requirement whenever the captions contain kana.
    needs_japanese: bool = True
    needs_latin: bool = False
    reason: str = ""


class PhotoMotionPolicy(BaseModel):
    """How much a still is allowed to move (requirement 6)."""

    # Multiplier on the zoom span. 0 would be a freeze; 1.5 is a strong push.
    intensity: float = 1.0
    prefer: list[str] = Field(
        default_factory=lambda: ["zoom_in", "zoom_out", "pan_left", "pan_right"]
    )
    # Keep the detected subject inside the frame for the whole move.
    subject_safe: bool = True
    reason: str = ""


class AudioPolicy(BaseModel):
    # Whether the finished mix is brought to a platform-standard loudness,
    # and to what. Every short-form platform normalises playback to around
    # -14 LUFS; delivering there is what stops a quiet mix being turned up
    # along with its noise floor.
    normalize: bool = True
    target_lufs: float = -14.0
    bgm_mood: str = "gentle"
    bgm_bpm_range: list[float] = Field(default_factory=lambda: [90.0, 120.0])
    bgm_volume: float = 1.0
    duck_narration: bool = True
    # How aggressively environment sound from the user's own footage is
    # kept. 0 drops it, 1 keeps it at source level.
    keep_ambience: float = 0.6
    denoise: bool = True
    sfx_per_minute: float = 8.0
    narration_rate: int = 0  # SAPI rate, -10..10
    narration_style: str = ""
    reason: str = ""


class StoryBeat(BaseModel):
    """One act of the structure this video is built on (requirement 8)."""

    id: str = ""
    label: str = ""
    purpose: str = ""
    share: float = 0.2  # fraction of total runtime


class EditDirective(BaseModel):
    """Everything decided before a single frame is cut."""

    # --- identity -----------------------------------------------------
    style: EditStyleId = "shorts"
    style_label: str = ""
    genre: str = "unknown"
    genre_label: str = ""
    platform: PlatformId = "generic"
    platform_label: str = ""
    audience: str = ""
    concept: str = ""

    # --- format -------------------------------------------------------
    duration_seconds: float = 60.0
    orientation: Literal["vertical", "horizontal", "square"] = "vertical"
    width: int = 1080
    height: int = 1920

    # --- feel ---------------------------------------------------------
    mood: str = ""
    tempo: Literal["slow", "medium", "fast"] = "medium"
    scene_seconds: float = 3.0
    scene_seconds_min: float = 1.8
    scene_seconds_max: float = 5.0
    energy_curve: list[str] = Field(default_factory=list)

    # --- structure ----------------------------------------------------
    story: list[StoryBeat] = Field(default_factory=list)
    hook_seconds: float = 3.0
    hook_direction: str = ""
    ending_direction: str = ""
    cta: str = ""

    # --- craft --------------------------------------------------------
    subtitle: SubtitlePolicy = Field(default_factory=SubtitlePolicy)
    font: FontDirection = Field(default_factory=FontDirection)
    transitions: TransitionPolicy = Field(default_factory=TransitionPolicy)
    photo_motion: PhotoMotionPolicy = Field(default_factory=PhotoMotionPolicy)
    color: ColorGrade = Field(default_factory=ColorGrade)
    audio: AudioPolicy = Field(default_factory=AudioPolicy)

    # --- provenance ---------------------------------------------------
    # "defaults" | "defaults+profile" | "defaults+profile+ai". Shown in the
    # UI so a directive that the model never saw is not presented as an AI
    # decision.
    decided_by: str = "defaults"
    # One line per decision that differs from the plain style preset, in
    # the user's language. This is what the "今回のKairo編集方針" panel and
    # the production log read.
    notes: list[str] = Field(default_factory=list)
    material_summary: str = ""
    ai_note: str = ""


class TransitionChoice(BaseModel):
    """One boundary's decision (requirement 5), with its justification."""

    # Boundary between scene index-1 and index. index 0 is the video's
    # opening, which is not a boundary and is always a cut.
    index: int = 0
    transition: TransitionId = "cut"
    label: str = ""
    duration: float = 0.0
    reason: TransitionReason = "none"
    reason_label: str = ""
    detail: str = ""


class TransitionPlan(BaseModel):
    choices: list[TransitionChoice] = Field(default_factory=list)
    non_cut_count: int = 0
    boundary_count: int = 0
    summary: str = ""

    def by_index(self) -> dict[int, TransitionChoice]:
        return {c.index: c for c in self.choices}


class CueDesign(BaseModel):
    """The design of one caption, as opposed to its text (requirement 4)."""

    index: int = 0
    text: str = ""
    start: float = 0.0
    end: float = 0.0
    # Relative to the resolved base size. 1.0 = the user's setting.
    size_scale: float = 1.0
    bold: bool = True
    position: Literal["top", "middle", "bottom"] = "bottom"
    style: Literal["outline", "box", "plain"] = "outline"
    color: str = ""
    animation: Literal["none", "fade", "pop", "slide_up"] = "fade"
    letter_spacing: float = 0.0
    line_spacing: float = 1.0
    # Words rendered larger/heavier inside the line.
    emphasis: list[str] = Field(default_factory=list)
    reason: str = ""


class SubtitleDesignPlan(BaseModel):
    cues: list[CueDesign] = Field(default_factory=list)
    dropped: int = 0
    summary: str = ""


class FontCandidate(BaseModel):
    """One face considered, and how it scored. Requirement 3 asks for the
    reason to be inspectable from the production log, which means the
    runners-up have to be recorded too - a winner with no field behind it
    explains nothing."""

    asset_id: str = ""
    name: str = ""
    family: str = ""
    score: float = 0.0
    reasons: list[str] = Field(default_factory=list)
    penalties: list[str] = Field(default_factory=list)
    recently_used: bool = False
