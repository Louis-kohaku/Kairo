"""Moving a still without losing what it is a picture of (requirement 6).

Kairo already gave every photo a Ken Burns move, but the move was decided
from the scene's `camera` word alone and always pivoted on the geometric
centre of the frame. On a photo whose subject is off to one side - which is
most photos people actually take - a "pan right" walks the subject out of
shot, and a hard zoom crops their head off.

This module decides the move from the picture as well as from the
direction: it takes the detail centroid `frame_quality.subject_center`
found, works out where that lands after the frame has been cropped to the
video's aspect ratio, and produces start/end framing that keeps the subject
inside the safe part of the window for the whole move.

The output is a `PhotoMove`: two anchor points and two zoom levels, which
`ffmpeg/compose.still_to_clip` turns into a zoompan expression. Everything
is computed here, in Python, rather than inside the filter expression -
an expression that clamps itself is unreadable and untestable, and this way
the plan can be shown to the user and checked by the review.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.schemas.edit_style import EditDirective

logger = logging.getLogger(__name__)

# How far from the window's edge the subject must stay, as a fraction of
# the window. 0.15 keeps a face out of the corner without making every move
# so timid it reads as static.
SAFE_INSET = 0.15
# Absolute bounds on the zoom, so no directive can ask for a move that
# turns a 12MP photo into a pixelated crop.
MIN_ZOOM = 1.0
MAX_ZOOM = 1.45


@dataclass
class PhotoMove:
    """One still's camera move, as the renderer needs it."""

    zoom_start: float
    zoom_end: float
    # Where the window is centred, in 0..1 of the *cropped* frame.
    x_start: float
    y_start: float
    x_end: float
    y_end: float
    kind: str = "zoom_in"
    reason: str = ""
    subject_x: float = 0.5
    subject_y: float = 0.5
    subject_known: bool = False
    # False when the subject was measured but the crop to the video's
    # aspect ratio put it outside the frame. Distinct from `subject_known`
    # on purpose: "we could not measure it" and "it is not in this frame
    # any more" are different facts, and only the second one is worth
    # telling the user about.
    subject_visible: bool = True


def map_subject_to_frame(
    subject: tuple[float, float] | None,
    source_size: tuple[int, int] | None,
    target_size: tuple[int, int],
) -> tuple[float, float, bool, bool]:
    """Where the subject sits after the photo is cropped to the video frame.

    `still_to_clip` scales the source up and centre-crops it to the target
    aspect ratio, so a subject at 20% across a 4:3 photo is somewhere else
    entirely once that photo has become a 9:16 frame. Ignoring that was
    half the reason the old move could push a subject out of shot.

    Returns (x, y, known, visible). `known` is False when there was no
    measurement, and the caller then treats the frame centre as the anchor,
    which is the old behaviour and correct when nothing better is known.
    `visible` is False when the subject *was* measured but the crop put it
    outside the frame - a 4:3 photo becoming a 9:16 short loses most of its
    width, so this is common and the move should say so rather than
    pretending to keep something in shot that is no longer there.
    """
    if subject is None:
        return 0.5, 0.5, False, True
    sx, sy = subject
    sx = max(0.0, min(1.0, float(sx)))
    sy = max(0.0, min(1.0, float(sy)))
    if not source_size or source_size[0] <= 0 or source_size[1] <= 0:
        return sx, sy, True, True

    source_aspect = source_size[0] / source_size[1]
    target_aspect = target_size[0] / max(1, target_size[1])
    if abs(source_aspect - target_aspect) < 0.01:
        return sx, sy, True, True

    if source_aspect > target_aspect:
        # Source is wider: the sides are cropped away.
        kept = target_aspect / source_aspect
        margin = (1.0 - kept) / 2.0
        sx = (sx - margin) / kept
    else:
        # Source is taller: the top and bottom are cropped away.
        kept = source_aspect / target_aspect
        margin = (1.0 - kept) / 2.0
        sy = (sy - margin) / kept
    # A subject cropped out of frame entirely lands outside 0..1. Clamping
    # puts the move against the edge it left through, which keeps as much
    # of it in shot as the crop allows - but the caller is told it is not
    # actually in frame, so the reason does not claim otherwise.
    visible = -0.02 <= sx <= 1.02 and -0.02 <= sy <= 1.02
    return max(0.0, min(1.0, sx)), max(0.0, min(1.0, sy)), True, visible


def _round_inward(center: float, zoom: float) -> float:
    """Rounds a window centre to 4 decimals without leaving the picture.

    Plain rounding can move the centre a few hundred-thousandths past the
    edge, which asks zoompan to sample outside the frame. The renderer
    guards against that too, but a plan that is correct only because the
    renderer corrects it is not a correct plan.
    """
    half = 0.5 / max(1.0, zoom)
    low = round(half + 5e-5, 4)
    high = round(1.0 - half - 5e-5, 4)
    if low > high:  # zoom 1.0: the window is the whole frame
        return 0.5
    return max(low, min(high, round(center, 4)))


def _clamp_center(center: float, zoom: float, subject: float) -> float:
    """Keeps the window inside the picture *and* the subject inside the window."""
    half = 0.5 / max(1.0, zoom)
    # The window must not leave the frame.
    center = max(half, min(1.0 - half, center))
    # The subject must stay inside the safe inset of the window.
    reach = half * (1.0 - 2 * SAFE_INSET)
    center = max(subject - reach, min(subject + reach, center))
    # Re-apply the frame bound, which wins: a window off the edge of the
    # picture shows black, and that is worse than a subject near the edge.
    return max(half, min(1.0 - half, center))


# What each direction means as a normalised displacement of the window
# centre, before the safety clamps. Deliberately small: a still that
# travels a third of its own width in three seconds reads as a slide show,
# not as camera movement.
_DIRECTIONS: dict[str, tuple[float, float]] = {
    "zoom_in": (0.0, 0.0),
    "zoom_out": (0.0, 0.0),
    "pan_left": (-0.10, 0.0),
    "pan_right": (0.10, 0.0),
    "pan_up": (0.0, -0.09),
    "pan_down": (0.0, 0.09),
    "ken_burns": (0.06, -0.05),
    "static": (0.0, 0.0),
}

# The camera words the scene writer and the procedural engine already use,
# mapped onto the directions above. Reuses the existing vocabulary rather
# than inventing a second one.
_CAMERA_WORDS: dict[str, str] = {
    "close-up": "zoom_in",
    "closeup": "zoom_in",
    "クローズアップ": "zoom_in",
    "アップ": "zoom_in",
    "寄り": "zoom_in",
    "zoom_in": "zoom_in",
    "ズームイン": "zoom_in",
    "wide": "zoom_out",
    "ワイド": "zoom_out",
    "引き": "zoom_out",
    "zoom_out": "zoom_out",
    "ズームアウト": "zoom_out",
    "pan_left": "pan_left",
    "パンレフト": "pan_left",
    "pan_right": "pan_right",
    "パンライト": "pan_right",
    "パン": "pan_right",
    "tilt": "pan_up",
    "ティルト": "pan_up",
    "static": "static",
    "固定": "static",
    "fix": "static",
}


def direction_for(camera: str, directive: EditDirective, index: int) -> str:
    """Which move this shot gets.

    The scene's own camera direction wins when it says something. When it
    does not, the style's preference list is cycled through by shot index,
    so a photo montage alternates rather than pushing in fourteen times -
    which is the "写真がずっと同じ動き" complaint in a different form.
    """
    low = (camera or "").strip().casefold()
    for word, direction in _CAMERA_WORDS.items():
        if word.casefold() in low:
            return direction
    preferred = [d for d in directive.photo_motion.prefer if d in _DIRECTIONS]
    if not preferred:
        preferred = ["zoom_in", "zoom_out"]
    return preferred[index % len(preferred)]


def plan_move(
    *,
    camera: str,
    index: int,
    directive: EditDirective,
    subject: tuple[float, float] | None,
    source_size: tuple[int, int] | None,
    target_size: tuple[int, int],
) -> PhotoMove:
    """The camera move for one still, with the subject kept in frame."""
    direction = direction_for(camera, directive, index)
    intensity = max(0.0, min(1.6, directive.photo_motion.intensity))
    sx, sy, known, visible = map_subject_to_frame(subject, source_size, target_size)

    # Zoom span. Scaled by the style's intensity, then bounded so the crop
    # never eats more of the picture than MAX_ZOOM allows.
    span = 0.12 * intensity
    is_pan = direction.startswith("pan_") or direction == "ken_burns"
    if direction == "zoom_out":
        zoom_start = min(MAX_ZOOM, 1.0 + span + 0.04)
        zoom_end = MIN_ZOOM + 0.01
    elif direction == "static":
        zoom_start = 1.01
        zoom_end = min(MAX_ZOOM, 1.01 + span * 0.25)
    elif is_pan:
        # A pan needs a window smaller than the frame or there is nowhere
        # to pan *to*: at zoom 1.01 the window is 99% of the picture and
        # the move gets clamped to nothing. So a pan holds a deliberately
        # tighter crop, with only a slight drift in zoom across it.
        zoom_start = min(MAX_ZOOM, 1.0 + max(0.10, span))
        zoom_end = min(MAX_ZOOM, zoom_start + span * 0.25)
    else:
        zoom_start = MIN_ZOOM + 0.01
        zoom_end = min(MAX_ZOOM, 1.0 + span + 0.04)
    # Rounded *before* the centres are computed, so the clamps below are
    # calculated against the zoom the renderer will actually use. Rounding
    # afterwards moved the window a fraction of a percent outside the
    # picture - harmless on screen, but it made the invariant untestable.
    zoom_start = round(max(MIN_ZOOM, min(MAX_ZOOM, zoom_start)), 4)
    zoom_end = round(max(MIN_ZOOM, min(MAX_ZOOM, zoom_end)), 4)

    dx, dy = _DIRECTIONS.get(direction, (0.0, 0.0))
    dx *= intensity
    dy *= intensity

    if directive.photo_motion.subject_safe and known and visible:
        # Travel symmetrically around the subject, so the subject is at the
        # centre of the move rather than at one end of it.
        base_x, base_y = sx, sy
    else:
        base_x, base_y = 0.5, 0.5

    x_start = _round_inward(_clamp_center(base_x - dx / 2.0, zoom_start, base_x), zoom_start)
    y_start = _round_inward(_clamp_center(base_y - dy / 2.0, zoom_start, base_y), zoom_start)
    x_end = _round_inward(_clamp_center(base_x + dx / 2.0, zoom_end, base_x), zoom_end)
    y_end = _round_inward(_clamp_center(base_y + dy / 2.0, zoom_end, base_y), zoom_end)

    labels = {
        "zoom_in": "ゆっくり寄る",
        "zoom_out": "ゆっくり引く",
        "pan_left": "左へ流す",
        "pan_right": "右へ流す",
        "pan_up": "上へ振る",
        "pan_down": "下へ振る",
        "ken_burns": "斜めにゆっくり動かす",
        "static": "ほぼ固定",
    }
    reason = labels.get(direction, direction)
    if known and visible:
        reason += f"（被写体は画面の{sx * 100:.0f}%・{sy * 100:.0f}%付近なので、そこを外さない範囲で動かします）"
    elif known:
        reason += "（縦形に切り抜く際に被写体が画面外になるため、中央を基準に動かします）"
    else:
        reason += "（被写体位置が分からないため、中央を基準に動かします）"
    if intensity < 0.7:
        reason += "。このスタイルでは動きを抑えます"

    return PhotoMove(
        zoom_start=round(zoom_start, 4),
        zoom_end=round(zoom_end, 4),
        x_start=round(x_start, 4),
        y_start=round(y_start, 4),
        x_end=round(x_end, 4),
        y_end=round(y_end, 4),
        kind=direction,
        reason=reason,
        subject_x=round(sx, 4),
        subject_y=round(sy, 4),
        subject_known=known,
        subject_visible=visible,
    )
