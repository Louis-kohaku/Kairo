"""Scene material construction on top of the FFmpeg engine.

Everything here turns generated stills and synthesised audio into ordinary
video clips, so the rest of Kairo (media assets, timeline, render_service)
handles AI-produced material through exactly the same code path as an
imported file.

Like `engine.py`, every function takes typed, already-validated parameters
and never a caller-built command string; process invocation itself still
happens only in `engine._run`, so there remains exactly one place in the
codebase that spawns ffmpeg and no command-injection surface here.

One invariant worth stating: every scene clip is written *with* an audio
stream, even a silent one. The render pipeline concatenates segments with
a stream copy, and a mix of clips with and without audio cannot be
concatenated that way.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.services.ffmpeg.engine import _run


def _zoompan_expression(
    zoom_start: float, zoom_end: float, pan: str, frames: int, width: int, height: int, fps: float
) -> str:
    """Ken Burns move for a still image.

    zoompan works on a per-output-frame counter (`on`), so the zoom is a
    linear ramp over `frames`. The source is pre-scaled well above the
    target before this runs: zoompan samples from the *input* frame, and
    zooming into an image that is already at output size is what makes the
    effect look like a reel of JPEG artefacts.
    """
    frames = max(2, frames)
    span = zoom_end - zoom_start
    zoom_expr = f"{zoom_start:.4f}+({span:.4f}*on/{frames})"

    if pan == "left":
        x_expr = f"iw*0.5-(iw/zoom*0.5)-(iw*0.06*on/{frames})"
        y_expr = "ih*0.5-(ih/zoom*0.5)"
    elif pan == "right":
        x_expr = f"iw*0.5-(iw/zoom*0.5)+(iw*0.06*on/{frames})"
        y_expr = "ih*0.5-(ih/zoom*0.5)"
    elif pan == "up":
        x_expr = "iw*0.5-(iw/zoom*0.5)"
        y_expr = f"ih*0.5-(ih/zoom*0.5)-(ih*0.06*on/{frames})"
    else:
        x_expr = "iw*0.5-(iw/zoom*0.5)"
        y_expr = "ih*0.5-(ih/zoom*0.5)"

    return (
        f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}'"
        f":d={frames}:s={width}x{height}:fps={fps}"
    )


def still_to_clip(
    image_path: Path,
    dest: Path,
    duration: float,
    width: int,
    height: int,
    fps: float,
    *,
    audio_path: Optional[Path] = None,
    audio_delay: float = 0.0,
    zoom_start: float = 1.02,
    zoom_end: float = 1.12,
    pan: str = "center",
    crf: int = 20,
    fade_in: float = 0.0,
    fade_out: float = 0.0,
) -> None:
    """Renders one still image into a moving clip of exactly `duration`.

    `audio_path` (a narration wav) is padded with silence to the clip's
    length so audio and video durations match exactly; without that,
    concatenating clips whose streams differ slightly in length makes the
    audio drift further out of sync with every scene.
    """
    duration = max(0.2, duration)
    frames = max(2, int(round(duration * fps)))
    prescale = (
        f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
        f"crop={width * 2}:{height * 2}"
    )
    zoompan = _zoompan_expression(zoom_start, zoom_end, pan, frames, width, height, fps)

    # Fades are opt-in per edge, and default to none. Clips are
    # concatenated back to back, so a fade-out on one clip followed by a
    # fade-in on the next produces a black flash at *every* cut - measured
    # at 18 dips to near-black in a 19-scene video before this changed.
    # Short-form wants hard cuts; only the very end of the video fades.
    fade_in = max(0.0, min(fade_in, duration / 3))
    fade_out = max(0.0, min(fade_out, duration / 3))
    video_chain = f"{prescale},{zoompan},format=yuv420p"
    if fade_in > 0:
        video_chain += f",fade=t=in:st=0:d={fade_in:.3f}"
    if fade_out > 0:
        video_chain += f",fade=t=out:st={max(0.0, duration - fade_out):.3f}:d={fade_out:.3f}"

    args: list[str] = [
        "-loop", "1",
        "-framerate", f"{fps}",
        "-t", f"{duration:.3f}",
        "-i", str(image_path),
    ]

    if audio_path is not None:
        args += ["-i", str(audio_path)]
        delay_ms = max(0, int(audio_delay * 1000))
        audio_chain = (
            f"[1:a]adelay={delay_ms}|{delay_ms},aresample=48000,apad,"
            f"atrim=0:{duration:.3f},asetpts=N/SR/TB[a]"
        )
    else:
        args += [
            "-f", "lavfi",
            "-t", f"{duration:.3f}",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        ]
        audio_chain = f"[1:a]atrim=0:{duration:.3f},asetpts=N/SR/TB[a]"

    args += [
        "-filter_complex", f"[0:v]{video_chain}[v];{audio_chain}",
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


def video_to_clip(
    src: Path,
    dest: Path,
    duration: float,
    width: int,
    height: int,
    fps: float,
    *,
    audio_path: Optional[Path] = None,
    crf: int = 20,
    source_start: float = 0.0,
    fill: str = "pad",
) -> None:
    """Fits existing footage (the user's own, or an AI-generated clip) into
    a scene slot: scaled into frame, looped when it is shorter than the
    slot, and given the scene's narration as its audio.

    `source_start` is where in the source to cut from - the material
    analysis decides that, because taking every clip from 0:00 wastes the
    usable part of a phone video that starts on a pocket shot.

    `fill` picks between letterboxing ("pad") and filling the frame by
    cropping ("cover"). Cover is what a 16:9 holiday video needs to become
    a 9:16 short without two black bars taking half the screen; pad stays
    available for material where losing the edges would lose the subject.
    """
    duration = max(0.2, duration)
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
    args: list[str] = ["-stream_loop", "-1"]
    if source_start > 0.05:
        # Before -i so ffmpeg seeks rather than decoding and discarding;
        # -stream_loop restarts from this point, which is what we want -
        # a loop back into the unusable head would undo the choice.
        args += ["-ss", f"{source_start:.3f}"]
    args += ["-i", str(src)]
    if audio_path is not None:
        args += ["-i", str(audio_path)]
        audio_chain = f"[1:a]aresample=48000,apad,atrim=0:{duration:.3f},asetpts=N/SR/TB[a]"
    else:
        args += [
            "-f", "lavfi",
            "-t", f"{duration:.3f}",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        ]
        audio_chain = f"[1:a]atrim=0:{duration:.3f},asetpts=N/SR/TB[a]"

    args += [
        "-filter_complex", f"[0:v]{vf}[v];{audio_chain}",
        "-map", "[v]",
        "-map", "[a]",
        "-t", f"{duration:.3f}",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-ar", "48000",
        "-ac", "2",
        "-movflags", "+faststart",
        str(dest),
    ]
    _run(args, total_duration=duration)


def extract_frames(src: Path, dest_dir: Path, timestamps: list[float], width: int = 512) -> list[Path]:
    """Grabs one JPEG per timestamp from a video.

    Used by material analysis, which needs actual pixels to say anything
    about brightness, movement or content - metadata alone cannot tell a
    dark pocket shot from a bright beach.

    A frame that cannot be decoded is skipped rather than failing the
    whole analysis: a video whose last second is truncated is still
    perfectly usable material.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    produced: list[Path] = []
    for i, ts in enumerate(timestamps):
        dest = dest_dir / f"frame_{i:02d}.jpg"
        args = [
            "-ss", f"{max(0.0, ts):.3f}",
            "-i", str(src),
            "-frames:v", "1",
            "-vf", f"scale={width}:-2:force_original_aspect_ratio=decrease",
            "-q:v", "4",
            str(dest),
        ]
        try:
            _run(args)
        except Exception:
            continue
        if dest.exists() and dest.stat().st_size > 0:
            produced.append(dest)
    return produced


# Chord voicings (Hz) per mood, as simple triads in a comfortable pad
# register. Synthesised rather than shipped as audio files so Kairo stays
# download-free and every BGM bed is licence-clean by construction.
_BGM_CHORDS: dict[str, list[tuple[float, float, float]]] = {
    "gentle": [
        (261.63, 329.63, 392.00), (220.00, 277.18, 329.63),
        (196.00, 246.94, 293.66), (174.61, 220.00, 261.63),
    ],
    "bright": [
        (293.66, 369.99, 440.00), (261.63, 329.63, 392.00),
        (329.63, 415.30, 493.88), (246.94, 311.13, 369.99),
    ],
    "playful": [
        (329.63, 415.30, 493.88), (293.66, 369.99, 440.00),
        (261.63, 329.63, 392.00), (349.23, 440.00, 523.25),
    ],
    "tense": [
        (220.00, 261.63, 311.13), (207.65, 246.94, 293.66),
        (196.00, 233.08, 277.18), (185.00, 220.00, 261.63),
    ],
    "emotional": [
        (220.00, 261.63, 329.63), (196.00, 246.94, 293.66),
        (174.61, 220.00, 261.63), (164.81, 207.65, 246.94),
    ],
    "calm": [
        (196.00, 246.94, 293.66), (174.61, 220.00, 261.63),
        (164.81, 207.65, 246.94), (146.83, 185.00, 220.00),
    ],
}

BGM_MOODS = tuple(_BGM_CHORDS)


def synthesize_bgm(dest: Path, duration: float, mood: str = "gentle", chord_seconds: float = 3.2) -> None:
    """Generates a soft instrumental bed of exactly `duration` seconds.

    Deliberately understated: a low-passed, slowly-tremolo'd triad pad with
    a little filtered air. It is background, and section 26 requires it not
    to fight the narration, so it is quiet at source as well as ducked at
    the mix.
    """
    duration = max(1.0, duration)
    chords = _BGM_CHORDS.get(mood, _BGM_CHORDS["gentle"])
    chord_seconds = max(1.5, chord_seconds)

    inputs: list[str] = []
    chains: list[str] = []
    labels: list[str] = []
    idx = 0
    cursor = 0.0
    chord_no = 0
    while cursor < duration:
        chord = chords[chord_no % len(chords)]
        seg = min(chord_seconds, duration - cursor)
        for freq in chord:
            inputs += [
                "-f", "lavfi",
                "-t", f"{seg:.3f}",
                "-i", f"sine=frequency={freq:.2f}:sample_rate=48000",
            ]
            chains.append(
                f"[{idx}:a]volume=0.12,afade=t=in:st=0:d=0.6,"
                f"afade=t=out:st={max(0.0, seg - 0.7):.3f}:d=0.7,"
                f"adelay={int(cursor * 1000)}|{int(cursor * 1000)}[n{idx}]"
            )
            labels.append(f"[n{idx}]")
            idx += 1
        cursor += seg
        chord_no += 1

    # A whisper of filtered noise stops the pad sounding like a test tone.
    inputs += [
        "-f", "lavfi",
        "-t", f"{duration:.3f}",
        "-i", "anoisesrc=color=pink:sample_rate=48000:amplitude=0.03",
    ]
    chains.append(f"[{idx}:a]lowpass=f=900,volume=0.5[air]")
    labels.append("[air]")

    mix = (
        "".join(labels)
        + f"amix=inputs={len(labels)}:duration=longest:normalize=0,"
        + "lowpass=f=2200,tremolo=f=0.25:d=0.12,"
        + f"atrim=0:{duration:.3f},asetpts=N/SR/TB,volume=0.9[out]"
    )

    args = [
        *inputs,
        "-filter_complex", ";".join(chains) + ";" + mix,
        "-map", "[out]",
        "-t", f"{duration:.3f}",
        "-c:a", "aac",
        "-b:a", "160k",
        "-ar", "48000",
        "-ac", "2",
        str(dest),
    ]
    _run(args, total_duration=duration)


# Short, synthesised sound effects: (lavfi source, filter chain, length).
# Kept small and abstract on purpose - a wrong-sounding literal effect is
# worse than a clean accent.
_SFX_RECIPES: dict[str, tuple[str, str, float]] = {
    "pop": (
        "sine=frequency=680:sample_rate=48000",
        "afade=t=out:st=0.02:d=0.10,volume=0.5",
        0.14,
    ),
    "ding": (
        "sine=frequency=1320:sample_rate=48000",
        "aecho=0.8:0.7:60:0.4,afade=t=out:st=0.05:d=0.45,volume=0.4",
        0.55,
    ),
    "whoosh": (
        "anoisesrc=color=white:sample_rate=48000:amplitude=0.5",
        "highpass=f=600,lowpass=f=5000,afade=t=in:st=0:d=0.12,"
        "afade=t=out:st=0.16:d=0.2,volume=0.35",
        0.38,
    ),
    "thud": (
        "sine=frequency=90:sample_rate=48000",
        "afade=t=out:st=0.03:d=0.22,volume=0.6",
        0.26,
    ),
    "sparkle": (
        "sine=frequency=1760:sample_rate=48000",
        "tremolo=f=18:d=0.8,afade=t=out:st=0.08:d=0.4,volume=0.3",
        0.5,
    ),
    "surprise": (
        "sine=frequency=440:sample_rate=48000",
        "aecho=0.8:0.6:40:0.3,afade=t=out:st=0.06:d=0.3,volume=0.45",
        0.4,
    ),
}

SFX_KINDS = tuple(_SFX_RECIPES)


def synthesize_sfx(dest: Path, kind: str) -> float:
    """Writes one short effect; returns its length in seconds."""
    source, chain, length = _SFX_RECIPES.get(kind, _SFX_RECIPES["pop"])
    args = [
        "-f", "lavfi",
        "-t", f"{length:.3f}",
        "-i", source,
        "-af", chain,
        "-c:a", "aac",
        "-ar", "48000",
        "-ac", "2",
        str(dest),
    ]
    _run(args)
    return length


def mix_narration_with_bgm(
    video_path: Path,
    bgm_path: Path,
    dest: Path,
    *,
    bgm_volume: float = 0.22,
    duck: bool = True,
) -> None:
    """Mixes a BGM bed under a video whose own audio is the narration.

    With `duck`, the narration drives a sidechain compressor on the music,
    so the bed steps back while someone is speaking and returns in the
    gaps - section 26's "BGMがナレーションを邪魔しない" as an actual signal
    path rather than a fixed volume that is either too loud under speech or
    inaudible without it.
    """
    if duck:
        filter_complex = (
            f"[1:a]volume={bgm_volume}[bgm];"
            "[0:a]asplit=2[voice][key];"
            "[bgm][key]sidechaincompress=threshold=0.035:ratio=8:attack=15:release=320:makeup=1[ducked];"
            "[voice][ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
            "alimiter=limit=0.95[aout]"
        )
    else:
        filter_complex = (
            f"[1:a]volume={bgm_volume}[bgm];"
            "[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[aout]"
        )
    args = [
        "-i", str(video_path),
        "-i", str(bgm_path),
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        str(dest),
    ]
    _run(args)


def overlay_sfx(video_path: Path, sfx: list[tuple[Path, float]], dest: Path) -> None:
    """Lays short effects onto a finished mix at absolute timestamps."""
    if not sfx:
        raise ValueError("overlay_sfx called with no effects")
    args: list[str] = ["-i", str(video_path)]
    chains: list[str] = []
    labels = ["[0:a]"]
    for i, (path, at) in enumerate(sfx, start=1):
        args += ["-i", str(path)]
        delay = max(0, int(at * 1000))
        chains.append(f"[{i}:a]adelay={delay}|{delay},volume=0.7[s{i}]")
        labels.append(f"[s{i}]")
    filter_complex = (
        ";".join(chains)
        + ";"
        + "".join(labels)
        + f"amix=inputs={len(labels)}:duration=first:dropout_transition=0:normalize=0,"
        + "alimiter=limit=0.95[aout]"
    )
    args += [
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        str(dest),
    ]
    _run(args)
