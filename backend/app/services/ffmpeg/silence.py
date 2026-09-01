"""Silence detection for AI auto-cut.

Runs ffmpeg's silencedetect audio filter and parses its stderr log - there
is no structured output mode for this filter, so text parsing is the
supported way to consume it.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from app.services.ffmpeg.util import require_binary

_START_RE = re.compile(r"silence_start:\s*(-?[\d.]+)")
_END_RE = re.compile(r"silence_end:\s*(-?[\d.]+)")


def detect_silence(
    path: Path, duration: float, noise_db: float, min_duration: float
) -> list[tuple[float, float]]:
    ffmpeg = require_binary("ffmpeg")
    args = [
        ffmpeg,
        "-hide_banner",
        "-i",
        str(path),
        "-af",
        f"silencedetect=noise={noise_db}dB:d={min_duration}",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(
        args,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=600,
    )
    starts = [float(m) for m in _START_RE.findall(proc.stderr)]
    ends = [float(m) for m in _END_RE.findall(proc.stderr)]

    # If the file ends in silence, ffmpeg logs silence_start but never
    # reaches a matching silence_end before EOF.
    if len(starts) > len(ends):
        ends.append(duration)

    return list(zip(starts, ends))


def compute_keep_segments(
    duration: float,
    silences: list[tuple[float, float]],
    padding: float,
    min_keep: float,
) -> list[tuple[float, float]]:
    """Invert silence intervals into the segments to keep, leaving a small
    padding of silence at each edge so cuts don't clip speech.
    """
    shrunk = []
    for start, end in sorted(silences):
        s = min(duration, start + padding)
        e = max(0.0, end - padding)
        if e > s:
            shrunk.append((s, e))

    keep: list[tuple[float, float]] = []
    cursor = 0.0
    for s, e in shrunk:
        if s > cursor:
            keep.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < duration:
        keep.append((cursor, duration))

    return [(s, e) for s, e in keep if e - s >= min_keep]
