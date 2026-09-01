from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_project_or_404
from app.core.config import LLM_BASE_URL, LLM_MODEL
from app.core.db import get_db
from app.schemas.schemas import JobOut
from app.services import job_manager, llm_client

router = APIRouter(prefix="/api", tags=["ai-edit"])


class AIEditRequest(BaseModel):
    instruction: str


class LLMStatus(BaseModel):
    available: bool  # server reachable + API ok (kept for back-compat)
    base_url: str
    model: str
    server_reachable: bool
    api_ok: bool
    models_loaded: list[str]
    configured_model_loaded: bool
    can_generate: bool  # the real gate: "connectable" != "can actually generate"


@router.get("/llm/status", response_model=LLMStatus)
def llm_status():
    status = llm_client.get_status()
    return LLMStatus(
        available=status.server_reachable and status.api_ok,
        base_url=LLM_BASE_URL,
        model=LLM_MODEL,
        server_reachable=status.server_reachable,
        api_ok=status.api_ok,
        models_loaded=status.models_loaded,
        configured_model_loaded=status.configured_model_loaded,
        can_generate=status.can_generate,
    )


@router.post("/projects/{project_id}/ai-edit", response_model=JobOut)
async def ai_edit(project_id: str, payload: AIEditRequest, db: Session = Depends(get_db)):
    get_project_or_404(db, project_id)
    return job_manager.enqueue_ai_edit_job(db, project_id, payload.instruction)
