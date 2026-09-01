"""Local speech-to-text via faster-whisper.

The model is loaded lazily and cached in-process: it's the largest
memory-resident object this app creates, so loading it once and reusing it
across jobs matters both on this Intel dev box and on the 24GB Apple
Silicon target this project is ultimately built for.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core.config import WHISPER_COMPUTE_TYPE, WHISPER_DEVICE, WHISPER_MODEL_SIZE

_model = None
_model_lock = threading.Lock()


@dataclass
class TranscribedSegment:
    start: float
    end: float
    text: str


def _get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from faster_whisper import WhisperModel

                _model = WhisperModel(
                    WHISPER_MODEL_SIZE,
                    device=WHISPER_DEVICE,
                    compute_type=WHISPER_COMPUTE_TYPE,
                )
    return _model


def transcribe(path: Path, language: Optional[str] = None) -> list[TranscribedSegment]:
    model = _get_model()
    segments, _info = model.transcribe(
        str(path),
        beam_size=5,
        language=language,
        vad_filter=True,
    )
    results = []
    for seg in segments:
        text = seg.text.strip()
        if text:
            results.append(TranscribedSegment(start=seg.start, end=seg.end, text=text))
    return results
