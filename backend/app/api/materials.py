"""HTTP surface for user-supplied material.

Kept separate from `media.py` on purpose. That router is the editor's media
bin - one file in, one row out. This one is the production studio's
material area, and it answers a different set of questions: what did the
user upload, what is in it, where will it be used, what is missing, and
what happened when something failed.

Every failure here reports *why* (design requirement 14). An upload that
could not be read comes back with the file name, the cause and what to do
about it, per file, so uploading ten photos and one broken video imports
ten photos and explains the eleventh rather than failing the batch.
"""
from __future__ import annotations

import asyncio
import logging
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_project_or_404
from app.core.config import ALLOWED_IMAGE_EXTENSIONS, ALLOWED_VIDEO_EXTENSIONS
from app.core.db import get_db
from app.schemas.material import MATERIAL_MODE_LABELS
from app.services import job_manager, media_service
from app.services.studio import (
    material_analysis,
    material_plan,
    material_usage,
    run_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["materials"])


class ReevaluateRequest(BaseModel):
    mode: str = "ai_auto"
    selected_asset_ids: list[str] = Field(default_factory=list)
    rerender: bool = True


def _asset_dict(asset, analysis=None) -> dict:
    if analysis is None:
        analysis = material_analysis.load_analysis(asset)
    return {
        "id": asset.id,
        "project_id": asset.project_id,
        "kind": asset.kind,
        "original_filename": asset.original_filename,
        "duration": asset.duration,
        "width": asset.width,
        "height": asset.height,
        "fps": asset.fps,
        "has_audio": asset.has_audio,
        "video_codec": asset.video_codec,
        "audio_codec": asset.audio_codec,
        "origin": asset.origin or "user",
        "origin_detail": asset.origin_detail or "",
        "analysis_status": asset.analysis_status or "pending",
        "analysis_error": asset.analysis_error,
        "analysis": analysis.model_dump() if analysis is not None else None,
        "imported_at": asset.imported_at.isoformat() if asset.imported_at else None,
    }


# ------------------------------------------------------------------ list


@router.get("/projects/{project_id}/materials")
def list_materials(project_id: str, db: Session = Depends(get_db)):
    """The user's own photos and videos, with whatever is known about them.

    Also reports where each one is planned to be used, so the material list
    can show 使用予定 / 未使用 without the client having to join the plan
    against the list itself.
    """
    get_project_or_404(db, project_id)
    assets = media_service.list_user_material(db, project_id)

    run = run_service.latest_run(db, project_id)
    plan = material_plan.from_json(run.material_plan_json) if run else None
    planned: dict[str, dict] = {}
    if plan is not None:
        for assignment in plan.assignments:
            if assignment.origin == "user" and assignment.asset_id:
                planned[assignment.asset_id] = {
                    "scene_number": assignment.scene_number,
                    "start_time": assignment.start_time,
                    "duration": assignment.duration,
                    "reason": assignment.reason,
                }

    return {
        "materials": [
            {**_asset_dict(asset), "planned_use": planned.get(asset.id)} for asset in assets
        ],
        "vision_available": material_analysis.vision_available(),
        "modes": [{"id": k, "label": v} for k, v in MATERIAL_MODE_LABELS.items()],
    }


# ---------------------------------------------------------------- upload


@router.post("/projects/{project_id}/materials")
async def upload_materials(
    project_id: str,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """Imports one or more files, reporting each failure individually."""
    get_project_or_404(db, project_id)

    imported: list[dict] = []
    errors: list[dict] = []
    for upload in files:
        # The material area is for the picture: an audio file here would
        # import successfully and then never appear in the list, which
        # looks exactly like a silent failure. Saying so is better than
        # accepting it into a place that will not show it.
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix and media_service.kind_for_suffix(suffix) == "audio" and suffix not in (
            ALLOWED_IMAGE_EXTENSIONS | ALLOWED_VIDEO_EXTENSIONS
        ):
            errors.append(
                {
                    "filename": upload.filename or "",
                    "message": f"「{upload.filename}」は音声ファイルのため、素材には追加できません。",
                    "cause": "素材として使えるのは写真と動画です。",
                    "hint": "BGMやナレーションとして使う場合は、手動編集画面のメディア読み込みから追加してください。",
                    "raw": "",
                }
            )
            continue
        try:
            asset = await asyncio.to_thread(media_service.import_media, db, project_id, upload)
            imported.append(_asset_dict(asset))
        except media_service.UnsupportedMediaError as exc:
            errors.append({"filename": upload.filename or "", **exc.to_dict()})
        except Exception as exc:  # noqa: BLE001 - reported per file
            logger.exception("Material import failed for %s", upload.filename)
            errors.append(
                {
                    "filename": upload.filename or "",
                    "message": f"「{upload.filename}」の読み込みに失敗しました。",
                    "cause": f"{type(exc).__name__}: {exc}",
                    "hint": "別の形式に変換するか、別のファイルで試してください。",
                    "raw": str(exc),
                }
            )

    if not imported and errors:
        # Nothing at all got in: a 400 with the details, so the client shows
        # the reasons rather than an empty success.
        raise HTTPException(400, {"message": "素材を読み込めませんでした。", "errors": errors})
    return {"imported": imported, "errors": errors}


@router.delete("/materials/{asset_id}")
def delete_material(asset_id: str, db: Session = Depends(get_db)):
    asset = media_service.get_media(db, asset_id)
    if asset is None:
        raise HTTPException(404, "素材が見つかりません。")
    media_service.delete_media(db, asset)
    return {"ok": True}


@router.get("/materials/{asset_id}/thumbnail")
def material_thumbnail(asset_id: str, db: Session = Depends(get_db)):
    asset = media_service.get_media(db, asset_id)
    if asset is None:
        raise HTTPException(404, "素材が見つかりません。")
    path = material_analysis.ensure_thumbnail(asset)
    if path is None:
        raise HTTPException(404, "サムネイルを作成できませんでした。")
    media_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    return FileResponse(path, media_type=media_type)


# -------------------------------------------------------------- analysis


@router.post("/projects/{project_id}/materials/analyze")
async def analyze_materials(project_id: str, force: bool = False, db: Session = Depends(get_db)):
    """Analyses everything the user uploaded.

    Offered explicitly as well as run automatically at production time, so
    the material list can show tags before anything has been started.
    """
    get_project_or_404(db, project_id)
    try:
        await asyncio.to_thread(material_analysis.analyze_project, db, project_id, force=force)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Material analysis failed")
        raise HTTPException(500, f"素材の解析に失敗しました: {exc}") from exc

    assets = media_service.list_user_material(db, project_id)
    return {
        "materials": [_asset_dict(a) for a in assets],
        "vision_available": material_analysis.vision_available(),
        "failed": [
            {"id": a.id, "filename": a.original_filename, "error": a.analysis_error}
            for a in assets
            if a.analysis_status == "failed"
        ],
    }


# ------------------------------------------------------------------ plan


@router.get("/projects/{project_id}/materials/plan")
def get_material_plan(
    project_id: str,
    mode: str = "ai_auto",
    target_seconds: float = 30.0,
    selected: str = "",
    db: Session = Depends(get_db),
):
    """The 素材プラン shown before production starts.

    Returns the real plan when a run has already made one, and an
    explicitly provisional estimate otherwise - the difference is carried
    in the payload's `provisional` flag rather than left for the UI to
    infer.
    """
    get_project_or_404(db, project_id)
    run = run_service.latest_run(db, project_id)
    existing = material_plan.from_json(run.material_plan_json) if run else None
    if existing is not None and not existing.provisional:
        return {"plan": existing.model_dump()}

    selected_ids = [s for s in selected.split(",") if s]
    plan = material_plan.preliminary_plan(
        db,
        project_id,
        mode=mode,
        selected_ids=selected_ids,
        target_seconds=target_seconds,
    )
    return {"plan": plan.model_dump()}


@router.get("/projects/{project_id}/materials/usage")
def get_material_usage(project_id: str, db: Session = Depends(get_db)):
    """Which material ended up where in the finished video."""
    get_project_or_404(db, project_id)
    report = material_usage.build_report(db, project_id)
    return {"usage": report.model_dump()}


# ------------------------------------------------------------- re-evaluate


@router.post("/projects/{project_id}/materials/reevaluate")
async def reevaluate_materials(
    project_id: str, payload: ReevaluateRequest, db: Session = Depends(get_db)
):
    """Re-matches material over the existing scenes and rebuilds what changed.

    Declared async like every other endpoint that enqueues a job: the job
    runner schedules work with `asyncio.create_task`, and a sync endpoint
    runs in a worker thread where there is no running event loop to
    schedule onto.
    """
    get_project_or_404(db, project_id)
    active = run_service.active_run(db, project_id)
    if active is not None and active.status in ("running", "pending", "pausing"):
        raise HTTPException(
            409, "制作の実行中は素材を再評価できません。完了を待つか一時停止してください。"
        )
    from app.services.studio import planning_service

    if not planning_service.ordered_scenes(db, project_id):
        raise HTTPException(
            400, "まだシーンがありません。先に制作を開始してください。"
        )
    job = job_manager.enqueue_material_reeval_job(
        db,
        project_id,
        mode=payload.mode,
        selected_ids=payload.selected_asset_ids,
        rerender=payload.rerender,
    )
    return {
        "job_id": job.id,
        "status": job.status,
        "selected": payload.selected_asset_ids,
    }
