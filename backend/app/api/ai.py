"""AI model management endpoints (design doc sections 3-20): what LM Studio
currently has available, what Kairo recommends for this PC, and how long
generation is expected to take.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.core.config import LLM_BASE_URL
from app.schemas.ai import (
    EstimateOut,
    ModelInfo,
    ModelsListOut,
    ParallelismWarningOut,
    RecommendationOut,
    SetupCandidate,
    TTSVoicesOut,
    VideoSettingWarningOut,
)
from app.services import (
    ai_diagnostics,
    ai_recommendation_service,
    llm_client,
    model_catalog,
    time_estimate_service,
    tts_service,
)

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/models", response_model=ModelsListOut)
def list_models():
    status = llm_client.get_status()

    if not status.server_reachable or not status.api_ok:
        context = ai_diagnostics.AIContext(
            provider="LM Studio",
            model=status.configured_model or "",
            task="モデル一覧取得",
            operation="GET /v1/models",
            endpoint=LLM_BASE_URL,
            model_status="unreachable" if not status.server_reachable else "not_loaded",
            requested_model=status.configured_model or "",
            model_source=status.model_source,
            models_loaded=status.models_loaded,
            connection_status="OK" if status.server_reachable else "NG",
            error_code=status.error_code,
        )
        diagnosis = ai_diagnostics.diagnose_llm_status(status, context=context).to_dict()
        return ModelsListOut(connected=False, base_url=LLM_BASE_URL, diagnosis=diagnosis)

    models = []
    for model_id in status.models_loaded:
        entry = model_catalog.find_match(model_id)
        models.append(
            ModelInfo(
                id=model_id,
                loaded=True,
                recommended=entry is not None,
                catalog_tier_label=entry.tier_label if entry else None,
                is_current=model_id == status.configured_model,
            )
        )

    return ModelsListOut(
        connected=True,
        base_url=LLM_BASE_URL,
        models=models,
        current_model=status.configured_model,
        current_model_source=status.model_source,
    )


@router.get("/recommendation", response_model=RecommendationOut)
def get_recommendation():
    status = llm_client.get_status()
    rec = ai_recommendation_service.recommend_model(status.models_loaded)
    candidates = ai_recommendation_service.build_setup_candidates(status.models_loaded)
    return RecommendationOut(
        ram_gb=rec["ram_gb"],
        gpu_names=rec["gpu_names"],
        gpu_dedicated=rec["gpu_dedicated"],
        recommended_tier_label=rec["recommended_tier_label"],
        reasons=rec["reasons"],
        recommended_model_id=rec.get("recommended_model_id"),
        recommended_model_source=rec["recommended_model_source"],
        setup_candidates=[SetupCandidate(**c) for c in candidates],
    )


@router.get("/video-setting-check", response_model=VideoSettingWarningOut)
def check_video_setting(width: int, height: int, fps: float):
    return VideoSettingWarningOut(**ai_recommendation_service.assess_video_setting(width, height, fps))


@router.get("/estimate", response_model=EstimateOut)
def get_estimate(
    duration_seconds: float = 60.0,
    quality_preset: str = "standard",
    engine_id: str = "svd",
):
    return EstimateOut(
        **time_estimate_service.estimate_total(duration_seconds, quality_preset, engine_id)
    )


@router.get("/parallelism-check", response_model=ParallelismWarningOut)
def check_parallelism(value: int):
    return ParallelismWarningOut(**ai_recommendation_service.assess_parallelism(value))


@router.get("/tts-voices", response_model=TTSVoicesOut)
def list_tts_voices():
    if not tts_service.is_supported_platform():
        return TTSVoicesOut(available=False, voices=[], note="このOSではTTS(音声合成)に対応していません(Windowsのみ対応)。")
    voices = tts_service.list_voices()
    if not voices:
        return TTSVoicesOut(
            available=False,
            voices=[],
            note="現在利用可能なTTSエンジンがありません。Windowsの「設定 > 時刻と言語 > 音声認識」から音声を追加してください。",
        )
    return TTSVoicesOut(available=True, voices=[v.__dict__ for v in voices], note=f"{len(voices)}件の音声が利用可能です。")


class TTSPreviewRequest(BaseModel):
    text: str
    voice_id: str | None = None


@router.post("/tts-preview")
def tts_preview(payload: TTSPreviewRequest):
    with tempfile.TemporaryDirectory(prefix="kairo_tts_preview_") as tmp:
        dest = Path(tmp) / "preview.wav"
        try:
            tts_service.synthesize_to_wav(payload.text, payload.voice_id, dest)
        except tts_service.TTSError as exc:
            raise HTTPException(400, str(exc)) from exc
        audio_bytes = dest.read_bytes()
    return Response(content=audio_bytes, media_type="audio/wav")
