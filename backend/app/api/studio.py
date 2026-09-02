"""HTTP surface for the AI production studio.

Three groups of endpoints, matching the three things a client needs to do:
drive a production run, watch what it is doing, and talk to it.

The event feed supports long-polling (`wait=true`): the pipeline notifies
`events` on every emit, so a client gets a phase change within milliseconds
instead of on its next poll tick, without holding a WebSocket open.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_project_or_404
from app.core.db import get_db
from app.models.studio import ChangeProposal, ChatMessage, ProductionRun
from app.services import job_manager, settings_service
from app.services.studio import (
    cocreation_service,
    events,
    model_service,
    planning_service,
    quality_service,
    run_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["studio"])


# ------------------------------------------------------------- requests


class StartRunRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=4000)
    # Seconds, not minutes: short-form is the target and "0.75 minutes" is
    # a worse thing to ask a UI to express than "45 seconds".
    target_duration_seconds: float = Field(default=60.0, gt=3, le=1800)
    orientation: str = "vertical"
    mode: str = "full_auto"


class ChatRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=2000)


class LoadModelRequest(BaseModel):
    model_id: str


# ------------------------------------------------------------------ runs


@router.get("/studio/phases")
def list_phases():
    return {"phases": run_service.phase_list()}


@router.get("/studio/quick-actions")
def quick_actions():
    return {"actions": cocreation_service.QUICK_ACTIONS}


@router.post("/projects/{project_id}/studio/start")
async def start_run(project_id: str, payload: StartRunRequest, db: Session = Depends(get_db)):
    project = get_project_or_404(db, project_id)

    # The project's frame is part of the brief, so it is applied up front
    # rather than left for the render to discover.
    width, height = _frame_for(payload.orientation, project.width, project.height)
    if (project.width, project.height) != (width, height):
        project.width, project.height = width, height
        db.commit()

    try:
        run = run_service.create_run(
            db,
            project_id,
            instruction=payload.instruction,
            target_duration_seconds=payload.target_duration_seconds,
            orientation=payload.orientation,
            mode=payload.mode,
        )
    except run_service.RunError as exc:
        raise HTTPException(409, str(exc)) from exc

    job_manager.enqueue_studio_run(run.id)
    return run_service.to_dict(db, run)


def _frame_for(orientation: str, current_w: int, current_h: int) -> tuple[int, int]:
    if orientation == "vertical":
        return 1080, 1920
    if orientation == "horizontal":
        return 1920, 1080
    if orientation == "square":
        return 1080, 1080
    return current_w, current_h


@router.get("/projects/{project_id}/studio/run")
def get_run(project_id: str, db: Session = Depends(get_db)):
    get_project_or_404(db, project_id)
    run = run_service.active_run(db, project_id) or run_service.latest_run(db, project_id)
    return {"run": run_service.to_dict(db, run), "phases": run_service.phase_list()}


def _get_run_or_404(db: Session, run_id: str) -> ProductionRun:
    run = db.get(ProductionRun, run_id)
    if run is None:
        raise HTTPException(404, "Production run not found")
    return run


@router.post("/runs/{run_id}/pause")
def pause_run(run_id: str, db: Session = Depends(get_db)):
    run = _get_run_or_404(db, run_id)
    try:
        run_service.pause(db, run)
    except run_service.RunError as exc:
        raise HTTPException(409, str(exc)) from exc
    return run_service.to_dict(db, run)


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: str, db: Session = Depends(get_db)):
    run = _get_run_or_404(db, run_id)
    try:
        run_service.resume(db, run)
    except run_service.RunError as exc:
        raise HTTPException(409, str(exc)) from exc
    return run_service.to_dict(db, run)


@router.post("/runs/{run_id}/stop")
def stop_run(run_id: str, db: Session = Depends(get_db)):
    run = _get_run_or_404(db, run_id)
    run_service.stop(db, run)
    return run_service.to_dict(db, run)


@router.get("/runs/{run_id}/events")
def get_events(run_id: str, after_seq: int = 0, wait: bool = False, db: Session = Depends(get_db)):
    _get_run_or_404(db, run_id)
    rows = (
        events.wait_for_new(run_id, after_seq, timeout=20.0)
        if wait
        else events.since(run_id, after_seq)
    )
    return {"events": [events.to_dict(e) for e in rows]}


# ---------------------------------------------------------------- models


@router.get("/ai/model-plan")
def model_plan():
    """The "今回使用するAI" table, resolved live (section 9)."""
    settings = settings_service.get_settings()
    plan = model_service.build_plan(want_narration=settings.tts.mode != "off")
    return plan.to_dict()


@router.post("/ai/models/load")
def load_model(payload: LoadModelRequest):
    ok, detail = model_service.load_model(payload.model_id)
    if not ok:
        raise HTTPException(502, detail)
    return {"ok": True, "detail": detail}


@router.get("/ai/models/download-instructions")
def download_instructions(model_id: str):
    return model_service.download_instructions(model_id)


# ------------------------------------------------------------- quality


@router.get("/projects/{project_id}/quality")
def get_quality(project_id: str, db: Session = Depends(get_db)):
    get_project_or_404(db, project_id)
    run = run_service.latest_run(db, project_id)
    if run is None or not run.quality_json:
        return {"report": None, "improvement": None}
    return {
        "report": run_service.load_json(run.quality_json),
        "improvement": run_service.load_json(run.improvement_json),
    }


@router.post("/projects/{project_id}/quality/check")
def run_quality_check(project_id: str, db: Session = Depends(get_db)):
    """Re-runs the check on demand - after manual edits, for example, where
    no production run is in flight to do it automatically."""
    get_project_or_404(db, project_id)
    run = run_service.latest_run(db, project_id)
    strategy = planning_service.strategy_from_json(run.strategy_json if run else None)
    scenes = planning_service.ordered_scenes(db, project_id)
    if not scenes:
        raise HTTPException(400, "チェック対象のシーンがありません。")

    from app.models.media_asset import MediaAsset

    has_bgm = (
        db.query(MediaAsset)
        .filter(MediaAsset.project_id == project_id, MediaAsset.kind == "audio")
        .count()
        > 0
    )
    has_narration = any(s.narration_duration for s in scenes)
    target = run.target_duration_seconds if run else sum(s.estimated_duration for s in scenes)

    report = quality_service.check(
        scenes,
        strategy,
        target_seconds=target,
        has_narration=has_narration,
        has_bgm=has_bgm,
    )
    if run is not None:
        run.quality_json = quality_service.report_to_json(report)
        db.commit()
    return {"report": report.model_dump()}


# -------------------------------------------------------- co-creation


@router.get("/projects/{project_id}/chat")
def get_chat(project_id: str, db: Session = Depends(get_db)):
    get_project_or_404(db, project_id)
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.project_id == project_id)
        .order_by(ChatMessage.created_at)
        .limit(200)
        .all()
    )
    proposals = {
        p.id: p
        for p in db.query(ChangeProposal)
        .filter(ChangeProposal.project_id == project_id)
        .all()
    }
    return {
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "proposal": _proposal_dict(proposals.get(m.proposal_id))
                if m.proposal_id
                else None,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ]
    }


def _proposal_dict(proposal: ChangeProposal | None) -> dict | None:
    if proposal is None:
        return None
    import json

    return {
        "id": proposal.id,
        "summary": proposal.summary,
        "reason": proposal.reason,
        "status": proposal.status,
        "preview": json.loads(proposal.preview_json or "[]"),
        "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
    }


@router.post("/projects/{project_id}/chat")
def post_chat(project_id: str, payload: ChatRequest, db: Session = Depends(get_db)):
    project = get_project_or_404(db, project_id)
    run = run_service.latest_run(db, project_id)
    strategy = planning_service.strategy_from_json(run.strategy_json if run else None)
    try:
        proposal = cocreation_service.propose(
            db, project, strategy, payload.instruction, run.id if run else None
        )
    except cocreation_service.CoCreationError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - reported to the chat UI
        logger.exception("Co-creation proposal failed")
        raise HTTPException(502, f"AIに接続できませんでした: {exc}") from exc

    latest = (
        db.query(ChatMessage)
        .filter(ChatMessage.project_id == project_id, ChatMessage.role == "assistant")
        .order_by(ChatMessage.created_at.desc())
        .first()
    )
    return {
        "reply": latest.content if latest else proposal.summary,
        "proposal": _proposal_dict(proposal) if proposal.status == "pending" else None,
    }


def _get_proposal_or_404(db: Session, proposal_id: str) -> ChangeProposal:
    proposal = db.get(ChangeProposal, proposal_id)
    if proposal is None:
        raise HTTPException(404, "Proposal not found")
    return proposal


@router.post("/proposals/{proposal_id}/apply")
def apply_proposal(proposal_id: str, db: Session = Depends(get_db)):
    proposal = _get_proposal_or_404(db, proposal_id)
    project = get_project_or_404(db, proposal.project_id)
    run = run_service.latest_run(db, proposal.project_id)
    strategy = planning_service.strategy_from_json(run.strategy_json if run else None)
    try:
        result = cocreation_service.apply(db, project, proposal, strategy)
    except cocreation_service.CoCreationError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Applying proposal %s failed", proposal_id)
        proposal.status = "failed"
        proposal.error = str(exc)
        db.commit()
        raise HTTPException(500, f"変更の適用に失敗しました: {exc}") from exc
    return {"result": result, "proposal": _proposal_dict(proposal)}


@router.post("/proposals/{proposal_id}/cancel")
def cancel_proposal(proposal_id: str, db: Session = Depends(get_db)):
    proposal = _get_proposal_or_404(db, proposal_id)
    if proposal.status == "pending":
        proposal.status = "cancelled"
        db.commit()
    return _proposal_dict(proposal)


@router.post("/proposals/{proposal_id}/undo")
def undo_proposal(proposal_id: str, db: Session = Depends(get_db)):
    proposal = _get_proposal_or_404(db, proposal_id)
    project = get_project_or_404(db, proposal.project_id)
    run = run_service.latest_run(db, proposal.project_id)
    strategy = planning_service.strategy_from_json(run.strategy_json if run else None)
    try:
        result = cocreation_service.undo(db, project, proposal, strategy)
    except cocreation_service.CoCreationError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"result": result, "proposal": _proposal_dict(proposal)}
