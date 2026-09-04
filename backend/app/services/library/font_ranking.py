"""Ranking caption faces against one video's actual needs.

`selector.select_font` scored fonts on readability plus a genre tag match,
and on this repository's own 112-font Japanese library that produced the
*same family for every genre*: readability dominated, the UD gothic
designed for documents won it, and it won it every time. That is the
problem requirement 3 names.

The fix is not a bigger readability bonus in the other direction. It is to
ask a different question. This module ranks against an `EditDirective` -
the style's font direction, the caption load, the language the captions are
actually in, and how large the text will be on this frame - and it keeps a
short memory of what recent productions used so a library of a hundred
usable faces stops behaving like a library of one.

Three properties are deliberate:

* **Fitness first, legibility as a floor.** A face below the directive's
  readability minimum is removed, not down-weighted; above it, the register
  the video needs decides. A tutorial and a luxury short want genuinely
  different faces and now get them.
* **Variety is a scored term, not a shuffle.** Recently used families are
  penalised, so the choice is still the best remaining fit and can still be
  explained - it never becomes "a random font".
* **Everything is recorded.** The winner, the runners-up, the reasons and
  the penalties all come back, because the brief asks for the font choice
  to be inspectable from the production log.
"""
from __future__ import annotations

import json
import logging
import re

from app.models.library import LibraryAsset
from app.schemas.edit_style import EditDirective, FontCandidate
from app.services.library import font_profile, licenses

logger = logging.getLogger(__name__)

# How many previously-used families still count as "recent". Long enough
# that a session of five videos does not repeat itself, short enough that a
# small library is not starved.
RECENT_MEMORY = 6
# Penalty applied to the most recently used family, decaying over the
# memory window. Large enough to change the winner between equally good
# faces, small enough that it can never beat a real fitness gap.
RECENT_PENALTY = 26.0


# Japanese font families ship near-identical siblings that differ only in
# metrics: "BIZ UDPGothic" is "BIZ UDGothic" with proportional Latin,
# "HGPGothicE" and "HGSGothicE" differ the same way, "MS PGothic" likewise,
# and "Yu Gothic UI" is Yu Gothic with UI metrics. To a viewer they are the
# same typeface, so treating them as different families made the variety
# rule produce "BIZ UDGothic, then BIZ UDPGothic" - which is visibly the
# same font twice.
_VARIANT_MARKERS = re.compile(
    r"(?i)(?<=\bbiz ud)[ps](?=gothic|mincho)"
    r"|(?i)(?<=\bhg)[ps](?=gothic|mincho|maru|soei|kyoka)"
    r"|(?i)(?<=\bms )p(?=gothic|mincho)"
    r"|(?i)(?<=\bud digi kyokasho )n[kp]?\b"
)
_TRAILING_VARIANT = re.compile(r"(?i)\s+(ui|pro|std|stdn|proN|n)$")


def family_key(family: str) -> str:
    """A family name with the metric-variant markers removed.

    Used only for the variety memory and for de-duplicating the candidate
    list; the row's real `family` is what gets written into the subtitle
    style, because that is the name libass has to resolve.
    """
    name = (family or "").strip()
    if not name:
        return ""
    name = _VARIANT_MARKERS.sub("", name)
    name = _TRAILING_VARIANT.sub("", name)
    return " ".join(name.split()).casefold()


def _tags(row: LibraryAsset) -> set[str]:
    try:
        return set(json.loads(row.tags_json or "[]"))
    except ValueError:
        return set()


def _eligible(rows: list[LibraryAsset], *, require_commercial: bool) -> tuple[list, int]:
    ok: list[LibraryAsset] = []
    rejected = 0
    for row in rows:
        if not row.available:
            continue
        if licenses.is_auto_usable(
            row.license_status,
            require_commercial=require_commercial,
            license_id=row.license_id,
        ):
            ok.append(row)
        else:
            rejected += 1
    return ok, rejected


def _caption_load(directive: EditDirective) -> float:
    """0.0-1.0: how much of the screen time carries text.

    Drives how heavily legibility is weighted. A video whose captions are
    on screen almost continuously cannot afford a face that only just
    clears the floor; one with three captions in sixty seconds can.
    """
    by_density = {"minimal": 0.15, "low": 0.35, "medium": 0.6, "high": 0.9}
    return max(
        by_density.get(directive.subtitle.density, 0.6),
        min(1.0, directive.subtitle.coverage),
    )


def _size_pressure(directive: EditDirective) -> float:
    """How small the captions will be relative to the frame, 0.0-1.0.

    Small text on a phone punishes thin and condensed faces far more than
    large text does, so the frame and the size scale are ranking inputs -
    the same font is a different answer at 9:16 and at 16:9.
    """
    # size_scale is relative to the user's own setting; a 16:9 delivery
    # scales it down, which raises the pressure on legibility.
    scale = max(0.4, min(1.6, directive.subtitle.size_scale))
    # A vertical frame gives text more relative height than a wide one.
    frame_factor = 1.0 if directive.height >= directive.width else 1.25
    return max(0.0, min(1.0, (1.25 - scale) * frame_factor))


def rank(
    db,
    directive: EditDirective,
    *,
    require_commercial: bool = True,
    recent_families: list[str] | None = None,
    needs_japanese: bool | None = None,
    limit: int = 8,
) -> tuple[list[FontCandidate], dict]:
    """Every eligible face, best first, with the reasons for each.

    Returns (candidates, diagnostics). The diagnostics carry the counts the
    UI shows so "1件しか候補がなかった" is visible rather than looking like a
    confident pick.
    """
    recent = [f for f in (recent_families or []) if f]
    recent_keys = [family_key(f) for f in recent]
    rows = db.query(LibraryAsset).filter(LibraryAsset.kind == "font").all()

    want_jp = directive.font.needs_japanese if needs_japanese is None else needs_japanese
    considered = len(rows)
    if want_jp:
        # A hard requirement, not a weighting: a caption in a font without
        # kana renders as boxes, which is a broken video rather than a
        # worse-looking one.
        rows = [r for r in rows if r.supports_japanese]
    if directive.font.needs_latin:
        rows = [r for r in rows if r.supports_latin]

    eligible, rejected = _eligible(rows, require_commercial=require_commercial)

    load = _caption_load(directive)
    pressure = _size_pressure(directive)
    wanted = {t.strip().lower() for t in directive.font.wanted if t.strip()}
    avoid = {t.strip().lower() for t in directive.font.avoid if t.strip()}
    style_id = directive.style
    floor = directive.font.min_readability

    scored: list[tuple[float, FontCandidate]] = []
    below_floor = 0
    for row in eligible:
        readability = int(row.readability or 0)
        if readability < floor:
            below_floor += 1
            continue

        tags = _tags(row)
        reasons: list[str] = []
        penalties: list[str] = []

        # --- fitness for this edit style ------------------------------
        fitness = font_profile.load_use_cases(row.use_cases_json).get(style_id)
        if fitness is None:
            # The library predates impression profiling. Fall back to
            # readability so the run still works, and say so - a silent
            # fallback here is what produced the identical-font behaviour.
            fitness = readability
            penalties.append("印象プロファイル未算出のため可読性で代用")
        score = fitness * 1.0
        if fitness >= 70:
            reasons.append(f"{directive.style_label}向き適性{fitness}")

        # --- legibility, weighted by how much text there is -----------
        # At minimal caption load this contributes ~12 points; at high
        # load with small text, ~55. That is the whole difference between
        # "a face that looks right" and "a face that can be read".
        legibility_weight = 0.18 + 0.42 * load + 0.25 * pressure
        score += readability * legibility_weight
        if readability >= 85 and load >= 0.6:
            reasons.append(f"字幕が多い構成のため可読性{readability}を重視")

        # --- impression axes the directive asked for -------------------
        for axis, want, label in (
            ("luxury", directive.font.luxury, "高級感"),
            ("casual", directive.font.casual, "カジュアル感"),
            ("cinematic", directive.font.cinematic, "シネマティック感"),
            ("impact", directive.font.impact, "インパクト"),
        ):
            if want <= 0.05:
                continue
            have = int(getattr(row, axis, 0) or 0)
            # Rewards matching the requested level, and penalises
            # overshooting it as well as falling short - a 95-impact
            # poster face is wrong for a directive that asked for 0.3.
            gap = abs(have / 100.0 - want)
            contribution = (1.0 - gap) * want * 40.0
            score += contribution
            if gap <= 0.18 and want >= 0.5:
                reasons.append(f"{label}{have}が方針に合致")
            elif gap >= 0.5:
                penalties.append(f"{label}が方針から離れている({have})")

        # --- explicit tag direction ------------------------------------
        matched = wanted & tags
        if matched:
            score += 7.0 * len(matched)
            reasons.append("指定スタイル一致: " + "・".join(sorted(matched)))
        hit_avoid = avoid & tags
        if hit_avoid:
            score -= 18.0 * len(hit_avoid)
            penalties.append("避けたい特徴: " + "・".join(sorted(hit_avoid)))

        # --- weight band ------------------------------------------------
        weight = int(row.weight or 400)
        if directive.font.weight_min <= weight <= directive.font.weight_max:
            score += 14.0
            reasons.append(f"ウェイト{weight}が方針の範囲内")
        else:
            distance = min(
                abs(weight - directive.font.weight_min),
                abs(weight - directive.font.weight_max),
            )
            score -= min(30.0, distance / 100.0 * 12.0)
            penalties.append(f"ウェイト{weight}が方針の範囲外")

        # --- structural disqualifiers ----------------------------------
        if "decorative" in tags or "symbol" in tags:
            score -= 55.0
            penalties.append("装飾書体のため字幕には不向き")
        if "italic" in tags:
            score -= 14.0
        if "mono" in tags and style_id != "tutorial":
            score -= 12.0
        if "coding" in tags and style_id != "tutorial":
            # Scored as well as down-weighted in the fitness map, because
            # this is the single change that stops the most legible face on
            # a developer's machine winning every video.
            score -= 30.0
            penalties.append("プログラミング用書体のため映像の字幕には不向き")

        # --- provenance -------------------------------------------------
        if not row.is_system:
            score += 8.0
            reasons.append("ライセンス明示のKairoライブラリ書体")

        # --- variety ----------------------------------------------------
        recently_used = False
        family = row.family or row.name
        key = family_key(family)
        if key and key in recent_keys:
            recently_used = True
            position = recent_keys.index(key)  # 0 = most recent
            decay = max(0.0, 1.0 - position / max(1, RECENT_MEMORY))
            score -= RECENT_PENALTY * decay
            penalties.append(
                f"直近{position + 1}本前の動画で使用済みのため優先度を下げました"
            )

        scored.append(
            (
                score,
                FontCandidate(
                    asset_id=row.id,
                    name=row.name,
                    family=family,
                    score=round(score, 1),
                    reasons=reasons[:4],
                    penalties=penalties[:3],
                    recently_used=recently_used,
                ),
            )
        )

    scored.sort(key=lambda item: item[0], reverse=True)
    diagnostics = {
        "considered": considered,
        "eligible": len(eligible),
        "rejected_for_license": rejected,
        "below_readability_floor": below_floor,
        "readability_floor": floor,
        "caption_load": round(load, 2),
        "size_pressure": round(pressure, 2),
        "recent_families": recent,
        "profiled": any(
            (r.use_cases_json or "{}") not in ("", "{}") for r in eligible
        ),
    }
    return [c for _score, c in scored[:limit]], diagnostics


def unique_families(candidates: list[FontCandidate]) -> list[FontCandidate]:
    """One entry per family.

    A scan finds Regular, Bold, Italic and BoldItalic of the same family as
    four rows, and a top-5 list made of four weights of one family tells the
    user nothing. The best-scoring face of each family is kept.
    """
    seen: set[str] = set()
    out: list[FontCandidate] = []
    for candidate in candidates:
        key = family_key(candidate.family or candidate.name)
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out
