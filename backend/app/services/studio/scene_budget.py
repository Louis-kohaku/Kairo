"""How many shots this material can honestly fill (requirement 8).

Requirement 8 ends with a rule that is easy to state and easy to skip:
*素材が不足している場合は無理に構成を作らず、利用可能素材から最適な構成を
生成してください.* Skipping it has a specific, visible cost, measured on a
real run of this repository: eight photos, a 30-second short, and the scene
writer produced fifteen shots. Seven were covered by the user's photos and
**eight were filled from a web image search**, which returned a nebula, a
billboard in Akihabara and an 18th-century sculpture. The video was
technically fine and had almost nothing to do with Okinawa.

The writing prompt already asks for a scene count near the material count,
but that is a suggestion, and a small local model does not reliably honour
it. This module turns it into a bound that is applied afterwards, where it
can be enforced:

* work out how many distinct shots the material can actually cover,
* allow a modest number of filled shots on top - filling is a legitimate
  feature, and a video that uses nothing but the user's photos is not the
  goal either,
* and when the design exceeds that, drop the weakest scenes and give their
  time back to the ones that remain.

"Weakest" is decided from the scene design, not at random: a scene whose
visual is a near-duplicate of another goes first, then one with no caption
and no narration, then the shortest. The opening and closing scenes are
never dropped, because a video still needs to start and end.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# How many shots one piece of material can reasonably become. A photo is one
# shot (the same picture twice reads as a mistake, whatever the Ken Burns
# move does), and a video can be cut into several - but only as many as its
# own length supports.
PHOTO_SHOTS = 1
# Filled shots allowed on top of what the material covers, as a fraction of
# the material-covered count. A third means a video built from nine photos
# may reach twelve shots; beyond that the fill stops being a supplement and
# becomes the video.
FILL_ALLOWANCE = 0.34
# Never cut a design below this many scenes, whatever the material count -
# a video with two shots is not an edit.
MIN_SCENES = 3


def supportable_shots(analyses: list, scene_seconds: float) -> int:
    """How many distinct shots the user's material can cover."""
    if not analyses:
        return 0
    shots = 0
    for item in analyses:
        if item.kind == "video" and item.duration:
            usable = item.duration
            if item.usable and item.usable.end > item.usable.start:
                usable = item.usable.end - item.usable.start
            shots += max(1, int(usable / max(1.5, scene_seconds)))
        else:
            shots += PHOTO_SHOTS
    return shots


def budget(analyses: list, scene_seconds: float, *, use_all: bool = False) -> int:
    """The largest scene count this material should be asked to carry.

    Returns 0 when there is no material at all, which the caller reads as
    "no bound" - a project with nothing uploaded is meant to be filled, and
    capping it would just make it shorter for no reason.
    """
    covered = supportable_shots(analyses, scene_seconds)
    if covered <= 0:
        return 0
    if use_all:
        # "できるだけ全部使う" is a promise about the finished video; the
        # bound must never cut below what the user gave us.
        return max(covered, MIN_SCENES)
    return max(MIN_SCENES, int(round(covered * (1.0 + FILL_ALLOWANCE))))


def _signature(scene) -> str:
    text = (getattr(scene, "visual_prompt", "") or "").strip()
    return re.sub(r"[\s、。,.!?！？「」『』()（）]", "", text)[:24].casefold()


def _weakness(scene, index: int, total: int, seen: dict[str, int]) -> tuple:
    """Sort key: higher is dropped sooner.

    A tuple rather than a number so the ordering is readable and each term
    is a separate, stated reason.
    """
    if index == 0 or index == total - 1:
        return (-1, 0.0)  # never dropped

    signature = _signature(scene)
    duplicate = 1 if signature and seen.get(signature, 0) > 1 else 0
    has_words = bool(
        (getattr(scene, "subtitle_text", "") or "").strip()
        or (getattr(scene, "narration", "") or "").strip()
    )
    return (
        duplicate,               # near-duplicate visuals go first
        0 if has_words else 1,   # then scenes that say nothing
        -float(getattr(scene, "estimated_duration", 0.0) or 0.0),  # then the shortest
    )


def trim_to_budget(scenes: list, limit: int) -> tuple[list, list[str]]:
    """Drops the weakest scenes until the design fits. Returns (kept, notes).

    The dropped scenes' time is not lost: the caller re-runs `retime_scenes`
    afterwards, which redistributes the target duration across what remains,
    so the video stays the requested length with fewer, longer shots.
    """
    if limit <= 0 or len(scenes) <= limit:
        return scenes, []

    counts: dict[str, int] = {}
    for scene in scenes:
        signature = _signature(scene)
        if signature:
            counts[signature] = counts.get(signature, 0) + 1

    total = len(scenes)
    ranked = sorted(
        range(total),
        key=lambda i: _weakness(scenes[i], i, total, counts),
        reverse=True,
    )
    drop = set(ranked[: total - limit])
    kept = [s for i, s in enumerate(scenes) if i not in drop]

    duplicates = sum(
        1 for i in drop if counts.get(_signature(scenes[i]), 0) > 1
    )
    silent = sum(
        1
        for i in drop
        if not (
            (getattr(scenes[i], "subtitle_text", "") or "").strip()
            or (getattr(scenes[i], "narration", "") or "").strip()
        )
    )
    notes = [
        f"素材で埋められる範囲を超えていたため、{total}シーンから{len(kept)}シーンに絞りました"
    ]
    if duplicates:
        notes.append(f"うち{duplicates}件は他のシーンとほぼ同じ映像内容でした")
    if silent:
        notes.append(f"うち{silent}件はナレーションも字幕もありませんでした")
    return kept, notes
