"""ffprobe wrapper.

Runs ffprobe as an argument list (never through a shell) and parses its
JSON output into a small typed struct. This is the only place in the
codebase that knows ffprobe's output format.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.services.ffmpeg.util import require_binary


class ProbeError(RuntimeError):
    pass


@dataclass
class MediaInfo:
    duration: float
    width: Optional[int]
    height: Optional[int]
    fps: Optional[float]
    has_video: bool
    has_audio: bool
    video_codec: Optional[str]
    audio_codec: Optional[str]

    @property
    def kind(self) -> str:
        return "video" if self.has_video else "audio"


def _parse_fps(rate: str | None) -> Optional[float]:
    if not rate or rate == "0/0":
        return None
    try:
        if "/" in rate:
            num, den = rate.split("/", 1)
            den_f = float(den)
            return float(num) / den_f if den_f else None
        return float(rate)
    except (ValueError, ZeroDivisionError):
        return None


def probe_media(path: Path) -> MediaInfo:
    ffprobe = require_binary("ffprobe")
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(f"ffprobe timed out inspecting {path.name}") from exc

    if result.returncode != 0:
        raise ProbeError(f"ffprobe failed on {path.name}: {result.stderr.strip()}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError(f"ffprobe returned invalid JSON for {path.name}") from exc

    fmt = data.get("format", {})
    streams = data.get("streams", [])

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration_raw = fmt.get("duration")
    if duration_raw is None and video_stream:
        duration_raw = video_stream.get("duration")
    if duration_raw is None and audio_stream:
        duration_raw = audio_stream.get("duration")

    try:
        duration = float(duration_raw) if duration_raw is not None else 0.0
    except ValueError:
        duration = 0.0

    return MediaInfo(
        duration=duration,
        width=video_stream.get("width") if video_stream else None,
        height=video_stream.get("height") if video_stream else None,
        fps=_parse_fps(video_stream.get("r_frame_rate")) if video_stream else None,
        has_video=video_stream is not None,
        has_audio=audio_stream is not None,
        video_codec=video_stream.get("codec_name") if video_stream else None,
        audio_codec=audio_stream.get("codec_name") if audio_stream else None,
    )
