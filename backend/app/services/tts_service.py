"""Local text-to-speech via the voices already installed in Windows
(System.Speech / SAPI5) - no extra model download, no cloud call, and no new
Python dependency. This is deliberately the *only* TTS backend: if the OS has
no voices installed (or this isn't Windows), Kairo reports that plainly
instead of pretending a TTS feature exists (design doc: never present a
dummy/no-op setting as if it does something).
"""
from __future__ import annotations

import json
import logging
import platform
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_SCRIPT_DIR = Path(__file__).resolve().parent / "tts"
_LIST_VOICES_SCRIPT = _SCRIPT_DIR / "list_voices.ps1"
_SYNTHESIZE_SCRIPT = _SCRIPT_DIR / "synthesize.ps1"


@dataclass
class TTSVoice:
    id: str
    name: str
    culture: str
    gender: str


class TTSError(RuntimeError):
    pass


def is_supported_platform() -> bool:
    return platform.system() == "Windows"


def _run_powershell(args: list[str], timeout: float = 30.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def list_voices() -> list[TTSVoice]:
    """Returns installed SAPI voices, or an empty list if this isn't
    Windows, PowerShell/System.Speech isn't available, or no voices are
    installed - all indistinguishable "nothing available" states from the
    caller's point of view, which is exactly what the UI needs to show."""
    if not is_supported_platform():
        return []
    try:
        result = _run_powershell(["-File", str(_LIST_VOICES_SCRIPT)])
    except Exception:
        logger.exception("Failed to invoke list_voices.ps1")
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        raw = json.loads(result.stdout)
    except ValueError:
        return []
    if isinstance(raw, dict):
        raw = [raw]
    return [
        TTSVoice(id=v["id"], name=v["name"], culture=v["culture"], gender=v["gender"])
        for v in raw
    ]


def synthesize_to_wav(
    text: str, voice_id: str | None, dest_path: Path, rate: int = 0
) -> None:
    """Synthesizes `text` with the given voice id (or the system default
    voice when None) and writes a .wav file to `dest_path`.

    `rate` is the SAPI speaking rate, -10 (slowest) to 10 (fastest). It is
    how the edit director's narration delivery reaches the actual audio: a
    documentary is spoken slower than an entertainment short, and without
    this the setting would be a number in a panel with nothing behind it.
    0 is the voice's own default and is what every existing caller gets.
    """
    if not is_supported_platform():
        raise TTSError("このOSではTTS(音声合成)に対応していません(Windowsのみ対応)。")
    if not text.strip():
        raise TTSError("読み上げるテキストが空です。")

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kairo_tts_") as tmp:
        text_file = Path(tmp) / f"{uuid.uuid4().hex}.txt"
        text_file.write_text(text, encoding="utf-8")

        args = ["-File", str(_SYNTHESIZE_SCRIPT), "-TextFile", str(text_file), "-OutFile", str(dest_path)]
        if voice_id:
            args.extend(["-VoiceId", voice_id])
        rate = max(-10, min(10, int(rate)))
        if rate:
            args.extend(["-Rate", str(rate)])

        result = _run_powershell(args, timeout=60.0)
        if result.returncode != 0 or not dest_path.exists():
            raise TTSError(f"音声合成に失敗しました: {result.stderr.strip() or '不明なエラー'}")
