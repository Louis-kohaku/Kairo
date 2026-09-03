"""Measuring music: tempo, beat grid, loudness, duration.

Beat Sync needs to know where the beats actually are, and "actually" is the
operative word - a BPM typed into a filename is a claim, not a measurement.
So this decodes the audio and measures it.

The method is the standard one, implemented directly on numpy (which is
already present as a torch dependency) rather than by adding librosa:

1. FFmpeg decodes to mono 22.05 kHz float samples on a pipe.
2. A short-time Fourier transform gives a spectrogram.
3. Spectral flux - the sum of positive frame-to-frame magnitude increases -
   gives an onset envelope: a signal that spikes when something starts.
4. Autocorrelating the onset envelope over the plausible tempo range finds
   the period that best explains the spikes; that period is the tempo.
5. Peaks in the onset envelope are snapped to that period to give the beat
   grid.

Everything it returns is either measured or explicitly `None`. When the
audio is too short, too quiet, or too arrhythmic for step 4 to find a
convincing period, `bpm` is `None` and `confidence` says why - which the
Beat Sync stage reads as "cut on scene boundaries instead", rather than
being handed a fabricated 120.
"""
from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from app.services.ffmpeg.util import require_binary

logger = logging.getLogger(__name__)

SAMPLE_RATE = 22050
_FRAME = 1024
_HOP = 256
# Frames per second of the onset envelope: 22050/256 ~= 86 Hz, plenty of
# resolution for beats up to 200 BPM (3.3 Hz).
_ENVELOPE_RATE = SAMPLE_RATE / _HOP
MIN_BPM = 60.0
MAX_BPM = 200.0
# Below this autocorrelation ratio the "best" period is not meaningfully
# better than its neighbours, which means the track has no beat this method
# can find. Reporting no tempo is the correct answer there.
MIN_TEMPO_CONFIDENCE = 0.12
# Envelope index i is the flux between STFT frames i and i+1, so the event
# it describes happens at frame i+1's centre, not at i*HOP. Without this
# correction the whole beat grid sits ~35 ms early - inaudible on its own,
# but it is the difference between a cut landing on the beat and just
# before it.
_ENVELOPE_TIME_OFFSET = (_HOP + _FRAME / 2) / SAMPLE_RATE


@dataclass
class AudioAnalysis:
    duration: float = 0.0
    bpm: float | None = None
    beats: list[float] = field(default_factory=list)
    downbeats: list[float] = field(default_factory=list)
    confidence: float = 0.0
    loudness_lufs: float | None = None
    peak_dbfs: float | None = None
    onset_rate: float = 0.0
    note: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "duration": round(self.duration, 3),
            "bpm": round(self.bpm, 1) if self.bpm else None,
            "beats": [round(b, 3) for b in self.beats],
            "downbeats": [round(b, 3) for b in self.downbeats],
            "confidence": round(self.confidence, 3),
            "loudness_lufs": self.loudness_lufs,
            "peak_dbfs": self.peak_dbfs,
            "onset_rate": round(self.onset_rate, 2),
            "note": self.note,
            "error": self.error,
            "method": (
                "FFmpegでデコードし、スペクトルフラックスのオンセット包絡を"
                "自己相関してテンポを推定しています（実測値）。"
            ),
        }


def _decode(path: Path, *, max_seconds: float = 300.0):
    """Decodes to a mono float32 numpy array at SAMPLE_RATE."""
    import numpy as np

    ffmpeg = require_binary("ffmpeg")
    args = [
        ffmpeg,
        "-v", "error",
        "-i", str(path),
        "-t", f"{max_seconds:.2f}",
        "-ac", "1",
        "-ar", str(SAMPLE_RATE),
        "-f", "f32le",
        "-",
    ]
    proc = subprocess.run(args, capture_output=True, check=False)
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(
            (proc.stderr.decode("utf-8", "replace").strip() or "音声をデコードできませんでした")[:400]
        )
    return np.frombuffer(proc.stdout, dtype="<f4").astype("float32")


def _onset_envelope(samples):
    """Spectral flux, normalised to 0-1."""
    import numpy as np

    if samples.size < _FRAME * 4:
        return np.zeros(0, dtype="float32")

    n_frames = 1 + (samples.size - _FRAME) // _HOP
    window = np.hanning(_FRAME).astype("float32")
    # One strided view over the signal, so the STFT is a single FFT call
    # rather than a Python loop over thousands of frames.
    frames = np.lib.stride_tricks.as_strided(
        samples,
        shape=(n_frames, _FRAME),
        strides=(samples.strides[0] * _HOP, samples.strides[0]),
        writeable=False,
    )
    spectrum = np.abs(np.fft.rfft(frames * window, axis=1))
    # Log compression: without it, loud low frequencies dominate the flux
    # and quiet percussive onsets vanish.
    spectrum = np.log1p(spectrum * 10.0)
    flux = np.diff(spectrum, axis=0)
    envelope = np.maximum(flux, 0.0).sum(axis=1)
    if envelope.size == 0:
        return envelope
    envelope -= envelope.mean()
    peak = np.abs(envelope).max()
    return (envelope / peak).astype("float32") if peak > 0 else envelope.astype("float32")


def _estimate_tempo(envelope) -> tuple[float | None, float]:
    """Autocorrelation over the plausible tempo range. Returns (bpm, confidence)."""
    import numpy as np

    if envelope.size < int(_ENVELOPE_RATE * 4):
        return None, 0.0

    signal = envelope - envelope.mean()
    correlation = np.correlate(signal, signal, mode="full")[signal.size - 1:]
    if correlation.size == 0 or correlation[0] <= 0:
        return None, 0.0
    correlation = correlation / correlation[0]

    min_lag = max(1, int(_ENVELOPE_RATE * 60.0 / MAX_BPM))
    max_lag = min(correlation.size - 1, int(_ENVELOPE_RATE * 60.0 / MIN_BPM))
    if max_lag <= min_lag:
        return None, 0.0

    window = correlation[min_lag : max_lag + 1]
    best = int(np.argmax(window))
    best_lag = min_lag + best
    strength = float(window[best])
    # Confidence is how much the winning lag stands out from the typical
    # correlation in the search range - a flat curve means "no tempo here".
    baseline = float(np.median(window))
    confidence = max(0.0, strength - baseline)
    if confidence < MIN_TEMPO_CONFIDENCE:
        return None, confidence

    bpm = 60.0 * _ENVELOPE_RATE / best_lag
    # Fold octave errors into the range short-form music actually lives in.
    while bpm < 85.0:
        bpm *= 2.0
    while bpm > 175.0:
        bpm /= 2.0
    return round(bpm, 1), confidence


def _beat_times(envelope, bpm: float, duration: float) -> list[float]:
    """A beat grid phase-locked to the strongest onset near each expected beat."""
    import numpy as np

    period = 60.0 / bpm
    period_frames = period * _ENVELOPE_RATE
    if period_frames < 2 or envelope.size == 0:
        return []

    # Phase: try every offset within one period and keep the one whose beat
    # positions land on the most onset energy. This is what stops the grid
    # from being right in tempo but half a beat out of alignment.
    best_offset, best_energy = 0.0, -1.0
    for offset in np.arange(0.0, period_frames, max(1.0, period_frames / 24.0)):
        indices = np.round(np.arange(offset, envelope.size, period_frames)).astype(int)
        indices = indices[indices < envelope.size]
        if indices.size == 0:
            continue
        energy = float(envelope[indices].sum())
        if energy > best_energy:
            best_offset, best_energy = float(offset), energy

    beats = []
    t = best_offset / _ENVELOPE_RATE + _ENVELOPE_TIME_OFFSET
    while t < duration:
        beats.append(round(max(0.0, t), 3))
        t += period
    return beats


_LOUDNESS_RE = re.compile(r"^\s*I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", re.MULTILINE)
_PEAK_RE = re.compile(r"^\s*Peak:\s*(-?\d+(?:\.\d+)?|-inf)\s*dBFS", re.MULTILINE)


def measure_loudness(path: Path) -> tuple[float | None, float | None]:
    """Integrated loudness and true peak, via FFmpeg's EBU R128 meter."""
    try:
        ffmpeg = require_binary("ffmpeg")
    except Exception:
        return None, None
    args = [ffmpeg, "-v", "info", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=180, check=False)
    except (subprocess.SubprocessError, OSError):
        return None, None
    text = proc.stderr or ""
    loudness = _LOUDNESS_RE.search(text)
    peak = _PEAK_RE.search(text)
    lufs = float(loudness.group(1)) if loudness else None
    peak_db: float | None = None
    if peak and peak.group(1) != "-inf":
        peak_db = float(peak.group(1))
    return lufs, peak_db


def analyze(path: Path, *, max_seconds: float = 300.0) -> AudioAnalysis:
    """Full measurement of one audio file. Never raises."""
    result = AudioAnalysis()
    try:
        samples = _decode(path, max_seconds=max_seconds)
    except Exception as exc:  # noqa: BLE001 - a bad file is a reported result
        result.error = str(exc)[:300]
        return result

    result.duration = round(samples.size / SAMPLE_RATE, 3)
    if result.duration < 1.0:
        result.note = "1秒未満のため拍の解析は行いません。"
        result.loudness_lufs, result.peak_dbfs = measure_loudness(path)
        return result

    try:
        envelope = _onset_envelope(samples)
        bpm, confidence = _estimate_tempo(envelope)
        result.confidence = confidence
        if bpm is not None:
            result.bpm = bpm
            result.beats = _beat_times(envelope, bpm, result.duration)
            # Four-to-the-floor is the overwhelmingly common metre in the
            # music short-form videos use; a downbeat every fourth beat is
            # stated as an assumption, not measured.
            result.downbeats = result.beats[::4]
            result.note = "1小節=4拍と仮定してダウンビートを算出しています。"
        else:
            result.note = (
                "明確なテンポを検出できませんでした（環境音やパッドなど拍の"
                "はっきりしない音源の可能性があります）。"
            )
        if envelope.size:
            # Onsets per second, counting only peaks well above the noise
            # floor. Reported as a texture measure ("how busy is this
            # track"), not used for tempo - that is the autocorrelation's
            # job.
            result.onset_rate = float(
                (envelope > (envelope.std() * 1.5)).sum() / max(result.duration, 0.001)
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Beat analysis failed for %s", path)
        result.error = str(exc)[:300]

    result.loudness_lufs, result.peak_dbfs = measure_loudness(path)
    return result
