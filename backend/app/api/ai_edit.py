from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_project_or_404
from app.core.config import LLM_BASE_URL
from app.core.db import get_db
from app.schemas.schemas import JobOut
from app.services import ai_diagnostics, job_manager, llm_client

router = APIRouter(prefix="/api", tags=["ai-edit"])


class AIEditRequest(BaseModel):
    instruction: str


class LLMStatus(BaseModel):
    available: bool  # server reachable + API ok (kept for back-compat)
    base_url: str
    model: str | None
    server_reachable: bool
    api_ok: bool
    models_loaded: list[str]
    configured_model_loaded: bool
    can_generate: bool  # loose gate: "connectable + some model loaded"
    model_source: str  # "env" | "user" | "auto" | "fallback" | "none"
    resolution_reason: str
    error_code: str
    ready: bool  # strict gate: "the resolved model specifically will work"
    diagnosis: dict | None = None  # populated (cause + how to fix it) when not ready


@router.get("/llm/status", response_model=LLMStatus)
def llm_status():
    status = llm_client.get_status()

    diagnosis = None
    if not status.ready:
        context = ai_diagnostics.AIContext(
            provider="LM Studio",
            model=status.configured_model or "(未解決)",
            task="モデル状態確認",
            operation="Preflight Check",
            endpoint=LLM_BASE_URL,
            model_status="loaded" if status.can_generate else (
                "not_loaded" if status.api_ok else "unreachable"
            ),
            requested_model=status.configured_model or "",
            model_source=status.model_source,
            models_loaded=status.models_loaded,
            connection_status="OK" if status.server_reachable else "NG",
            error_code=status.error_code,
        )
        diagnosis = ai_diagnostics.diagnose_llm_status(status, context=context).to_dict()

    return LLMStatus(
        available=status.server_reachable and status.api_ok,
        base_url=LLM_BASE_URL,
        model=status.configured_model,
        server_reachable=status.server_reachable,
        api_ok=status.api_ok,
        models_loaded=status.models_loaded,
        configured_model_loaded=status.configured_model_loaded,
        can_generate=status.can_generate,
        model_source=status.model_source,
        resolution_reason=status.resolution_reason,
        error_code=status.error_code,
        ready=status.ready,
        diagnosis=diagnosis,
    )


@router.post("/projects/{project_id}/ai-edit", response_model=JobOut)
async def ai_edit(project_id: str, payload: AIEditRequest, db: Session = Depends(get_db)):
    get_project_or_404(db, project_id)
    return job_manager.enqueue_ai_edit_job(db, project_id, payload.instruction)
