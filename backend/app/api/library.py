"""HTTP surface for the Creative Asset Library and its licence manager."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.library import LibraryAsset
from app.services import settings_service
from app.services.library import (
    audio_library,
    font_fetch,
    fonts,
    licenses,
    selector,
)
from app.services.trends import genre as genre_module

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/library", tags=["library"])


class ScanRequest(BaseModel):
    include_system: bool = True
    reanalyze: bool = False


class DownloadFontRequest(BaseModel):
    id: str
    max_files: int = Field(default=3, ge=1, le=8)


class SetLicenseRequest(BaseModel):
    license_id: str
    attribution: str = ""


def _to_dict(row: LibraryAsset) -> dict:
    def _load(raw: str | None) -> list:
        try:
            value = json.loads(raw or "[]")
            return value if isinstance(value, list) else []
        except ValueError:
            return []

    return {
        "id": row.id,
        "kind": row.kind,
        "name": row.name,
        "family": row.family,
        "path": row.path,
        "is_system": row.is_system,
        "available": row.available,
        "category": row.category,
        "mood": row.mood,
        "source": row.source,
        "source_url": row.source_url,
        "license": {
            "id": row.license_id,
            "name": row.license_name,
            "url": row.license_url,
            "status": row.license_status,
            "status_label": licenses.status_label(row.license_status),
            "attribution_required": row.attribution_required,
            "attribution": row.attribution_text,
            "commercial_use": row.commercial_use,
            "file": row.license_file,
            "summary": licenses.get(row.license_id).summary,
        },
        "auto_usable": licenses.is_auto_usable(row.license_status),
        "languages": _load(row.languages_json),
        "styles": _load(row.styles_json),
        "genres": _load(row.genres_json),
        "weight": row.weight,
        "readability": row.readability or None,
        "supports_japanese": row.supports_japanese,
        "supports_latin": row.supports_latin,
        "duration": row.duration,
        "bpm": row.bpm,
        "loudness_lufs": row.loudness_lufs,
        "analysis_status": row.analysis_status,
        "analysis_error": row.analysis_error,
        "notes": row.notes,
    }


@router.get("")
def overview(db: Session = Depends(get_db)):
    settings = settings_service.get_settings().library
    return {
        "summary": selector.library_summary(db),
        "roots": {
            "fonts": str(fonts.FONTS_ROOT),
            "music": str(audio_library.MUSIC_ROOT),
            "sfx": str(audio_library.SFX_ROOT),
        },
        "settings": settings.model_dump(),
        "licenses": licenses.catalog(),
        "status_labels": licenses.STATUS_LABELS,
        "sfx_import_only": list(audio_library.SFX_IMPORT_ONLY),
    }


@router.get("/assets")
def list_assets(
    kind: str | None = None,
    status: str | None = None,
    japanese_only: bool = False,
    query: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    q = db.query(LibraryAsset)
    if kind:
        q = q.filter(LibraryAsset.kind == kind)
    if status:
        q = q.filter(LibraryAsset.license_status == status)
    if japanese_only:
        q = q.filter(LibraryAsset.supports_japanese.is_(True))
    if query:
        like = f"%{query}%"
        q = q.filter(LibraryAsset.name.like(like) | LibraryAsset.family.like(like))
    rows = (
        q.order_by(LibraryAsset.kind, LibraryAsset.readability.desc(), LibraryAsset.name)
        .limit(max(1, min(limit, 1000)))
        .all()
    )
    return {"assets": [_to_dict(r) for r in rows], "total": q.count()}


@router.post("/scan")
def scan(payload: ScanRequest | None = None, db: Session = Depends(get_db)):
    payload = payload or ScanRequest()
    font_result = fonts.scan(db, include_system=payload.include_system)
    audio_result = audio_library.scan(db, reanalyze=payload.reanalyze)
    return {"fonts": font_result, "audio": audio_result}


@router.post("/bootstrap")
def bootstrap(force: bool = False, db: Session = Depends(get_db)):
    """Generates Kairo's own licence-clean music/SFX and catalogues everything.

    Safe to call repeatedly; existing files are left alone unless `force`.
    """
    fonts.scan(db)
    return audio_library.bootstrap(db, force=force)


@router.get("/fonts/catalog")
def font_catalog(db: Session = Depends(get_db)):
    return {
        "catalog": font_fetch.catalog(db),
        "note": (
            "Google Fonts公式リポジトリ(google/fonts)からライセンスファイルと"
            "一緒にダウンロードします。ライセンスファイルを取得できないフォントは"
            "ダウンロードしません。"
        ),
    }


@router.post("/fonts/download")
def download_font(payload: DownloadFontRequest, db: Session = Depends(get_db)):
    try:
        result = font_fetch.download(payload.id, max_files=payload.max_files)
    except font_fetch.FontFetchError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Font download failed for %s", payload.id)
        raise HTTPException(502, f"フォントを取得できませんでした: {exc}") from exc
    scan_result = fonts.scan(db, include_system=False)
    return {"downloaded": result, "scan": scan_result}


@router.post("/assets/{asset_id}/license")
def set_license(asset_id: str, payload: SetLicenseRequest, db: Session = Depends(get_db)):
    if payload.license_id not in licenses.LICENSES:
        raise HTTPException(400, f"未知のライセンスIDです: {payload.license_id}")
    row = audio_library.set_license(
        db, asset_id, payload.license_id, attribution=payload.attribution
    )
    if row is None:
        raise HTTPException(404, "素材が見つかりません")
    return _to_dict(row)


@router.get("/preview")
def preview_selection(
    genre: str = "travel",
    mood: str = "bright",
    duration: float = 40.0,
    db: Session = Depends(get_db),
):
    """What the agent would choose for this genre right now, and why.

    Exists so the user can inspect the selection logic without starting a
    production - the same call the pipeline makes, with the same reasons
    attached.
    """
    settings = settings_service.get_settings().library
    profile = genre_module.default_profile(genre)
    font = selector.select_font(
        db, genre=genre, profile=profile, require_commercial=settings.prefer_commercial_safe
    )
    music = selector.select_music(
        db,
        mood=mood,
        duration=duration,
        profile=profile,
        require_commercial=settings.prefer_commercial_safe,
        require_beat=True,
    )
    return {
        "genre": genre,
        "genre_label": genre_module.label(genre),
        "font": font.to_dict(),
        "music": music.to_dict(),
        "profile": profile.model_dump(),
    }
