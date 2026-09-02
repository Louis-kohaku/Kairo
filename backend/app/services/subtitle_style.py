"""Turns a user's SubtitleSettings into the subtitle styling the render
pipeline actually burns in (design doc: settings must drive real generation
output, not sit inert next to it).

Kairo now writes its own ASS file rather than handing ffmpeg an SRT plus a
`force_style` override. The reason is measurable: ffmpeg's SRT-to-ASS
conversion uses its own fixed reference resolution, and libass scales
FontSize by `video_height / PlayResY`. On a 1080x1920 short that made the
"42px" a user picked in Settings render at roughly 180px - five characters
filled 74% of the frame width, and at 60 the caption wrapped and ran off
the sides.

Writing the ASS ourselves lets us set `PlayResX`/`PlayResY` to the real
frame size, which makes **FontSize mean pixels**, exactly as the settings
UI claims. It also gives us the safe-area margins short-form needs
(section 25), which a `force_style` string cannot express.

`build_force_style` is kept for the SRT path (and any caller that still
wants an override string), but the render pipeline uses `build_ass`.
"""
from __future__ import annotations

from app.models.subtitle import SubtitleCue
from app.schemas.settings import SubtitleSettings

_ALIGNMENT_BY_POSITION = {
    "bottom": 2,  # numpad-style libass alignment: bottom-center
    "middle": 5,  # middle-center
    "top": 8,  # top-center
}

# Phone UI (captions, buttons, the progress bar) crowds the edges of a
# vertical video, so text is kept inside these fractions of the frame.
SAFE_MARGIN_X = 0.075
SAFE_MARGIN_BOTTOM = 0.12
SAFE_MARGIN_TOP = 0.10


def _hex_to_ass_color(hex_color: str) -> str:
    """"#RRGGBB" -> libass "&H00BBGGRR&" (alpha, then BGR, reversed byte order).

    Every character is checked to be a hex digit, not just the length. The
    result is interpolated into a style definition, and this value is
    reachable from an AI-generated one (AI Co-Creation's
    `set_subtitle_style` operation), so a 6-character string containing a
    comma or brace would otherwise let a model inject extra directives.
    Anything unrecognised falls back to white rather than being passed
    through.
    """
    h = hex_color.strip().lstrip("#")
    if len(h) != 6 or any(c not in "0123456789abcdefABCDEF" for c in h):
        return "&H00FFFFFF&"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}&".upper()


def _safe_font_name(font: str) -> str:
    """Font names sit in a comma-separated style line, where "," starts the
    next field and "'"/"\\" are meaningful to the filter argument that
    carries the file path. Real font names need none of them."""
    cleaned = "".join(c for c in font if c not in ",'\\:{}").strip()
    return cleaned or "Arial"


def resolve_size_px(settings: SubtitleSettings, height: int) -> int:
    """The caption's cap height in real pixels.

    Clamped to a sane share of the frame so neither a stray setting nor an
    AI-proposed value can produce an unreadable render.
    """
    size = max(8, min(int(settings.size), 200))
    return max(12, min(size, int(height * 0.14)))


def max_chars_per_line(settings: SubtitleSettings, width: int, height: int) -> int:
    """How many full-width Japanese characters fit on one line.

    Derived from the real font size rather than assumed, because the two
    are what actually decide whether a caption fits: a CJK glyph is about
    one em wide, so the usable width divided by the em size is the budget.
    """
    size = resolve_size_px(settings, height)
    usable = width * (1 - 2 * SAFE_MARGIN_X)
    return max(6, int(usable / (size * 1.02)))


def build_force_style(settings: SubtitleSettings) -> str:
    """libass override string, for the SRT burn-in path.

    Note that FontSize here is *not* pixels - it is scaled by libass
    against ffmpeg's conversion resolution. `build_ass` exists because of
    that; prefer it.
    """
    alignment = _ALIGNMENT_BY_POSITION.get(settings.position, 2)
    color = _hex_to_ass_color(settings.color)

    parts = [
        f"FontName={_safe_font_name(settings.font)}",
        f"FontSize={max(8, min(int(settings.size), 200))}",
        f"PrimaryColour={color}",
        f"Alignment={alignment}",
    ]

    if settings.style == "box":
        parts.append("BorderStyle=3")  # opaque box behind the text
        parts.append("Outline=1")
    elif settings.style == "plain":
        parts.append("BorderStyle=1")
        parts.append("Outline=0")
        parts.append("Shadow=0")
    else:  # "outline" (default)
        parts.append("BorderStyle=1")
        parts.append("Outline=2")
        parts.append("Shadow=1")

    return ",".join(parts)


def _ass_time(seconds: float) -> str:
    """ASS timestamps are H:MM:SS.cc (centiseconds, single-digit hours)."""
    seconds = max(0.0, seconds)
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis == 100:  # rounding carried into the next second
        centis = 0
        secs += 1
        if secs == 60:
            secs = 0
            minutes += 1
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


_BREAK_AFTER = "、。！？!?,.）」』】〉》"


def wrap_for_burn(text: str, max_chars: int, max_lines: int = 4) -> str:
    """Breaks a caption into lines that fit the frame.

    Kairo wraps rather than leaving it to libass, because libass only finds
    break opportunities at spaces unless it was built with libunibreak -
    and Japanese has no spaces. Measured on this machine's ffmpeg, a
    38-character sentence rendered as one line spanning the full 1080px
    frame and clipped at both edges, at every WrapStyle. That path is how
    Whisper transcripts reach the renderer in the manual editing flow, so
    it has to be handled here rather than assumed away.

    Existing line breaks are kept (they are the writer's own), and lines
    are broken after Japanese punctuation when one is near the limit so a
    line ends somewhere that reads naturally. Nothing is truncated: a long
    transcript becomes more lines, not less text.
    """
    if max_chars <= 0:
        return text
    out: list[str] = []
    for paragraph in text.split("\n"):
        remaining = paragraph.strip()
        if not remaining:
            continue
        while remaining and len(out) < max_lines:
            if len(remaining) <= max_chars:
                out.append(remaining)
                remaining = ""
                break
            window = remaining[: max_chars + 1]
            cut = max((window.rfind(ch) for ch in _BREAK_AFTER), default=-1) + 1
            if cut < max_chars * 0.55:
                cut = max_chars
            out.append(remaining[:cut].strip())
            remaining = remaining[cut:].strip()
        if remaining and out:
            # Out of lines: keep the text rather than dropping it, letting
            # the last line be the long one, which is still better than
            # silently losing part of a transcript.
            out[-1] = f"{out[-1]}{remaining}"
    return "\n".join(out)


def _ass_text(text: str) -> str:
    """Caption text as an ASS event field.

    "{" and "}" delimit override blocks in ASS, so a caption containing
    them would silently become styling instructions - and captions are
    written by the model, not by us. They are dropped rather than escaped,
    since a short-form caption has no legitimate use for them.
    """
    cleaned = text.replace("{", "(").replace("}", ")")
    # Real newlines are not allowed inside an event; \N is ASS's line break.
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    return cleaned.replace("\n", r"\N").strip()


def build_ass(
    cues: list[SubtitleCue], settings: SubtitleSettings, width: int, height: int
) -> str:
    """A complete ASS subtitle script sized to this exact frame.

    `PlayResX`/`PlayResY` are the real video dimensions, so every measure
    below (font size, outline width, margins) is in output pixels.
    """
    size = resolve_size_px(settings, height)
    alignment = _ALIGNMENT_BY_POSITION.get(settings.position, 2)
    colour = _hex_to_ass_color(settings.color)
    font = _safe_font_name(settings.font)

    if settings.style == "box":
        border_style, outline, shadow = 3, max(2, round(size * 0.18)), 0
    elif settings.style == "plain":
        border_style, outline, shadow = 1, 0, 0
    else:  # outline - the readable default over arbitrary footage
        border_style, outline, shadow = 1, max(2, round(size * 0.10)), max(1, round(size * 0.05))

    margin_x = int(width * SAFE_MARGIN_X)
    margin_v = int(
        height * (SAFE_MARGIN_TOP if settings.position == "top" else SAFE_MARGIN_BOTTOM)
    )

    header = "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            # Keeps outline/shadow scaled with the declared resolution.
            "ScaledBorderAndShadow: yes",
            # 2 = use only the line breaks in the text. Kairo does its own
            # wrapping (see wrap_for_burn) because libass finds no break
            # opportunities in Japanese unless built with libunibreak, so
            # leaving it to the renderer clipped long lines at the frame
            # edge instead of wrapping them.
            "WrapStyle: 2",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Kairo,{font},{size},{colour},&H000000FF,&H00000000,&H96000000,"
            f"-1,0,0,0,100,100,0,0,{border_style},{outline},{shadow},"
            f"{alignment},{margin_x},{margin_x},{margin_v},1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
    )

    budget = max_chars_per_line(settings, width, height)
    lines = [header]
    for cue in cues:
        text = _ass_text(wrap_for_burn(cue.text, budget))
        if not text:
            continue
        lines.append(
            f"Dialogue: 0,{_ass_time(cue.start)},{_ass_time(cue.end)},Kairo,,0,0,0,,{text}"
        )
    return "\n".join(lines) + "\n"
