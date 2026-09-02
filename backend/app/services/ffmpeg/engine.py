"""Safe FFmpeg execution engine.

This is the ONLY module that shells out to ffmpeg. Every function here takes
already-validated, typed parameters (paths, floats, ints) - never a raw
string built from user input - and always invokes ffmpeg via an argument
list (subprocess with shell=False), so there is no command-injection
surface. Higher layers (API routes, the render service) describe *what*
they want as data; this module decides *how* to ask ffmpeg for it.
"""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

from app.services.ffmpeg.util import require_binary

ProgressCallback = Callable[[float], None]  # fraction complete, 0.0-1.0


class FFmpegRunError(RuntimeError):
    def __init__(self, message: str, stderr_tail: str = ""):
        super().__init__(message)
        self.stderr_tail = stderr_tail


def _run(
    args: list[str],
    total_duration: Optional[float] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> None:
    ffmpeg = require_binary("ffmpeg")
    argv = [ffmpeg, "-hide_banner", "-y", *args]

    if on_progress and total_duration and total_duration > 0:
        argv = argv[:1] + ["-progress", "pipe:1", "-nostats"] + argv[1:]

    proc = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if on_progress else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    # stdout (progress) and stderr must be drained concurrently: if either
    # pipe's OS buffer fills while we're blocked reading the other, ffmpeg
    # stalls forever on the next write() - a classic subprocess deadlock.
    stderr_lines: list[str] = []

    def _drain_stderr() -> None:
        if proc.stderr:
            for line in proc.stderr:
                stderr_lines.append(line)

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    if on_progress and total_duration and total_duration > 0 and proc.stdout:
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_ms="):
                try:
                    micros = int(line.split("=", 1)[1])
                    seconds = micros / 1_000_000
                    fraction = min(1.0, max(0.0, seconds / total_duration))
                    on_progress(fraction)
                except ValueError:
                    pass

    returncode = proc.wait()
    stderr_thread.join()
    if returncode != 0:
        tail = "\n".join("".join(stderr_lines).strip().splitlines()[-20:])
        raise FFmpegRunError(
            f"ffmpeg exited with code {returncode}", stderr_tail=tail
        )


def normalize_segment(
    src: Path,
    in_point: float,
    out_point: float,
    width: int,
    height: int,
    fps: float,
    dest: Path,
    on_progress: Optional[ProgressCallback] = None,
    crf: int = 18,
) -> None:
    """Trim [in_point, out_point) from src and re-encode it to a common
    format/resolution/fps so heterogeneous source clips can later be
    concatenated with a lossless stream copy.

    `crf` is libx264's quality knob (lower = higher quality/larger file,
    0-51) - the editor's video-settings quality preset maps to a crf value
    so "品質" actually changes the encoded output, not just resolution/fps.
    """
    duration = max(0.0, out_point - in_point)
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}"
    )
    args = [
        "-i",
        str(src),
        "-ss",
        f"{in_point:.6f}",
        "-to",
        f"{out_point:.6f}",
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        str(crf),
        "-c:a",
        "aac",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    _run(args, total_duration=duration, on_progress=on_progress)


def extract_audio_segment(
    src: Path, in_point: float, out_point: float, dest: Path
) -> None:
    duration = max(0.0, out_point - in_point)
    args = [
        "-i",
        str(src),
        "-ss",
        f"{in_point:.6f}",
        "-to",
        f"{out_point:.6f}",
        "-vn",
        "-c:a",
        "aac",
        "-ar",
        "48000",
        "-ac",
        "2",
        str(dest),
    ]
    _run(args, total_duration=duration)


def concat_files(segment_paths: list[Path], dest: Path, filelist_path: Path) -> None:
    """Concatenate pre-normalized segments (same codec/params) via the
    concat demuxer with a stream copy - no re-encode needed.
    """
    lines = []
    for p in segment_paths:
        escaped = str(p.resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    filelist_path.write_text("\n".join(lines), encoding="utf-8")

    args = [
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(filelist_path),
        "-c",
        "copy",
        str(dest),
    ]
    _run(args)


def loop_or_trim_audio(src: Path, target_duration: float, dest: Path) -> None:
    """Make an audio file exactly target_duration seconds long, looping it
    if it is shorter and trimming if it is longer.
    """
    args = [
        "-stream_loop",
        "-1",
        "-i",
        str(src),
        "-t",
        f"{target_duration:.6f}",
        "-c:a",
        "aac",
        "-ar",
        "48000",
        "-ac",
        "2",
        str(dest),
    ]
    _run(args, total_duration=target_duration)


def burn_subtitles(
    video_path: Path,
    srt_path: Path,
    dest: Path,
    force_style: str | None = None,
    crf: int = 18,
) -> None:
    """Hardsub an .srt file onto a video via libass. ffmpeg's filtergraph
    mini-language treats ':' as an option separator, so on Windows the
    drive-letter colon in the path must be escaped.

    `force_style` is a libass style override string (e.g.
    "FontName=Arial,FontSize=48,PrimaryColour=&H00FFFFFF&,Alignment=2"),
    built from the user's subtitle settings by the caller - see
    `subtitle_style.build_force_style`.
    """
    escaped_path = str(srt_path.resolve()).replace("\\", "/").replace(":", "\\:")
    filter_value = f"subtitles='{escaped_path}'"
    if force_style:
        filter_value += f":force_style='{force_style}'"
    args = [
        "-i",
        str(video_path),
        "-vf",
        filter_value,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        str(crf),
        "-c:a",
        "copy",
        str(dest),
    ]
    _run(args)


def mix_video_with_bgm(
    video_path: Path, bgm_path: Path, bgm_volume: float, dest: Path
) -> None:
    filter_complex = (
        f"[1:a]volume={bgm_volume}[bgm];"
        "[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
    )
    args = [
        "-i",
        str(video_path),
        "-i",
        str(bgm_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "0:v",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        str(dest),
    ]
    _run(args)
