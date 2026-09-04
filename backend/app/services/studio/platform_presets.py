"""Per-platform delivery rules (requirement 14).

The four targets the brief names differ in ways that actually change the
edit, not just the container: how long the video may be, how hard the first
seconds have to work, how large the captions need to be against the
platform's own UI, and whether a call to action belongs at the end at all.

Applied to the `EditDirective` *before* the material and AI layers, so a
platform rule is a starting constraint the rest of the director can still
reason about, rather than a post-hoc override that silently contradicts
what the user was shown.

Nothing here talks to any platform. These are format conventions Kairo
applies locally; no API is called and no account is needed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.edit_style import PLATFORM_LABELS, EditDirective


@dataclass(frozen=True)
class PlatformPreset:
    id: str
    label: str
    orientation: str
    width: int
    height: int
    max_seconds: float
    ideal_seconds: float
    # How much the caption grows or shrinks against the user's setting.
    subtitle_scale: float
    # Where the platform's own UI sits, which is what pushes captions up.
    subtitle_position: str
    hook_seconds: float
    # Whether a closing call to action is conventional here.
    cta: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)


PRESETS: tuple[PlatformPreset, ...] = (
    PlatformPreset(
        id="youtube_shorts",
        label="YouTube Shorts",
        orientation="vertical",
        width=1080,
        height=1920,
        max_seconds=180.0,
        ideal_seconds=45.0,
        subtitle_scale=1.0,
        # Shorts puts the title, channel and buttons along the bottom, so a
        # bottom caption competes with them on a real phone.
        subtitle_position="middle",
        hook_seconds=2.0,
        cta="チャンネル登録の一言を最後に置く",
        notes=("下部にUIが重なるため字幕はやや上に置きます",),
    ),
    PlatformPreset(
        id="tiktok",
        label="TikTok",
        orientation="vertical",
        width=1080,
        height=1920,
        max_seconds=180.0,
        ideal_seconds=30.0,
        subtitle_scale=1.05,
        subtitle_position="middle",
        hook_seconds=1.5,
        cta="続きを見たくなる一言で終える",
        notes=("最初の1〜2秒での離脱が最も大きいため、冒頭を特に強くします",),
    ),
    PlatformPreset(
        id="instagram_reels",
        label="Instagram Reels",
        orientation="vertical",
        width=1080,
        height=1920,
        max_seconds=90.0,
        ideal_seconds=30.0,
        subtitle_scale=0.98,
        subtitle_position="middle",
        hook_seconds=2.0,
        cta="保存したくなる一言で終える",
        notes=("見た目の統一感が効くため、色味を揃えます",),
    ),
    PlatformPreset(
        id="youtube_landscape",
        label="YouTube 16:9",
        orientation="horizontal",
        width=1920,
        height=1080,
        max_seconds=1800.0,
        ideal_seconds=180.0,
        # A 16:9 video is watched further from the eye and has more
        # horizontal room, so the same em size reads as larger.
        subtitle_scale=0.72,
        subtitle_position="bottom",
        hook_seconds=5.0,
        cta="",
        notes=("横型は字幕を小さめにし、下部に置きます",),
    ),
    PlatformPreset(
        id="generic",
        label="指定なし",
        orientation="vertical",
        width=1080,
        height=1920,
        max_seconds=1800.0,
        ideal_seconds=60.0,
        subtitle_scale=1.0,
        subtitle_position="bottom",
        hook_seconds=3.0,
    ),
)

PRESET_BY_ID: dict[str, PlatformPreset] = {p.id: p for p in PRESETS}

# Words in a brief that name a platform. Longest match wins.
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "youtube_shorts": ("youtube shorts", "ショート", "shorts", "ようつべショート"),
    "tiktok": ("tiktok", "ティックトック", "tik tok"),
    "instagram_reels": ("reels", "リール", "インスタ", "instagram"),
    "youtube_landscape": ("youtube 16:9", "横型youtube", "youtube", "ようつべ"),
}


def detect(instruction: str, orientation: str = "vertical") -> str:
    """The platform a brief named, or the orientation's sensible default.

    "generic" is only returned when the orientation itself is unusual - a
    vertical video with no platform named is overwhelmingly a short, and
    saying so is more useful than declining to guess.
    """
    text = (instruction or "").casefold()
    best: tuple[int, str] | None = None
    for pid, words in _KEYWORDS.items():
        for word in words:
            if word in text and (best is None or len(word) > best[0]):
                best = (len(word), pid)
    if best:
        # "YouTubeでショート" must not resolve to the landscape preset.
        if best[1] == "youtube_landscape" and ("short" in text or "ショート" in text):
            return "youtube_shorts"
        return best[1]
    if orientation == "vertical":
        return "youtube_shorts"
    if orientation == "horizontal":
        return "youtube_landscape"
    return "generic"


def apply(directive: EditDirective, platform: str) -> None:
    """Writes a platform's rules onto a directive, in place."""
    preset = PRESET_BY_ID.get(platform) or PRESET_BY_ID["generic"]
    directive.platform = preset.id  # type: ignore[assignment]
    directive.platform_label = PLATFORM_LABELS.get(preset.id, preset.label)

    if directive.duration_seconds > preset.max_seconds:
        directive.notes.append(
            f"{preset.label}の上限に合わせて尺を"
            f"{directive.duration_seconds:.0f}秒→{preset.max_seconds:.0f}秒にします"
        )
        directive.duration_seconds = preset.max_seconds

    # Caption size and position: the platform's own UI decides these more
    # than taste does, so they override the style preset.
    if abs(preset.subtitle_scale - 1.0) > 0.01:
        directive.subtitle.size_scale = round(
            directive.subtitle.size_scale * preset.subtitle_scale, 3
        )
    if preset.subtitle_position != directive.subtitle.position:
        # Only pushed up, never down: a style that deliberately puts
        # captions at the top (rare, but a real choice) is left alone.
        if not (preset.subtitle_position == "middle" and directive.subtitle.position == "top"):
            directive.subtitle.position = preset.subtitle_position  # type: ignore[assignment]

    directive.hook_seconds = min(directive.hook_seconds, preset.hook_seconds)
    if preset.cta and not directive.cta:
        directive.cta = preset.cta
    for note in preset.notes:
        directive.notes.append(f"{preset.label}: {note}")


def frame_for(platform: str, fallback: tuple[int, int]) -> tuple[int, int]:
    preset = PRESET_BY_ID.get(platform)
    if preset is None:
        return fallback
    return preset.width, preset.height


def preset_list() -> list[dict]:
    """The platforms, for the UI's 配信先 picker."""
    return [
        {
            "id": p.id,
            "label": p.label,
            "orientation": p.orientation,
            "width": p.width,
            "height": p.height,
            "ideal_seconds": p.ideal_seconds,
            "max_seconds": p.max_seconds,
            "notes": list(p.notes),
        }
        for p in PRESETS
    ]
