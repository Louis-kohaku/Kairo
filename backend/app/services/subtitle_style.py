"""Turns a user's SubtitleSettings into a libass `force_style` string so the
render pipeline's hardsub step actually reflects the font/size/position/
color/style chosen in Settings (design doc: settings must drive real
generation output, not sit inert next to it).
"""
from __future__ import annotations

from app.schemas.settings import SubtitleSettings

_ALIGNMENT_BY_POSITION = {
    "bottom": 2,  # numpad-style libass alignment: bottom-center
    "middle": 5,  # middle-center
    "top": 8,  # top-center
}


def _hex_to_ass_color(hex_color: str) -> str:
    """"#RRGGBB" -> libass "&H00BBGGRR&" (alpha, then BGR, reversed byte order)."""
    h = hex_color.strip().lstrip("#")
    if len(h) != 6:
        return "&H00FFFFFF&"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}&".upper()


def build_force_style(settings: SubtitleSettings) -> str:
    alignment = _ALIGNMENT_BY_POSITION.get(settings.position, 2)
    color = _hex_to_ass_color(settings.color)

    parts = [
        f"FontName={settings.font}",
        f"FontSize={settings.size}",
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
