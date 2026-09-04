"""Font impressions: what a face *feels* like, as numbers you can rank on.

`fonts.py` already answers the factual questions - can this render kana, how
heavy is it, how legible is it when shrunk. That was enough to pick "the
most legible Japanese font", which is exactly the problem requirement 3
describes: the most legible Japanese font on a Windows machine is a UD
gothic designed for documents, and it was being chosen for every genre, every
time. Measured on this repository's own library, `select_font` returned the
same family for all twelve genres.

Legibility is necessary and nowhere near sufficient. A caption face also has
a register - a thin Mincho reads as expensive, a heavy rounded gothic reads
as friendly - and that register is what makes a Vlog caption look like a
Vlog rather than like a spreadsheet.

So this module derives five impression axes plus a per-edit-style fitness
map from the metrics the font file itself declares. Each is:

* **derived, not asserted** - every axis is a documented formula over
  PANOSE class, weight class, width class, x-height ratio and the style
  tags; nothing is looked up from a curated list of "good fonts", because
  such a list would be wrong on the user's machine;
* **repeatable** - the same file always scores the same, so a decision can
  be explained and re-checked;
* **a heuristic, and labelled one** - `method()` returns the sentence the
  UI shows next to these numbers, in the same spirit as the existing
  readability score.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.services.library import fontfile

logger = logging.getLogger(__name__)

# Glyphs rendered to measure how heavy a face actually looks. Two kanji with
# very different stroke counts plus a kana and a Latin letter, so the
# measurement is not dominated by one character's design.
_INK_PROBES = "永あ国A"
_INK_SIZE = 64


def ink_coverage(path: str, collection_index: int = 0) -> float | None:
    """The fraction of the em box a face actually inks, 0.0-1.0.

    `usWeightClass` is a declaration, and display faces routinely get it
    wrong: Dela Gothic One - an ultra-heavy poster face - declares 400, and
    its PANOSE weight byte says "Book". Ranking on the declaration alone
    therefore scored it as a light text font and it never won a slot on a
    short, which is exactly the kind of blind spot that made every video
    end up with the same caption face.

    So the glyphs are rasterised and the ink is counted. This is a
    measurement of the file rather than a claim about it, it works for any
    font including ones with no usable PANOSE, and it costs one 64px raster
    per face at scan time.

    Returns None when Pillow cannot open the file - a real answer that the
    callers treat as "fall back to the declared weight".
    """
    try:
        from PIL import Image, ImageDraw, ImageFont  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None

    try:
        font = ImageFont.truetype(str(path), _INK_SIZE, index=collection_index)
    except Exception:  # noqa: BLE001 - a font Pillow cannot open is not fatal
        return None

    inked = 0
    total = 0
    for char in _INK_PROBES:
        try:
            image = Image.new("L", (_INK_SIZE * 2, _INK_SIZE * 2), 0)
            draw = ImageDraw.Draw(image)
            draw.text((_INK_SIZE // 2, _INK_SIZE // 4), char, font=font, fill=255)
            bbox = image.getbbox()
            if bbox is None:
                # The face has no glyph for this probe; not evidence either
                # way, so it contributes nothing rather than counting as
                # "no ink".
                continue
            box = image.crop(bbox)
            pixels = list(box.getdata())
            if not pixels:
                continue
            inked += sum(1 for p in pixels if p > 96)
            total += len(pixels)
        except Exception:  # noqa: BLE001
            continue

    if total == 0:
        return None
    return round(inked / total, 4)


def perceived_weight(info: fontfile.FontInfo, ink: float | None) -> int:
    """A 100-900 weight the ranking can trust.

    The declared `usWeightClass` when there is no measurement, and the
    measured ink coverage when there is - but only when the two disagree
    substantially, so a correctly-declared font keeps its own number and
    only the mislabelled display faces get corrected.

    The mapping is calibrated against faces measured on this machine, whose
    declared weights are known to be correct:

        MS Mincho (400)        0.237
        Yu Gothic Medium (500) 0.317
        Yu Gothic Bold (700)   0.465
        BIZ UDGothic Bold(700) 0.469
        Meiryo Bold (700)      0.539
        Dela Gothic One (?)    0.723   <- declares 400, is a poster face

    so the anchors are 0.24 -> 400, 0.47 -> 700, 0.72 -> 900, piecewise
    linear between them. The 200-unit disagreement threshold is what keeps
    every correctly-declared font on its own number: only Dela Gothic One,
    in the list above, is re-rated.
    """
    declared = info.weight_class or 400
    if ink is None:
        return declared
    if ink <= 0.24:
        measured = 300
    elif ink <= 0.47:
        measured = 400 + (ink - 0.24) / 0.23 * 300
    elif ink <= 0.72:
        measured = 700 + (ink - 0.47) / 0.25 * 200
    else:
        measured = 900
    measured = int(max(100, min(900, round(measured))))
    if abs(measured - declared) < 200:
        return declared
    return measured


def weight_of(info: fontfile.FontInfo) -> int:
    """The weight every axis below ranks on.

    Reads the measured value when the scan produced one (fonts.py sets
    `measured_weight` after rasterising), and the declared `usWeightClass`
    otherwise. One accessor rather than the check repeated in six places,
    so a face can never be light on one axis and heavy on another.
    """
    measured = getattr(info, "measured_weight", 0) or 0
    return measured if measured > 0 else (info.weight_class or 400)


# Every edit style (services/studio/edit_styles.py) this module scores
# fitness for. Kept as a plain tuple rather than importing the style table,
# so the library layer does not depend on the studio layer.
USE_CASES: tuple[str, ...] = (
    "vlog",
    "travel",
    "cinematic",
    "food",
    "tutorial",
    "entertainment",
    "shorts",
    "documentary",
    "luxury",
    "casual",
)


def _clamp(value: float) -> int:
    return int(max(0, min(100, round(value))))


def classify(tags: list[str]) -> str:
    """The single word that best describes this face's construction.

    Order matters: a handwritten face that also has serifs is handwritten
    first, because that is what a viewer sees. `unknown` is a real answer
    for a file whose PANOSE is empty and whose name says nothing.
    """
    tag_set = set(tags)
    for candidate in ("handwritten", "decorative", "mono", "rounded", "serif", "sans"):
        if candidate in tag_set:
            return "display" if candidate == "decorative" else candidate
    return "unknown"


def _x_height_ratio(info: fontfile.FontInfo) -> float:
    upm = info.units_per_em or 1000
    if info.x_height:
        return info.x_height / upm
    if info.cap_height:
        # Rough conversion: x-height is typically ~0.72 of cap height in a
        # text face. Used only when the font declares no x-height at all.
        return (info.cap_height / upm) * 0.72
    return 0.5


def luxury(info: fontfile.FontInfo, tags: list[str]) -> int:
    """High-end register: light serif, generous proportions, no decoration.

    The properties that read as expensive in a caption are the opposite of
    the ones that read as loud - thin strokes, serifs or very clean
    geometry, a small x-height (which looks classical), and normal width.
    """
    weight = weight_of(info)
    tag_set = set(tags)
    score = 30.0

    if "serif" in tag_set:
        score += 26.0
    if "elegant" in tag_set:
        score += 10.0
    if "rounded" in tag_set:
        score -= 22.0  # rounded is friendly, never expensive
    if "handwritten" in tag_set:
        score -= 16.0
    if "decorative" in tag_set:
        score -= 24.0
    if "mono" in tag_set:
        score -= 20.0
    if "universal_design" in tag_set:
        score -= 10.0  # UD faces are designed for clarity, not for register

    # Weight: 200-450 is the luxury band; anything above 700 is a poster.
    if weight <= 300:
        score += 22.0
    elif weight <= 450:
        score += 16.0
    elif weight <= 600:
        score += 2.0
    elif weight >= 800:
        score -= 20.0
    else:
        score -= 8.0

    ratio = _x_height_ratio(info)
    # A small x-height reads as classical; a large one reads as utilitarian.
    score += max(-14.0, min(14.0, (0.50 - ratio) * 140.0))

    width = info.width_class or 5
    score -= abs(width - 5) * 4.0
    if info.is_italic:
        score += 4.0
    return _clamp(score)


def casual(info: fontfile.FontInfo, tags: list[str]) -> int:
    """Approachable register: rounded, medium weight, open counters."""
    weight = weight_of(info)
    tag_set = set(tags)
    score = 34.0

    if "rounded" in tag_set:
        score += 30.0
    if "friendly" in tag_set:
        score += 12.0
    if "handwritten" in tag_set:
        score += 18.0
    if "serif" in tag_set:
        score -= 20.0
    if "mono" in tag_set:
        score -= 14.0
    if "universal_design" in tag_set:
        score += 4.0

    if 450 <= weight <= 750:
        score += 14.0
    elif weight <= 250:
        score -= 12.0
    elif weight >= 850:
        score -= 6.0

    ratio = _x_height_ratio(info)
    score += max(-12.0, min(16.0, (ratio - 0.50) * 140.0))
    return _clamp(score)


def cinematic(info: fontfile.FontInfo, tags: list[str]) -> int:
    """Film-title register: restrained, wide-set, light-to-medium.

    Deliberately overlaps `luxury` without duplicating it: a cinematic face
    can be a clean geometric sans (which luxury penalises less than it
    rewards serifs), and it strongly prefers the absence of anything
    playful.
    """
    weight = weight_of(info)
    tag_set = set(tags)
    score = 32.0

    if "serif" in tag_set:
        score += 16.0
    if "clean" in tag_set or "modern" in tag_set:
        score += 14.0
    if "elegant" in tag_set:
        score += 10.0
    if "rounded" in tag_set:
        score -= 26.0
    if "handwritten" in tag_set:
        score -= 22.0
    if "decorative" in tag_set:
        score -= 20.0
    if "universal_design" in tag_set:
        score -= 12.0
    if "mono" in tag_set:
        score -= 8.0

    if weight <= 350:
        score += 18.0
    elif weight <= 550:
        score += 10.0
    elif weight >= 800:
        score -= 18.0

    width = info.width_class or 5
    # Slightly wide reads as widescreen; condensed reads as tabloid.
    if width >= 6:
        score += 6.0
    elif width <= 4:
        score -= 8.0
    return _clamp(score)


def impact(info: fontfile.FontInfo, tags: list[str]) -> int:
    """How hard this face hits at a glance - the telop axis."""
    weight = weight_of(info)
    tag_set = set(tags)
    score = 20.0

    if weight >= 800:
        score += 34.0
    elif weight >= 700:
        score += 28.0
    elif weight >= 600:
        score += 18.0
    elif weight >= 500:
        score += 8.0
    elif weight <= 300:
        score -= 22.0

    if "sans" in tag_set:
        score += 12.0
    if "impact" in tag_set:
        score += 10.0
    if "decorative" in tag_set:
        score += 6.0
    if "serif" in tag_set:
        score -= 10.0
    if "light" in tag_set:
        score -= 16.0

    ratio = _x_height_ratio(info)
    score += max(-10.0, min(16.0, (ratio - 0.48) * 150.0))
    return _clamp(score)


def friendliness(info: fontfile.FontInfo, tags: list[str]) -> int:
    tag_set = set(tags)
    score = 35.0
    if "rounded" in tag_set:
        score += 32.0
    if "friendly" in tag_set:
        score += 14.0
    if "handwritten" in tag_set:
        score += 14.0
    if "universal_design" in tag_set:
        score += 8.0
    if "serif" in tag_set:
        score -= 14.0
    if "mono" in tag_set:
        score -= 18.0
    if weight_of(info) >= 850:
        score -= 10.0
    return _clamp(score)


def authority(info: fontfile.FontInfo, tags: list[str]) -> int:
    """Trustworthy / instructional register - the explainer axis."""
    tag_set = set(tags)
    weight = weight_of(info)
    score = 32.0
    if "universal_design" in tag_set:
        score += 26.0
    if "readable" in tag_set:
        score += 10.0
    if "sans" in tag_set:
        score += 10.0
    if "serif" in tag_set:
        score += 6.0
    if "handwritten" in tag_set:
        score -= 26.0
    if "decorative" in tag_set:
        score -= 28.0
    if info.is_italic:
        score -= 10.0
    if 500 <= weight <= 750:
        score += 12.0
    elif weight <= 300:
        score -= 12.0
    width = info.width_class or 5
    score -= abs(width - 5) * 3.0
    return _clamp(score)


def use_case_fitness(
    *,
    readability: int,
    luxury_score: int,
    casual_score: int,
    cinematic_score: int,
    impact_score: int,
    friendly_score: int,
    authority_score: int,
    tags: list[str],
) -> dict[str, int]:
    """How well this face suits each edit style, 0-100.

    A weighted blend of the axes above, with the weights chosen to say what
    each style actually needs: a tutorial caption is read, so authority and
    readability dominate; a luxury caption is looked at, so register does.
    Every style keeps a readability floor, because an unreadable caption is
    not a stylistic choice.
    """
    tag_set = set(tags)
    r = float(readability)

    def blend(*pairs: tuple[float, float]) -> int:
        total_weight = sum(w for w, _ in pairs) or 1.0
        return _clamp(sum(w * v for w, v in pairs) / total_weight)

    fitness = {
        "vlog": blend((0.35, r), (0.30, casual_score), (0.20, 100 - impact_score), (0.15, cinematic_score)),
        "travel": blend((0.35, r), (0.25, cinematic_score), (0.20, impact_score), (0.20, casual_score)),
        "cinematic": blend((0.20, r), (0.50, cinematic_score), (0.30, luxury_score)),
        "food": blend((0.35, r), (0.35, friendly_score), (0.30, impact_score)),
        "tutorial": blend((0.45, r), (0.40, authority_score), (0.15, impact_score)),
        "entertainment": blend((0.30, r), (0.55, impact_score), (0.15, casual_score)),
        "shorts": blend((0.40, r), (0.40, impact_score), (0.20, casual_score)),
        "documentary": blend((0.35, r), (0.35, authority_score), (0.30, cinematic_score)),
        "luxury": blend((0.15, r), (0.60, luxury_score), (0.25, cinematic_score)),
        "casual": blend((0.35, r), (0.45, friendly_score), (0.20, casual_score)),
    }

    # A programming font is a legible font that looks like a terminal. It
    # is a legitimate choice for a tutorial (where code-adjacent is the
    # register), and the wrong answer everywhere else - which is precisely
    # how the library's most legible face ended up on every video.
    if "coding" in tag_set:
        for key in fitness:
            fitness[key] = _clamp(fitness[key] * (0.95 if key == "tutorial" else 0.6))
    # Hard disqualifiers, applied after the blend so the reason is visible:
    # a decorative or handwritten face is not a caption face for the styles
    # that put text on screen constantly.
    if "decorative" in tag_set:
        for key in ("tutorial", "documentary", "shorts", "travel"):
            fitness[key] = _clamp(fitness[key] * 0.45)
    if "mono" in tag_set:
        for key in fitness:
            if key != "tutorial":
                fitness[key] = _clamp(fitness[key] * 0.7)
    if "italic" in tag_set:
        for key in fitness:
            fitness[key] = _clamp(fitness[key] * 0.85)
    return fitness


def build(info: fontfile.FontInfo, tags: list[str], readability: int) -> dict:
    """Every impression axis plus the fitness map, for one font face."""
    lux = luxury(info, tags)
    cas = casual(info, tags)
    cin = cinematic(info, tags)
    imp = impact(info, tags)
    fri = friendliness(info, tags)
    aut = authority(info, tags)
    return {
        "luxury": lux,
        "casual": cas,
        "cinematic": cin,
        "impact": imp,
        "friendliness": fri,
        "authority": aut,
        "classification": classify(tags),
        "use_cases": use_case_fitness(
            readability=readability,
            luxury_score=lux,
            casual_score=cas,
            cinematic_score=cin,
            impact_score=imp,
            friendly_score=fri,
            authority_score=aut,
            tags=tags,
        ),
        "method": method(),
    }


def method() -> str:
    return (
        "PANOSE分類・ウェイト・字幅・x-height比・スタイルタグから算出した"
        "Kairoの推定値です（フォント名の一覧照合ではなく、フォントファイル自身の"
        "情報から機械的に導いた指標で、実測の官能評価ではありません）"
    )


def load_use_cases(raw: str | None) -> dict[str, int]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): int(v) for k, v in data.items() if isinstance(v, (int, float))}


def needs_profiling(rows: list) -> bool:
    """Whether the library still has to be re-scanned for these axes.

    A library written before impressions existed has them all at zero,
    which would make every font score identically and put the selection
    straight back to "the most legible one". Detected rather than assumed
    so the pipeline can trigger one rescan instead of silently ranking on
    nothing.
    """
    fonts = [r for r in rows if r.kind == "font" and r.available]
    if not fonts:
        return False
    return not any((r.use_cases_json or "{}") not in ("", "{}") for r in fonts)
