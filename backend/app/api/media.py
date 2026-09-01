from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_project_or_404
from app.core.db import get_db
from app.core.paths import project_dir
from app.schemas.schemas import MediaAssetOut
from app.services import media_service

router = APIRouter(prefix="/api", tags=["media"])


@router.post("/projects/{project_id}/media", response_model=MediaAssetOut)
def upload_media(
    project_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)
):
    get_project_or_404(db, project_id)
    try:
        return media_service.import_media(db, project_id, file)
    except media_service.UnsupportedMediaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/media", response_model=list[MediaAssetOut])
def list_media(project_id: str, db: Session = Depends(get_db)):
    get_project_or_404(db, project_id)
    return media_service.list_media(db, project_id)


@router.get("/media/{asset_id}/file")
def get_media_file(asset_id: str, db: Session = Depends(get_db)):
    asset = media_service.get_media(db, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Media asset not found")

    path = project_dir(asset.project_id) / asset.stored_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="Media file missing on disk")

    media_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        filename=asset.original_filename,
        content_disposition_type="inline",
    )
