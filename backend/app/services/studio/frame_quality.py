"""Measuring what is actually in a frame: sharpness, subject, shake.

Requirements 6 and 7 both need the same thing and neither could have it
before: numbers about the *content* of a picture rather than about its file.
`material_analysis` measured brightness, colour and frame-to-frame movement,
which is enough to say "this clip is dark" and not enough to say "this photo
is out of focus" or "the person is on the left, so do not pan right".

Everything here is measured with Pillow and plain arithmetic - no OpenCV, no
model download, no new dependency. Each measurement is documented, bounded,
and honest about being a proxy:

* **Sharpness** is the variance of a Laplacian-like second difference over
  the greyscale image, normalised by contrast. It is the standard blur
  proxy; it cannot tell a deliberately shallow depth of field from a
  missed focus, and the caller is told so.
* **Subject position** is the centroid of local detail. Where a photo has
  detail, it usually has its subject - a face, a dish, a signpost - and a
  flat sky or wall contributes nothing. It is not face detection and does
  not claim to be.
* **Shake** is the variance of frame-to-frame displacement estimated by
  comparing coarse row/column profiles. High mean movement is a pan;
  high *variance* of movement is a shaky hand, and the difference is what
  makes it usable for rejecting material.
* **Signature** is a 16x16 average hash, used to find duplicates.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_ANALYSIS_SIZE = 192
_HASH_SIZE = 16


def _pillow():
    try:
        from PIL import Image  # noqa: PLC0415

        return Image
    except Exception:  # noqa: BLE001
        return None


def _grey(path: Path, size: int = _ANALYSIS_SIZE):
    Image = _pillow()
    if Image is None:
        return None
    try:
        with Image.open(path) as im:
            grey = im.convert("L")
            grey.thumbnail((size, size))
            return grey.copy()
    except Exception:  # noqa: BLE001
        return None


def sharpness(path: Path) -> float | None:
    """0.0-1.0, higher is sharper. None when it could not be measured.

    The variance of the 4-neighbour Laplacian, divided by the image's own
    contrast so a low-contrast but perfectly focused photo is not called
    blurry. Normalised against an empirical ceiling so the number is
    comparable between photos of different subjects.

    This is a proxy, not a verdict: a portrait with a deliberately blurred
    background scores lower than a flat document scan, and the caller
    should treat a low score as "worth checking" rather than "unusable".
    """
    grey = _grey(path)
    if grey is None:
        return None
    width, height = grey.size
    if width < 8 or height < 8:
        return None
    pixels = list(grey.getdata())

    total = 0.0
    total_sq = 0.0
    count = 0
    mean = sum(pixels) / len(pixels)
    variance = sum((p - mean) ** 2 for p in pixels) / len(pixels)
    contrast = max(4.0, variance ** 0.5)

    for y in range(1, height - 1):
        row = y * width
        for x in range(1, width - 1):
            i = row + x
            lap = (
                4 * pixels[i]
                - pixels[i - 1]
                - pixels[i + 1]
                - pixels[i - width]
                - pixels[i + width]
            )
            total += lap
            total_sq += lap * lap
            count += 1
    if count == 0:
        return None
    lap_mean = total / count
    lap_var = max(0.0, total_sq / count - lap_mean * lap_mean)
    # Divided by contrast squared so the measure is about edge definition
    # rather than about how much tonal range the picture happens to have.
    normalised = (lap_var ** 0.5) / contrast
    # 1.2 is where a well-focused phone photo lands on this scale; above
    # that is noise or oversharpening, so the curve is capped there.
    return round(max(0.0, min(1.0, normalised / 1.2)), 4)


def subject_center(path: Path) -> tuple[float, float] | None:
    """Where the picture's detail is, as (x, y) in 0.0-1.0 frame coordinates.

    The detail-weighted centroid: each pixel's local gradient is its weight,
    so a face against a plain sky pulls the centroid onto the face and the
    sky contributes almost nothing. Returns the frame centre when the image
    is uniformly detailed, which is the correct answer for a texture.

    Used by the photo-motion planner to keep the subject inside the frame
    for the whole Ken Burns move (requirement 6). It is not face detection;
    the analysis records it as a detail centroid and the UI says so.
    """
    grey = _grey(path, size=128)
    if grey is None:
        return None
    width, height = grey.size
    if width < 8 or height < 8:
        return None
    pixels = list(grey.getdata())

    weight_total = 0.0
    x_total = 0.0
    y_total = 0.0
    for y in range(1, height - 1):
        row = y * width
        for x in range(1, width - 1):
            i = row + x
            gradient = abs(pixels[i] - pixels[i + 1]) + abs(pixels[i] - pixels[i + width])
            if gradient < 8:
                continue  # flat area: no subject information
            weight_total += gradient
            x_total += gradient * x
            y_total += gradient * y
    if weight_total <= 0:
        return (0.5, 0.5)
    return (
        round(max(0.0, min(1.0, x_total / weight_total / max(1, width - 1))), 4),
        round(max(0.0, min(1.0, y_total / weight_total / max(1, height - 1))), 4),
    )


def signature(path: Path) -> str | None:
    """A 16x16 average hash, as hex. Used to find duplicate material."""
    Image = _pillow()
    if Image is None:
        return None
    try:
        with Image.open(path) as im:
            small = im.convert("L").resize((_HASH_SIZE, _HASH_SIZE))
    except Exception:  # noqa: BLE001
        return None
    pixels = list(small.getdata())
    if not pixels:
        return None
    mean = sum(pixels) / len(pixels)
    bits = "".join("1" if p >= mean else "0" for p in pixels)
    return f"{int(bits, 2):0{_HASH_SIZE * _HASH_SIZE // 4}x}"


def hamming(a: str | None, b: str | None) -> int | None:
    """Bit distance between two signatures, or None if either is missing."""
    if not a or not b or len(a) != len(b):
        return None
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except ValueError:
        return None


# Two stills within this many bits of each other are the same shot. On a
# 256-bit hash, 12 bits catches burst frames and re-crops while leaving two
# genuinely different photos of the same beach apart.
DUPLICATE_THRESHOLD = 12


def _profiles(grey) -> tuple[list[float], list[float]]:
    """Row and column mean-brightness profiles of one frame."""
    width, height = grey.size
    pixels = list(grey.getdata())
    rows = [
        sum(pixels[y * width : (y + 1) * width]) / max(1, width) for y in range(height)
    ]
    cols = [
        sum(pixels[y * width + x] for y in range(height)) / max(1, height)
        for x in range(width)
    ]
    return rows, cols


def _best_shift(a: list[float], b: list[float], limit: int = 12) -> int:
    """The offset that best aligns two 1-D profiles, in samples."""
    best_shift = 0
    best_error = None
    for shift in range(-limit, limit + 1):
        error = 0.0
        count = 0
        for i in range(len(a)):
            j = i + shift
            if 0 <= j < len(b):
                error += abs(a[i] - b[j])
                count += 1
        if count < len(a) // 2:
            continue
        error /= count
        if best_error is None or error < best_error:
            best_error = error
            best_shift = shift
    return best_shift


def shake(frames: list[Path]) -> float | None:
    """0.0-1.0, higher means shakier. None when there are too few frames.

    Estimates the horizontal and vertical displacement between consecutive
    frames by aligning their row/column brightness profiles, then reports
    the *variance* of that displacement rather than its magnitude. A steady
    pan moves consistently and scores low; a hand-held shot moves
    differently every frame and scores high, which is the distinction that
    matters when deciding whether footage is usable.
    """
    if len(frames) < 3:
        return None
    profiles = []
    for frame in frames:
        grey = _grey(frame, size=64)
        if grey is None:
            continue
        profiles.append(_profiles(grey))
    if len(profiles) < 3:
        return None

    shifts: list[tuple[int, int]] = []
    for (rows_a, cols_a), (rows_b, cols_b) in zip(profiles, profiles[1:]):
        shifts.append((_best_shift(cols_a, cols_b), _best_shift(rows_a, rows_b)))
    if len(shifts) < 2:
        return None

    def variance(values: list[int]) -> float:
        mean = sum(values) / len(values)
        return sum((v - mean) ** 2 for v in values) / len(values)

    jitter = variance([s[0] for s in shifts]) + variance([s[1] for s in shifts])
    # 40 (sum of both axes' variance, in samples of a 64-wide profile) is
    # where visibly unusable hand-held footage lands.
    return round(max(0.0, min(1.0, jitter / 40.0)), 4)


def quality_score(
    *,
    sharpness_value: float | None,
    brightness: float | None,
    shake_value: float | None,
    contrast: float | None = None,
) -> tuple[float, list[str]]:
    """A 0-100 usability score with the reasons that moved it.

    Deliberately about *technical* usability only - "can this be shown" -
    and never about interest or relevance, which the matching stage judges
    from tags. Keeping the two apart is what lets the plan say "sharp but
    off-topic" instead of one opaque number.
    """
    score = 70.0
    notes: list[str] = []

    if sharpness_value is not None:
        if sharpness_value < 0.12:
            score -= 35.0
            notes.append(f"ピントが甘い（シャープネス{sharpness_value:.2f}）")
        elif sharpness_value < 0.22:
            score -= 14.0
            notes.append(f"ややピントが甘い（{sharpness_value:.2f}）")
        elif sharpness_value >= 0.45:
            score += 14.0
            notes.append(f"よく解像している（{sharpness_value:.2f}）")
        else:
            score += 6.0

    if brightness is not None:
        if brightness < 0.12:
            score -= 30.0
            notes.append(f"暗すぎる（明るさ{brightness:.2f}）")
        elif brightness < 0.22:
            score -= 12.0
            notes.append(f"やや暗い（{brightness:.2f}）")
        elif brightness > 0.88:
            score -= 22.0
            notes.append(f"白飛びしている（{brightness:.2f}）")
        elif 0.35 <= brightness <= 0.72:
            score += 10.0

    if shake_value is not None:
        if shake_value > 0.55:
            score -= 30.0
            notes.append(f"手ブレが大きい（{shake_value:.2f}）")
        elif shake_value > 0.3:
            score -= 12.0
            notes.append(f"やや手ブレがある（{shake_value:.2f}）")
        else:
            score += 6.0

    if contrast is not None and contrast < 0.08:
        score -= 12.0
        notes.append("コントラストが低く、のっぺりしている")

    return round(max(0.0, min(100.0, score)), 1), notes


def method() -> str:
    return (
        "Pillowで画像を解析したKairoの推定値です。"
        "シャープネスはラプラシアン分散、被写体位置は細部の重心、"
        "手ブレはフレーム間ズレのばらつきから求めています"
        "（顔認識や物体検出は行っていません）"
    )
