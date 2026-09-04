"""Font Intelligence: knowing fonts well enough to choose one.

A list of installed font names is not enough to pick a caption face. What
the production pipeline needs to ask is "a Japanese-capable, heavy, highly
legible face that suits a travel short on a phone screen", and to get an
answer it can justify.

So every font Kairo can reach is read (`fontfile.py`), scored and tagged:

* **Language coverage** comes from the font's own cmap, not its name.
* **Style** (sans / serif / rounded / decorative / handwritten / mono)
  comes from its PANOSE classification, with the family name only used to
  *add* Japanese-specific tags PANOSE has no vocabulary for (UD fonts,
  明朝/ゴシック naming) - never to override what the file says.
* **Readability** is an explicit, documented heuristic over real metrics -
  x-height ratio, weight, width and monospacing - and is labelled as a
  heuristic everywhere it is shown. It is not a measurement of legibility;
  it is a repeatable ranking that prefers the properties that survive being
  shrunk to a phone.
* **Genre fit** is a deterministic mapping from those tags, so the same
  font always suits the same genres and the choice can be explained.

Licence is never inferred from any of this: a system font is recorded as
OS-bundled (conditional), a downloaded font carries the licence its
distribution declared, and anything else is `unknown` and therefore not
auto-selectable.
"""
from __future__ import annotations

import json
import logging
import os
import platform
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import LIBRARY_ROOT
from app.models.library import LibraryAsset
from app.services.library import font_profile, fontfile, licenses

logger = logging.getLogger(__name__)

FONTS_ROOT = LIBRARY_ROOT / "fonts"
# Mirrors the layout in the design brief: language-partitioned, so a human
# browsing the folder can see at a glance what is available for Japanese.
FONT_SUBDIRS = ("jp", "en", "multi")


def ensure_dirs() -> None:
    for sub in FONT_SUBDIRS:
        (FONTS_ROOT / sub).mkdir(parents=True, exist_ok=True)


def system_font_dirs() -> list[Path]:
    """Where this OS keeps fonts. Only directories that exist are returned."""
    candidates: list[Path] = []
    system = platform.system()
    if system == "Windows":
        windir = Path(os.environ.get("WINDIR", "C:/Windows"))
        candidates.append(windir / "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    elif system == "Darwin":
        candidates += [
            Path("/System/Library/Fonts"),
            Path("/Library/Fonts"),
            Path.home() / "Library" / "Fonts",
        ]
    else:
        candidates += [
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
            Path.home() / ".fonts",
            Path.home() / ".local/share/fonts",
        ]
    return [c for c in candidates if c.is_dir()]


# ---------------------------------------------------------------- tagging

# PANOSE family type (byte 0) and serif style (byte 1), per the OpenType
# specification. Only used for Latin-text family types; other family types
# are their own answer.
_PANOSE_SERIF_STYLES_SANS = {11, 12, 13}
_PANOSE_SERIF_STYLE_ROUNDED = 15

# Family-name markers for Japanese programming fonts. These families are
# hybrids (proportional CJK + fixed-width Latin), so no table in the file
# reports them as monospaced, yet they are editor fonts and read as such on
# screen. Matched case-insensitively as substrings of the family name.
_CODING_FAMILY_MARKERS: tuple[str, ...] = (
    "udev gothic",
    "hackgen",
    "plemol",
    "moralerspace",
    "cica",
    "ricty",
    "myrica",
    "firge",
    "juisee",
    "bizin gothic",
    "白源",
    "jetbrains",
    "cascadia",
    "source code",
    "fira code",
    "iosevka",
    "hasklig",
    "sarasa",
    "更紗",
)


def style_tags(info: fontfile.FontInfo, family: str) -> list[str]:
    tags: list[str] = []
    panose = info.panose or ()
    family_type = panose[0] if len(panose) > 0 else 0
    serif_style = panose[1] if len(panose) > 1 else 0

    if family_type == 3:
        tags.append("handwritten")
    elif family_type == 4:
        tags.append("decorative")
    elif family_type == 5:
        tags.append("symbol")
    elif family_type == 2:
        if serif_style == _PANOSE_SERIF_STYLE_ROUNDED:
            tags += ["rounded", "sans"]
        elif serif_style in _PANOSE_SERIF_STYLES_SANS:
            tags.append("sans")
        elif serif_style >= 2:
            tags.append("serif")

    lowered = f"{family} {info.subfamily}".casefold()
    # Japanese naming conventions PANOSE has no field for. These add tags;
    # they never remove one the file itself asserted.
    if any(k in lowered for k in ("mincho", "明朝", "serif")) and "serif" not in tags:
        tags.append("serif")
    if any(k in lowered for k in ("gothic", "ゴシック", "sans")) and "sans" not in tags:
        tags.append("sans")
    if any(k in lowered for k in ("round", "丸ゴ", "maru", "rounded")) and "rounded" not in tags:
        tags.append("rounded")
    if "ud" in lowered.split() or lowered.startswith("ud") or " ud" in lowered:
        tags.append("universal_design")
    if any(k in lowered for k in ("mono", "code", "consol", "courier")):
        tags.append("mono")
    if info.is_monospace and "mono" not in tags:
        tags.append("mono")
    if any(k in lowered for k in _CODING_FAMILY_MARKERS):
        # Japanese programming fonts (UDEV Gothic, HackGen, PlemolJP,
        # Cica, Ricty, ...) pair a proportional CJK face with a fixed-width
        # Latin one, so neither `post.isFixedPitch` nor PANOSE reports them
        # as monospaced - the file genuinely is not. They are still built
        # for a code editor, and they were what the old selector kept
        # choosing for every video: highest readability, no register.
        #
        # This is the one place a family *name* is allowed to add a tag,
        # and only because these families say what they are in their own
        # names. It adds "coding"; it never removes a tag the file asserted.
        tags.append("coding")

    weight = font_profile.weight_of(info)
    if weight <= 300:
        tags.append("light")
    elif weight >= 800:
        tags.append("black")
    elif weight >= 600:
        tags.append("bold")
    elif weight >= 500:
        tags.append("medium")
    else:
        tags.append("regular")

    if info.is_italic:
        tags.append("italic")
    if info.is_variable:
        tags.append("variable")

    # Impression tags used by the planner's vocabulary. Derived, and
    # deliberately few - three overlapping adjectives per font would make
    # the selection explanation meaningless.
    if "sans" in tags and weight >= 600:
        tags.append("impact")
    if "sans" in tags and 350 <= weight <= 550:
        tags.append("clean")
    if "rounded" in tags:
        tags.append("friendly")
    if "serif" in tags:
        tags.append("elegant")
    if "universal_design" in tags:
        tags.append("readable")
    if "sans" in tags and "mono" not in tags and "decorative" not in tags:
        tags.append("modern")
    return sorted(set(tags))


def readability_score(info: fontfile.FontInfo, tags: list[str]) -> int:
    """A 0-100 heuristic for "survives being shrunk onto a phone".

    Documented rather than tuned: x-height carries most of the perceived
    size of running text, weight decides whether the glyph holds up against
    a busy frame, and the styles that hurt small-size legibility (thin,
    decorative, handwritten, condensed, monospaced) are subtracted. It is a
    ranking aid, not a measurement, and is presented as such.
    """
    upm = info.units_per_em or 1000
    score = 50.0

    # x-height ratio: ~0.52 is typical for a legible UI face.
    if info.x_height:
        ratio = info.x_height / upm
        score += max(-15.0, min(20.0, (ratio - 0.45) * 200.0))
    elif info.cap_height:
        ratio = info.cap_height / upm
        score += max(-10.0, min(12.0, (ratio - 0.68) * 120.0))

    weight = font_profile.weight_of(info)
    if 500 <= weight <= 750:
        score += 14.0  # the band captions actually want
    elif 400 <= weight < 500:
        score += 8.0
    elif weight < 300:
        score -= 18.0
    elif weight > 850:
        score -= 6.0

    # usWidthClass 5 is normal; condensed faces lose legibility at size.
    width = info.width_class or 5
    score -= abs(width - 5) * 3.0

    if "decorative" in tags:
        score -= 22.0
    if "handwritten" in tags:
        score -= 16.0
    if "mono" in tags:
        score -= 8.0
    if "italic" in tags:
        score -= 5.0
    if "universal_design" in tags:
        score += 12.0  # UD fonts are designed for exactly this
    if "rounded" in tags:
        score += 3.0

    return int(max(0, min(100, round(score))))


# Deterministic tag -> genre mapping. Every genre lists the tags that make a
# font suitable for it; a font matching none of a genre's tags is simply not
# offered for that genre rather than ranked last.
_GENRE_TAGS: dict[str, tuple[str, ...]] = {
    "travel": ("modern", "clean", "sans", "rounded", "light", "regular", "medium"),
    "pet": ("rounded", "friendly", "bold", "sans", "medium"),
    "food": ("rounded", "bold", "friendly", "sans", "medium"),
    "game": ("impact", "bold", "black", "sans", "decorative"),
    "vlog": ("clean", "sans", "light", "regular", "modern"),
    "beauty": ("elegant", "serif", "light", "modern", "clean"),
    "education": ("readable", "universal_design", "sans", "bold", "medium", "clean"),
    "entertainment": ("impact", "bold", "black", "sans"),
    "sports": ("impact", "bold", "black", "sans"),
    "tech": ("modern", "clean", "sans", "mono", "medium"),
    "news": ("readable", "sans", "bold", "medium", "universal_design"),
    "business": ("clean", "readable", "sans", "medium", "universal_design"),
}


def genre_fit(tags: list[str]) -> list[str]:
    tag_set = set(tags)
    return [g for g, wanted in _GENRE_TAGS.items() if tag_set & set(wanted)]


def languages(info: fontfile.FontInfo) -> list[str]:
    langs: list[str] = []
    if info.supports_japanese:
        langs.append("ja")
    if info.supports_latin:
        langs.append("en")
    return langs


def language_dir(info: fontfile.FontInfo) -> str:
    if info.supports_japanese and info.supports_latin:
        return "multi"
    if info.supports_japanese:
        return "jp"
    return "en"


# ---------------------------------------------------------------- scanning


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _measure_weight(info: fontfile.FontInfo, path: Path) -> None:
    """Rasterises the face to find out how heavy it actually looks.

    Done once per scan and written onto the FontInfo, because a font's
    declared weight is a claim: Dela Gothic One, a poster face, declares
    400. Every tag and impression below then reads the measured number
    through `font_profile.weight_of`, so a mislabelled display face stops
    being ranked as body text.
    """
    if info.measured_weight:
        return
    ink = font_profile.ink_coverage(str(path), info.collection_index)
    if ink is None:
        return
    info.ink_coverage = ink
    info.measured_weight = font_profile.perceived_weight(info, ink)


def _describe(info: fontfile.FontInfo, path: Path) -> dict:
    family = info.family or path.stem
    _measure_weight(info, path)
    tags = style_tags(info, family)
    readability = readability_score(info, tags)
    # Impression axes and per-edit-style fitness. Computed here, at scan
    # time, rather than at selection time: ranking 400+ faces on every
    # production would re-read every font file, and these values only
    # change when the file does.
    profile = font_profile.build(info, tags, readability)
    return {
        "family": family,
        "subfamily": info.subfamily,
        "tags": tags,
        "genres": genre_fit(tags),
        "languages": languages(info),
        "readability": readability,
        "profile": profile,
        "weight": font_profile.weight_of(info),
        "declared_weight": info.weight_class or 400,
        "ink_coverage": info.ink_coverage or None,
        "supports_japanese": info.supports_japanese,
        "supports_latin": info.supports_latin,
        "analysis": {
            "units_per_em": info.units_per_em,
            "x_height": info.x_height,
            "cap_height": info.cap_height,
            "x_height_ratio": round(info.x_height / (info.units_per_em or 1000), 3)
            if info.x_height
            else None,
            "width_class": info.width_class,
            "declared_weight_class": info.weight_class,
            "measured_weight": info.measured_weight or None,
            "ink_coverage": info.ink_coverage or None,
            "weight_method": (
                "グリフを実際に描画してインク量を測定し、"
                "宣言値と大きく違う場合のみ採用します"
            ),
            "glyph_count": info.glyph_count,
            "panose": list(info.panose),
            "is_variable": info.is_variable,
            "is_monospace": info.is_monospace,
            "is_italic": info.is_italic,
            "designer": info.designer,
            "vendor_url": info.vendor_url,
            "embedded_license": (info.license_description or "")[:400],
            "embedded_license_url": info.license_url,
            "readability_method": (
                "x-height比・ウェイト・字幅・装飾性から算出したKairoの推定値です"
                "（実測の可読性テスト結果ではありません）"
            ),
            "impression": {
                "luxury": profile["luxury"],
                "casual": profile["casual"],
                "cinematic": profile["cinematic"],
                "impact": profile["impact"],
                "friendliness": profile["friendliness"],
                "authority": profile["authority"],
                "classification": profile["classification"],
                "method": profile["method"],
            },
            "use_cases": profile["use_cases"],
        },
    }


def _upsert(
    db,
    *,
    path: str,
    name: str,
    info: fontfile.FontInfo,
    is_system: bool,
    source: str,
    source_url: str,
    license_id: str,
    license_file: str = "",
    file_size: int = 0,
    file_path: Path | None = None,
) -> tuple[LibraryAsset, bool]:
    # `path` is the identity key (LIBRARY_ROOT-relative for Kairo's own
    # fonts, absolute for system ones); `file_path` is where the bytes
    # actually are. They differ for library fonts, and rasterising the
    # identity key silently measured nothing at all.
    described = _describe(info, file_path or Path(path))
    lic = licenses.get(license_id)

    row = (
        db.query(LibraryAsset)
        .filter(LibraryAsset.kind == "font", LibraryAsset.path == path)
        .one_or_none()
    )
    created = row is None
    if row is None:
        row = LibraryAsset(kind="font", path=path)
        db.add(row)

    row.name = name
    row.family = described["family"]
    row.is_system = is_system
    row.available = True
    row.file_size = file_size
    row.source = source
    row.source_url = source_url
    row.license_id = lic.id
    row.license_name = lic.name
    row.license_url = lic.url
    row.license_status = lic.status
    row.attribution_required = lic.attribution_required
    row.commercial_use = lic.commercial_use
    row.license_file = license_file
    row.languages_json = json.dumps(described["languages"])
    row.styles_json = json.dumps(described["tags"])
    row.genres_json = json.dumps(described["genres"])
    row.tags_json = json.dumps(described["tags"])
    row.weight = described["weight"]
    row.readability = described["readability"]
    row.supports_japanese = described["supports_japanese"]
    row.supports_latin = described["supports_latin"]
    profile = described["profile"]
    row.luxury = profile["luxury"]
    row.casual = profile["casual"]
    row.cinematic = profile["cinematic"]
    row.impact = profile["impact"]
    row.friendliness = profile["friendliness"]
    row.authority = profile["authority"]
    row.classification = profile["classification"]
    row.use_cases_json = json.dumps(profile["use_cases"])
    row.category = language_dir(info)
    row.analysis_json = json.dumps(described["analysis"], ensure_ascii=False)
    row.analysis_status = "ok"
    row.analysis_error = ""
    row.updated_at = _now()
    return row, created


def scan(db, *, include_system: bool = True, limit: int | None = None) -> dict:
    """Reads every reachable font into the library. Returns a summary.

    Idempotent: re-running updates rows in place rather than duplicating,
    so this is safe to call on every startup or from a "再スキャン" button.
    """
    ensure_dirs()
    scanned = added = updated = failed = 0
    seen_paths: set[str] = set()

    # Kairo's own library first, so a downloaded font wins the (kind, path)
    # identity over a system copy of the same family.
    for file in sorted(FONTS_ROOT.rglob("*")):
        if file.suffix.lower() not in fontfile.FONT_EXTENSIONS:
            continue
        rel = file.relative_to(LIBRARY_ROOT).as_posix()
        meta = _sidecar(file)
        for index in range(fontfile.face_count(file)):
            info = fontfile.read(file, collection_index=index)
            scanned += 1
            if info is None:
                failed += 1
                continue
            path_key = rel if index == 0 else f"{rel}#{index}"
            seen_paths.add(path_key)
            _row, created = _upsert(
                db,
                path=path_key,
                name=info.full_name or info.family or file.stem,
                info=info,
                is_system=False,
                source=meta.get("source", "Kairo Font Library"),
                source_url=meta.get("source_url", ""),
                license_id=meta.get("license_id", "unknown"),
                license_file=meta.get("license_file", ""),
                file_size=file.stat().st_size,
                file_path=file,
            )
            added += int(created)
            updated += int(not created)

    if include_system:
        for directory in system_font_dirs():
            for file in sorted(directory.glob("*")):
                if file.suffix.lower() not in fontfile.FONT_EXTENSIONS:
                    continue
                if limit and scanned >= limit:
                    break
                for index in range(fontfile.face_count(file)):
                    info = fontfile.read(file, collection_index=index)
                    scanned += 1
                    if info is None:
                        failed += 1
                        continue
                    key = str(file) if index == 0 else f"{file}#{index}"
                    if key in seen_paths:
                        continue
                    seen_paths.add(key)
                    _row, created = _upsert(
                        db,
                        path=key,
                        name=info.full_name or info.family or file.stem,
                        info=info,
                        is_system=True,
                        source=f"{platform.system()} 同梱フォント",
                        source_url="",
                        license_id="system-bundled",
                        file_size=file.stat().st_size,
                        file_path=file,
                    )
                    added += int(created)
                    updated += int(not created)

    db.commit()

    # Mark anything that used to be here and is not any more, rather than
    # deleting: a finished production's assets-used record still points at it.
    #
    # Scoped to what this pass actually looked at. A library-only scan
    # (include_system=False) has no evidence about the OS's fonts, and
    # marking all 400+ of them unavailable because it did not walk their
    # directory would take the caption font out of every production.
    missing = 0
    sweep = db.query(LibraryAsset).filter(LibraryAsset.kind == "font")
    if not include_system:
        sweep = sweep.filter(LibraryAsset.is_system.is_(False))
    for row in sweep.all():
        if row.path in seen_paths:
            continue
        if row.available:
            row.available = False
            missing += 1
    db.commit()

    return {
        "scanned": scanned,
        "added": added,
        "updated": updated,
        "failed": failed,
        "missing": missing,
        "library_root": str(FONTS_ROOT),
    }


def _sidecar(font_path: Path) -> dict:
    """Reads the `<font>.kairo.json` licence record written at download time.

    Without one, the font's licence is unknown - which is a real answer, and
    keeps the font out of automatic selection until someone says what it is.
    """
    sidecar = font_path.with_suffix(font_path.suffix + ".kairo.json")
    if not sidecar.exists():
        sidecar = font_path.parent / "kairo-license.json"
    if not sidecar.exists():
        return {}
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}
