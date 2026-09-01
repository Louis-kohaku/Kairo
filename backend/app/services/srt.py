from __future__ import annotations

from app.models.subtitle import SubtitleCue


def _format_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis == 1000:
        millis = 0
        secs += 1
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def build_srt(cues: list[SubtitleCue]) -> str:
    lines = []
    for i, cue in enumerate(sorted(cues, key=lambda c: c.order_index), start=1):
        lines.append(str(i))
        lines.append(f"{_format_timestamp(cue.start)} --> {_format_timestamp(cue.end)}")
        lines.append(cue.text)
        lines.append("")
    return "\n".join(lines)
