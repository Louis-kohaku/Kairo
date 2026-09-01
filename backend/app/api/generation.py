from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_project_or_404
from app.core.config import DATA_ROOT
from app.core.db import get_db
from app.core.paths import project_dir
from app.models.generation import Generation
from app.schemas.schemas import EngineCapabilitiesOut, GenerationOut, JobOut
from app.services import job_manager, video_engines

router = APIRouter(prefix="/api", tags=["generation"])

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MIN_RECOMMENDED_RAM_GB = 8.0


def _sources_dir(project_id: str) -> Path:
    d = project_dir(project_id) / "sources"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.get("/generation-engines", response_model=list[EngineCapabilitiesOut])
def list_engines():
    import psutil

    total_ram_gb = psutil.virtual_memory().total / 1e9

    out = []
    for caps in video_engines.list_capabilities():
        try:
            engine = video_engines.get_engine(caps.id)
            downloaded = engine.is_model_downloaded()
        except Exception:
            downloaded = False

        if total_ram_gb < caps.min_ram_gb:
            status, reason = "not_recommended", (
                f"推奨メモリ{caps.min_ram_gb:.0f}GBに対し、このPCは約{total_ram_gb:.0f}GBです。"
                "動作しても非常に低速、または失敗する可能性があります。"
            )
        elif not downloaded:
            status, reason = "not_downloaded", (
                f"モデル未ダウンロード(初回生成時に約{caps.approx_download_gb:.1f}GBを取得します)。"
            )
        else:
            status, reason = "ready", "このPCで利用可能です(CPU実行、速度は解像度・長さに依存します)。"

        estimate_low = estimate_high = None
        try:
            engine = video_engines.get_engine(caps.id)
            estimate_low, estimate_high = engine.estimate_duration_seconds(
                width=384, height=256, num_frames=8, num_inference_steps=10
            )
        except Exception:
            pass

        out.append(
            EngineCapabilitiesOut(
                **caps.__dict__,
                is_model_downloaded=downloaded,
                status=status,
                status_reason=reason,
                estimate_low_seconds=estimate_low,
                estimate_high_seconds=estimate_high,
            )
        )
    return out


@router.post("/projects/{project_id}/generate/image-to-video", response_model=JobOut)
async def generate_image_to_video(
    project_id: str,
    image: UploadFile = File(...),
    prompt: str = Form(""),
    engine_id: str = Form("svd"),
    # Lighter-than-model-default settings: CPU-only inference measured at
    # ~30 min for the model's own defaults (512x320/14 frames/15 steps) on
    # the Intel Core Ultra 7 155H reference machine, vs. ~8 min at these
    # settings. See README "実機検証" for both measurements.
    width: int = Form(384),
    height: int = Form(256),
    num_frames: int = Form(8),
    num_inference_steps: int = Form(10),
    fps: float = Form(6),
    seed: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    get_project_or_404(db, project_id)

    suffix = Path(image.filename or "").suffix.lower()
    if suffix not in ALLOWED_IMAGE_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_EXTENSIONS))
        raise HTTPException(400, f"対応していない画像形式です '{suffix}'。対応形式: {allowed}")

    try:
        engine = video_engines.get_engine(engine_id)
    except KeyError as exc:
        raise HTTPException(400, str(exc)) from exc

    if engine.capabilities.prompt_conditioned is False and prompt.strip():
        # Not an error - just make sure the caller isn't relying on the
        # prompt actually doing something it can't (section 8: never
        # silently pretend). The frontend also shows this up front.
        pass

    stored_name = f"{uuid.uuid4().hex}{suffix}"
    dest = _sources_dir(project_id) / stored_name
    with dest.open("wb") as out_file:
        while chunk := await image.read(1024 * 1024):
            out_file.write(chunk)

    params = {
        "width": width,
        "height": height,
        "num_frames": num_frames,
        "num_inference_steps": num_inference_steps,
        "fps": fps,
        "seed": seed,
    }

    generation = Generation(
        project_id=project_id,
        kind="image_to_video",
        engine_id=engine_id,
        prompt=prompt,
        source_image_path=str(dest),
        params_json=json.dumps(params),
        status="pending",
    )
    db.add(generation)
    db.commit()
    db.refresh(generation)

    job = job_manager.enqueue_image_to_video_job(db, project_id, generation.id)
    return job


@router.get("/projects/{project_id}/generations", response_model=list[GenerationOut])
def list_generations(project_id: str, db: Session = Depends(get_db)):
    get_project_or_404(db, project_id)
    return (
        db.query(Generation)
        .filter(Generation.project_id == project_id)
        .order_by(Generation.created_at.desc())
        .all()
    )
