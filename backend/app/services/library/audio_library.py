"""The music and SFX halves of the Creative Asset Library.

Kairo needs music and effects it is allowed to use. There is no free,
key-less API that hands out commercially-usable music, and scraping one
would break the rule this project is built on, so the library is filled from
two sources and neither of them is a guess:

**Kairo's own synthesis.** FFmpeg generates the beds and effects. Nobody
else holds rights in them, so they are `kairo-generated` / `usable` by
construction, and - because Kairo chose the tempo - their beat grid is known
exactly rather than estimated. This is what makes the library non-empty on a
machine that has never been online.

**Files the user imports.** Anything dropped into `library/music/**` or
`library/sfx/**`. These arrive with `license_id="unknown"`, which means they
are catalogued, analysed and visible, and *not* eligible for automatic
selection until someone states their terms. That is the point of rule 13:
the absence of a licence is a fact about the asset, not a formality to skip.

Both kinds are measured the same way (`audio_analysis.py`), so a user's
track and a generated bed are ranked on the same evidence.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import LIBRARY_ROOT
from app.models.library import LibraryAsset
from app.services.ffmpeg import compose
from app.services.library import audio_analysis, licenses

logger = logging.getLogger(__name__)

MUSIC_ROOT = LIBRARY_ROOT / "music"
SFX_ROOT = LIBRARY_ROOT / "sfx"

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}

# The mood folders, mirroring the design brief's layout. Each maps to a
# voicing `compose.synthesize_bgm` knows, so a folder is never an empty
# promise.
MUSIC_CATEGORIES: dict[str, str] = {
    "cinematic": "emotional",
    "travel": "bright",
    "vlog": "gentle",
    "emotional": "emotional",
    "energetic": "energetic",
    "comedy": "playful",
    "ambient": "calm",
    "warm": "warm",
    "modern": "modern",
    "neutral": "neutral",
    "tense": "tense",
}

# Tempos generated per mood. Two each: one that suits a calm cut and one
# that suits a fast one, so Beat Sync has a grid to work with at either
# pace without generating a wall of near-identical files.
_GENERATED_BPMS: dict[str, tuple[float, ...]] = {
    "cinematic": (80.0, 100.0),
    "travel": (100.0, 122.0),
    "vlog": (90.0, 108.0),
    "emotional": (76.0, 92.0),
    "energetic": (124.0, 140.0),
    "comedy": (112.0, 132.0),
    "ambient": (0.0,),  # a pad with no pulse - the honest shape for ambience
    "warm": (96.0, 112.0),
    "modern": (104.0, 120.0),
    "neutral": (92.0, 108.0),
    "tense": (86.0, 104.0),
}

GENERATED_SECONDS = 45.0

# The SFX folders, and which of `compose`'s recipes fills each. `nature`,
# `water` and `ambient` have no synthesised recipe that would honestly be
# called that, so they exist as import targets only and are documented as
# such rather than being filled with a sine wave labelled "wave".
SFX_CATEGORIES: dict[str, str] = {
    "whoosh": "whoosh",
    "hit": "thud",
    "pop": "pop",
    "click": "pop",
    "transition": "whoosh",
    "cinematic": "ding",
    "sparkle": "sparkle",
    "surprise": "surprise",
}
SFX_IMPORT_ONLY = ("nature", "water", "ambient")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_dirs() -> None:
    for name in MUSIC_CATEGORIES:
        (MUSIC_ROOT / name).mkdir(parents=True, exist_ok=True)
    for name in list(SFX_CATEGORIES) + list(SFX_IMPORT_ONLY):
        (SFX_ROOT / name).mkdir(parents=True, exist_ok=True)


def _rel(path: Path) -> str:
    return path.relative_to(LIBRARY_ROOT).as_posix()


def _sidecar_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".kairo.json")


def read_sidecar(path: Path) -> dict:
    sidecar = _sidecar_path(path)
    if not sidecar.exists():
        return {}
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_sidecar(path: Path, data: dict) -> None:
    _sidecar_path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ------------------------------------------------------------- generation


def generate_builtin_music(*, force: bool = False, on_progress=None) -> list[Path]:
    """Writes Kairo's own music beds to disk. Idempotent."""
    ensure_dirs()
    written: list[Path] = []
    for category, mood in MUSIC_CATEGORIES.items():
        for bpm in _GENERATED_BPMS.get(category, (0.0,)):
            name = (
                f"kairo_{category}_{int(bpm)}bpm.m4a" if bpm else f"kairo_{category}_pad.m4a"
            )
            dest = MUSIC_ROOT / category / name
            if dest.exists() and not force:
                continue
            if on_progress:
                on_progress(f"BGMを生成しています: {category} {int(bpm) or '-'}BPM")
            try:
                compose.synthesize_bgm(
                    dest, GENERATED_SECONDS, mood=mood, bpm=bpm or None
                )
            except Exception:
                logger.exception("Failed to generate library BGM %s", dest)
                continue
            write_sidecar(
                dest,
                {
                    "title": f"Kairo {category} bed" + (f" {int(bpm)}BPM" if bpm else " (pad)"),
                    "artist": "Kairo (FFmpeg synthesis)",
                    "license_id": "kairo-generated",
                    "source": "Kairo内蔵シンセ (FFmpeg lavfi)",
                    "source_url": "",
                    "mood": mood,
                    "category": category,
                    # Not a detection result: this is the tempo the file was
                    # generated at, which is why Beat Sync can trust it.
                    "declared_bpm": bpm or None,
                },
            )
            written.append(dest)
    return written


def generate_builtin_sfx(*, force: bool = False) -> list[Path]:
    ensure_dirs()
    written: list[Path] = []
    for category, recipe in SFX_CATEGORIES.items():
        dest = SFX_ROOT / category / f"kairo_{category}.m4a"
        if dest.exists() and not force:
            continue
        try:
            compose.synthesize_sfx(dest, recipe)
        except Exception:
            logger.exception("Failed to generate library SFX %s", dest)
            continue
        write_sidecar(
            dest,
            {
                "title": f"Kairo {category}",
                "artist": "Kairo (FFmpeg synthesis)",
                "license_id": "kairo-generated",
                "source": "Kairo内蔵シンセ (FFmpeg lavfi)",
                "category": category,
            },
        )
        written.append(dest)
    return written


# ---------------------------------------------------------------- scanning


def _upsert(db, kind: str, path: Path, meta: dict, analysis: audio_analysis.AudioAnalysis):
    rel = _rel(path)
    lic = licenses.get(meta.get("license_id", "unknown"))
    row = (
        db.query(LibraryAsset)
        .filter(LibraryAsset.kind == kind, LibraryAsset.path == rel)
        .one_or_none()
    )
    created = row is None
    if row is None:
        row = LibraryAsset(kind=kind, path=rel)
        db.add(row)

    category = meta.get("category") or path.parent.name
    row.name = meta.get("title") or path.stem
    row.family = meta.get("artist", "")
    row.is_system = False
    row.available = True
    row.file_size = path.stat().st_size
    row.source = meta.get("source", "")
    row.source_url = meta.get("source_url", "")
    row.license_id = lic.id
    row.license_name = lic.name
    row.license_url = meta.get("license_url") or lic.url
    row.license_status = lic.status
    row.attribution_required = lic.attribution_required
    row.attribution_text = meta.get("attribution", "")
    row.commercial_use = lic.commercial_use
    row.license_file = meta.get("license_file", "")
    row.category = category
    row.mood = meta.get("mood", "") or MUSIC_CATEGORIES.get(category, "")
    row.tags_json = json.dumps(meta.get("tags", []), ensure_ascii=False)
    row.genres_json = json.dumps(meta.get("genres", []), ensure_ascii=False)
    row.duration = analysis.duration or None
    # A declared tempo (Kairo generated the file at it) beats a detected
    # one; for imported files there is only the detection.
    declared = meta.get("declared_bpm")
    row.bpm = float(declared) if declared else analysis.bpm
    row.loudness_lufs = analysis.loudness_lufs
    payload = analysis.to_dict()
    payload["declared_bpm"] = declared
    row.analysis_json = json.dumps(payload, ensure_ascii=False)
    row.analysis_status = "failed" if analysis.error else "ok"
    row.analysis_error = analysis.error
    row.notes = meta.get("note", "")
    row.updated_at = _now()
    return row, created


def scan(db, *, kinds: tuple[str, ...] = ("music", "sfx"), reanalyze: bool = False) -> dict:
    """Catalogues and measures everything in the music/SFX trees."""
    ensure_dirs()
    summary = {"scanned": 0, "added": 0, "updated": 0, "failed": 0, "skipped": 0}
    seen: dict[str, set[str]] = {"music": set(), "sfx": set()}

    for kind, root in (("music", MUSIC_ROOT), ("sfx", SFX_ROOT)):
        if kind not in kinds:
            continue
        for file in sorted(root.rglob("*")):
            if file.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            rel = _rel(file)
            seen[kind].add(rel)
            summary["scanned"] += 1

            existing = (
                db.query(LibraryAsset)
                .filter(LibraryAsset.kind == kind, LibraryAsset.path == rel)
                .one_or_none()
            )
            # Analysis decodes the whole file, so it is not repeated for a
            # row that already has a result unless asked.
            if existing is not None and existing.analysis_status == "ok" and not reanalyze:
                existing.available = True
                existing.updated_at = _now()
                summary["skipped"] += 1
                continue

            meta = read_sidecar(file)
            analysis = audio_analysis.analyze(file)
            _row, created = _upsert(db, kind, file, meta, analysis)
            summary["added" if created else "updated"] += 1
            if analysis.error:
                summary["failed"] += 1

    db.commit()

    missing = 0
    for kind in kinds:
        for row in db.query(LibraryAsset).filter(LibraryAsset.kind == kind).all():
            if row.path in seen.get(kind, set()):
                continue
            if row.available:
                row.available = False
                missing += 1
    db.commit()
    summary["missing"] = missing
    summary["music_root"] = str(MUSIC_ROOT)
    summary["sfx_root"] = str(SFX_ROOT)
    return summary


def bootstrap(db, *, force: bool = False, on_progress=None) -> dict:
    """Generates Kairo's own assets if absent, then scans everything.

    Called from the library API and from the production pipeline's first
    use, so a fresh install has a usable, licence-clean library without the
    user doing anything.
    """
    music = generate_builtin_music(force=force, on_progress=on_progress)
    sfx = generate_builtin_sfx(force=force)
    result = scan(db, reanalyze=force)
    result["generated_music"] = len(music)
    result["generated_sfx"] = len(sfx)
    return result


def set_license(db, asset_id: str, license_id: str, *, attribution: str = "") -> LibraryAsset | None:
    """Records the licence a user has established for an imported asset.

    Also written back to the sidecar on disk, so the declaration survives a
    database reset and a re-scan does not silently drop it back to unknown.
    """
    row = db.get(LibraryAsset, asset_id)
    if row is None:
        return None
    lic = licenses.get(license_id)
    row.license_id = lic.id
    row.license_name = lic.name
    row.license_url = lic.url
    row.license_status = lic.status
    row.attribution_required = lic.attribution_required
    row.commercial_use = lic.commercial_use
    row.attribution_text = attribution
    row.updated_at = _now()
    db.commit()

    if not row.is_system:
        path = LIBRARY_ROOT / row.path
        if path.exists():
            meta = read_sidecar(path)
            meta.update(
                {
                    "license_id": lic.id,
                    "attribution": attribution,
                    "declared_by": "user",
                    "declared_at": _now().isoformat(),
                }
            )
            try:
                write_sidecar(path, meta)
            except OSError:
                logger.exception("Could not write licence sidecar for %s", path)
    return row
