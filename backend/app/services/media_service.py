from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import ALLOWED_MEDIA_EXTENSIONS, ALLOWED_VIDEO_EXTENSIONS
from app.core.paths import assets_dir
from app.models.media_asset import MediaAsset
from app.services.ffmpeg.probe import probe_media

CHUNK_SIZE = 1024 * 1024  # 1 MiB


class UnsupportedMediaError(ValueError):
    pass


def _safe_suffix(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_MEDIA_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_MEDIA_EXTENSIONS))
        raise UnsupportedMediaError(
            f"Unsupported file extension '{suffix}'. Allowed: {allowed}"
        )
    return suffix


def import_media(db: Session, project_id: str, upload: UploadFile) -> MediaAsset:
    suffix = _safe_suffix(upload.filename or "")
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    dest_dir = assets_dir(project_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / stored_name

    with dest_path.open("wb") as out_file:
        while chunk := upload.file.read(CHUNK_SIZE):
            out_file.write(chunk)

    try:
        info = probe_media(dest_path)
    except Exception:
        dest_path.unlink(missing_ok=True)
        raise

    asset = MediaAsset(
        project_id=project_id,
        kind="video" if suffix in ALLOWED_VIDEO_EXTENSIONS else "audio",
        original_filename=upload.filename or stored_name,
        stored_path=f"assets/{stored_name}",
        duration=info.duration,
        width=info.width,
        height=info.height,
        fps=info.fps,
        has_audio=info.has_audio,
        video_codec=info.video_codec,
        audio_codec=info.audio_codec,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def list_media(db: Session, project_id: str) -> list[MediaAsset]:
    return (
        db.query(MediaAsset)
        .filter(MediaAsset.project_id == project_id)
        .order_by(MediaAsset.imported_at.asc())
        .all()
    )


def get_media(db: Session, asset_id: str) -> MediaAsset | None:
    return db.get(MediaAsset, asset_id)
