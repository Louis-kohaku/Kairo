"""Safe FFmpeg execution engine.

This is the ONLY module that shells out to ffmpeg. Every function here takes
already-validated, typed parameters (paths, floats, ints) - never a raw
string built from user input - and always invokes ffmpeg via an argument
list (subprocess with shell=False), so there is no command-injection
surface. Higher layers (API routes, the render service) describe *what*
they want as data; this module decides *how* to ask ffmpeg for it.
"""
from __future__ import annotations

import re
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

from app.services.ffmpeg.util import require_binary

# The only shape `normalize_segment(color=...)` accepts: the two colour
# filters `color_filter()` emits, with numeric arguments and nothing else.
# Anything with a quote, a comma in the wrong place, or another filter name
# is rejected before it can reach the filtergraph.
_COLOR_CHAIN_RE = re.compile(
    r"^eq=brightness=-?\d+\.\d+:contrast=-?\d+\.\d+"
    r":saturation=-?\d+\.\d+:gamma=-?\d+\.\d+"
    r"(?:,colorbalance=bs=-?\d+\.\d+:rs=-?\d+\.\d+"
    r":rh=-?\d+\.\d+:bh=-?\d+\.\d+)?$"
    r"|^colorbalance=bs=-?\d+\.\d+:rs=-?\d+\.\d+"
    r":rh=-?\d+\.\d+:bh=-?\d+\.\d+$"
)

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


def color_filter(
    *,
    brightness: float = 0.0,
    contrast: float = 1.0,
    saturation: float = 1.0,
    gamma: float = 1.0,
    shadow_blue: float = 0.0,
    highlight_red: float = 0.0,
) -> str:
    """The FFmpeg filter chain for one colour look, or "" for no change.

    Built from typed numbers, never from a caller-supplied string, so a
    colour grade cannot become a filtergraph injection point - the same
    rule the rest of this module follows.

    Every term is clamped to a range that adjusts the picture rather than
    replacing it (requirement 13: unify the look without destroying the
    material's own colour). At the limits this is roughly ±10% brightness,
    ±25% contrast and ±35% saturation; a LUT-style transform is
    deliberately out of reach.
    """
    brightness = max(-0.10, min(0.10, float(brightness)))
    contrast = max(0.75, min(1.25, float(contrast)))
    saturation = max(0.65, min(1.35, float(saturation)))
    gamma = max(0.85, min(1.15, float(gamma)))
    shadow_blue = max(-0.3, min(0.3, float(shadow_blue)))
    highlight_red = max(-0.3, min(0.3, float(highlight_red)))

    parts: list[str] = []
    if (
        abs(brightness) > 0.002
        or abs(contrast - 1.0) > 0.002
        or abs(saturation - 1.0) > 0.002
        or abs(gamma - 1.0) > 0.002
    ):
        parts.append(
            f"eq=brightness={brightness:.4f}:contrast={contrast:.4f}"
            f":saturation={saturation:.4f}:gamma={gamma:.4f}"
        )
    if abs(shadow_blue) > 0.002 or abs(highlight_red) > 0.002:
        # colorbalance takes six terms (rs/gs/bs, rm/gm/bm, rh/gh/bh); only
        # the two the grades actually use are set, and the reds/blues are
        # pushed in opposite directions so the mid-grey stays neutral.
        parts.append(
            f"colorbalance=bs={shadow_blue:.4f}:rs={-shadow_blue * 0.5:.4f}"
            f":rh={highlight_red:.4f}:bh={-highlight_red * 0.5:.4f}"
        )
    return ",".join(parts)


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
    color: str = "",
    fill: str = "pad",
) -> None:
    """Trim [in_point, out_point) from src and re-encode it to a common
    format/resolution/fps so heterogeneous source clips can later be
    concatenated with a lossless stream copy.

    `crf` is libx264's quality knob (lower = higher quality/larger file,
    0-51) - the editor's video-settings quality preset maps to a crf value
    so "品質" actually changes the encoded output, not just resolution/fps.

    `color` is a filter chain from `color_filter()`, applied here rather
    than at the end of the render so the grade lands on every segment
    consistently and survives the concat stream copy. Empty means no
    grading, which is what a manual render does.
    """
    duration = max(0.0, out_point - in_point)
    if fill == "cover":
        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,fps={fps}"
        )
    else:
        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}"
        )
    if color:
        # `color` is the one string parameter in this module that reaches a
        # filtergraph, so it is checked rather than trusted. In practice it
        # always comes from `color_filter()` above, which builds it from
        # clamped floats; the check makes that a guarantee of the function
        # instead of a property of its current callers.
        if not _COLOR_CHAIN_RE.fullmatch(color):
            raise FFmpegRunError(f"不正なカラー補正指定です: {color[:80]}")
        vf = f"{vf},{color}"
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
    subtitle_path: Path,
    dest: Path,
    force_style: str | None = None,
    crf: int = 18,
) -> None:
    """Hardsub a subtitle file onto a video via libass.

    Accepts either an `.ass` script or an `.srt`. Prefer `.ass`: ffmpeg
    converts SRT using its own reference resolution, so libass then scales
    FontSize by `video_height / PlayResY` and a "42px" setting renders
    several times that. An ASS written by `subtitle_style.build_ass`
    declares PlayRes as the real frame size, which makes its sizes and
    margins mean output pixels.

    `force_style` is a libass override string; it is only meaningful for
    the SRT path, since an ASS already carries its own style.

    ffmpeg's filtergraph mini-language treats ':' as an option separator,
    so on Windows the drive-letter colon in the path must be escaped.
    """
    escaped_path = str(subtitle_path.resolve()).replace("\\", "/").replace(":", "\\:")
    filter_value = f"subtitles='{escaped_path}'"
    if force_style and subtitle_path.suffix.lower() != ".ass":
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


# Kairo's transition vocabulary mapped onto FFmpeg's `xfade` transitions.
# Every entry is a transition ffmpeg implements natively; there is
# deliberately no entry that would have to be faked with a filter chain
# whose behaviour we could not predict across ffmpeg versions.
#
# "cut" is absent on purpose: a cut is the absence of a transition, and the
# renderer handles it by not calling this at all.
XFADE_BY_TRANSITION: dict[str, str] = {
    "fade": "fade",
    "dissolve": "dissolve",
    "dip_to_black": "fadeblack",
    "slide_left": "slideleft",
    "slide_right": "slideright",
    "slide_up": "slideup",
    "push_left": "smoothleft",
    "zoom": "zoomin",
    # A match cut is an edit decision (two shots whose subjects line up),
    # not an effect. The nearest honest rendering is a very short dissolve,
    # and the plan records the *reason* so the user is not told an effect
    # was applied that was not.
    "match_cut": "dissolve",
}


def supports_transition(name: str) -> bool:
    return name in XFADE_BY_TRANSITION


def build_transition(
    first: Path,
    second: Path,
    dest: Path,
    *,
    transition: str,
    duration: float,
    width: int,
    height: int,
    fps: float,
    crf: int = 20,
) -> None:
    """Renders the overlap between two segments as its own short clip.

    Why a separate clip rather than one big filtergraph over the whole
    timeline: the render pipeline concatenates normalised segments with a
    stream copy, which is fast, cache-friendly and the reason a small
    timeline edit does not re-encode the untouched clips. Building each
    transition as its own segment - encoded to exactly the same
    codec/resolution/fps as the others - keeps that property. The caller
    trims `duration/2` off the tail of `first` and the head of `second`, so
    the total running time is unchanged.

    The audio is cross-faded over the same window, because a hard audio
    join under a dissolving picture is audible as a click.
    """
    xfade = XFADE_BY_TRANSITION.get(transition)
    if xfade is None:
        raise FFmpegRunError(f"未対応のトランジションです: {transition}")
    duration = max(0.08, min(duration, 2.0))

    # Both inputs are trimmed to exactly the overlap window before xfade,
    # so `offset` is 0 and the output is exactly `duration` long. Feeding
    # xfade two full-length clips instead makes its output as long as both
    # of them, which is how a transition silently adds seconds to a video.
    filter_complex = (
        f"[0:v]trim=duration={duration:.3f},setpts=PTS-STARTPTS,"
        f"scale={width}:{height},setsar=1,fps={fps},format=yuv420p[va];"
        f"[1:v]trim=duration={duration:.3f},setpts=PTS-STARTPTS,"
        f"scale={width}:{height},setsar=1,fps={fps},format=yuv420p[vb];"
        f"[va][vb]xfade=transition={xfade}:duration={duration:.3f}:offset=0[v];"
        f"[0:a]atrim=duration={duration:.3f},asetpts=PTS-STARTPTS,aresample=48000[aa];"
        f"[1:a]atrim=duration={duration:.3f},asetpts=PTS-STARTPTS,aresample=48000[ab];"
        f"[aa][ab]acrossfade=d={duration:.3f}[a]"
    )
    args = [
        "-i", str(first),
        "-i", str(second),
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "[a]",
        "-t", f"{duration:.3f}",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-r", f"{fps}",
        "-c:a", "aac",
        "-ar", "48000",
        "-ac", "2",
        "-movflags", "+faststart",
        str(dest),
    ]
    _run(args, total_duration=duration)


def trim_segment(
    src: Path,
    dest: Path,
    *,
    start: float,
    duration: float,
    width: int,
    height: int,
    fps: float,
    crf: int = 20,
) -> None:
    """Re-encodes `[start, start+duration)` of a normalised segment.

    Used to shorten the two clips either side of a transition by the half
    of the overlap each contributes. Re-encoded rather than stream-copied
    because a copy can only cut on a keyframe, and a transition boundary
    almost never lands on one - the resulting segment would be the wrong
    length and the audio would drift.
    """
    duration = max(0.04, duration)
    args = [
        "-ss", f"{max(0.0, start):.6f}",
        "-i", str(src),
        "-t", f"{duration:.6f}",
        "-vf", f"scale={width}:{height},setsar=1,fps={fps},format=yuv420p",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-r", f"{fps}",
        "-c:a", "aac",
        "-ar", "48000",
        "-ac", "2",
        "-movflags", "+faststart",
        str(dest),
    ]
    _run(args, total_duration=duration)


def normalize_loudness(
    src: Path,
    dest: Path,
    *,
    target_lufs: float = -14.0,
    true_peak: float = -1.5,
    denoise: bool = False,
) -> None:
    """Brings the finished mix to a platform-standard loudness.

    Every short-form platform normalises to roughly -14 LUFS on playback.
    A video delivered far below that is turned up by the platform along
    with its noise floor; one delivered above it is turned down, which
    wastes the headroom the mix was built with. Doing it here, once, on the
    finished file is what makes "音量が小さい" a solved problem rather than
    a recurring review finding.

    `denoise` adds a high-pass and FFmpeg's own spectral noise reduction
    (`afftdn`), for material recorded on a phone in wind or room hum. It is
    conservative on purpose - aggressive denoising makes speech sound
    underwater, which is worse than the hum.

    The video is stream-copied, so this costs seconds rather than a
    re-encode.
    """
    # Clamped to loudnorm's own accepted ranges rather than passed through.
    # These reach here from an EditDirective, which an LLM pass can adjust,
    # and a value outside the filter's range makes ffmpeg reject the whole
    # graph - losing the finished mix over a number nobody chose on purpose.
    target_lufs = max(-70.0, min(-5.0, float(target_lufs)))
    true_peak = max(-9.0, min(0.0, float(true_peak)))

    chain: list[str] = []
    if denoise:
        # 80Hz high-pass removes handling rumble and wind without touching
        # speech; afftdn at a low reduction level takes the hiss off.
        chain.append("highpass=f=80")
        chain.append("afftdn=nr=10:nf=-28")
    chain.append(
        f"loudnorm=I={target_lufs:.1f}:TP={true_peak:.1f}:LRA=11"
    )
    chain.append("alimiter=limit=0.97")

    args = [
        "-i", str(src),
        "-af", ",".join(chain),
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-ac", "2",
        "-movflags", "+faststart",
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
