"""The AI production orchestrator (design doc sections 4/6/7): turns one
natural-language topic into a chaptered, scene-level script + storyboard.

Deliberately scoped to Phase 4: this only plans (Planning Agent -> Script
Agent -> Storyboard Agent -> Scene rows). It never touches ffmpeg or
generates media - that starts in Phase 5, once each Scene's visual_type
has a real generator behind it. Every chapter is scripted with its own LLM
call so a long video is never planned in a single shot, matching section 6
("do not generate a long video in one pass").
"""
from __future__ import annotations

import json
import logging
import time

from pydantic import ValidationError

from app.core.config import LLM_BASE_URL
from app.core.db import SessionLocal
from app.core.paths import project_dir
from app.models.job import Job
from app.models.production import Chapter, ProductionSpec, Scene
from app.models.project import Project
from app.schemas.production import ChapterScript, PlanOutline
from app.services import ai_diagnostics, job_log, llm_client, llm_preflight, time_estimate_service
from app.services.json_extract import JSONExtractionError, parse_json_object

logger = logging.getLogger(__name__)

# Steps that actually exist today. Kairo's production pipeline is
# deliberately scoped to planning + scripting (see module docstring) - it
# never generates media - so the step checklist a client renders must only
# ever claim these two ran, never later phases that have no implementation.
STEP_LABELS = {
    "planning": "企画生成",
    "scene_generation": "台本・シーン生成",
}


class ProductionError(RuntimeError):
    pass


def _update_job(db, job_id: str, **fields) -> None:
    """Updates the Job row on the SAME session `run_production` uses for
    everything else. A separate session here would try to write to SQLite
    while this function's caller may still hold an uncommitted transaction
    open, which deadlocks as "database is locked" - there is only one
    writer at a time.
    """
    job = db.get(Job, job_id)
    if job is None:
        return
    for key, value in fields.items():
        setattr(job, key, value)
    db.commit()


def _build_plan_prompt(instruction: str, target_duration_minutes: float) -> list[dict]:
    system = (
        "あなたはYouTube向け動画のプランナーです。ユーザーの依頼から動画の企画を"
        "JSONで出力してください。他の文章は一切出力せず、JSONオブジェクトのみを返してください。\n\n"
        "出力形式:\n"
        '{"title": "...", "target_audience": "...", "tone": "...", '
        '"chapters": [{"title": "...", "summary": "..."}, ...]}\n\n'
        "章の数は動画の長さに応じて適切に決めてください(目安: 3〜8章)。"
    )
    user = f"{instruction}\n\n動画の目標時間: 約{target_duration_minutes}分"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _build_chapter_script_prompt(
    plan: PlanOutline, chapter_title: str, chapter_summary: str, target_seconds: float
) -> list[dict]:
    visual_types = (
        "ai_video, ai_image, photo, diagram, chart, map, text_animation, "
        "existing_video, existing_image, screen_recording"
    )
    system = (
        "あなたは動画脚本家です。与えられた章について、ナレーション台本とビジュアル構成を"
        "シーン単位でJSONで出力してください。他の文章は一切出力せず、JSONオブジェクトのみを返してください。\n\n"
        "出力形式:\n"
        '{"scenes": [{"narration": "...", "visual_type": "<type>", '
        '"visual_prompt": "...", "estimated_duration": 5.0}, ...]}\n\n'
        f"visual_typeは次のいずれかにしてください: {visual_types}\n"
        "動画生成だけに頼らず、内容に応じて図解・チャート・地図・テキストアニメーションなども"
        "積極的に活用してください。\n"
        "各シーンのナレーションは1〜3文程度にし、この章の合計時間がおよそ"
        f"{target_seconds:.0f}秒になるようシーン数を調整してください。"
    )
    user = (
        f"動画タイトル: {plan.title}\n対象視聴者: {plan.target_audience}\nトーン: {plan.tone}\n\n"
        f"この章のタイトル: {chapter_title}\n章の概要: {chapter_summary}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _generate_plan(instruction: str, target_duration_minutes: float) -> PlanOutline:
    response = llm_client.chat_completion(_build_plan_prompt(instruction, target_duration_minutes))
    try:
        data = parse_json_object(response)
    except JSONExtractionError as exc:
        raise ProductionError(f"企画案をJSONとして解釈できませんでした: {exc}") from exc
    try:
        return PlanOutline.model_validate(data)
    except ValidationError as exc:
        raise ProductionError(f"企画案の形式が不正です: {exc}") from exc


def _generate_chapter_script(
    plan: PlanOutline, chapter_title: str, chapter_summary: str, target_seconds: float
) -> ChapterScript:
    response = llm_client.chat_completion(
        _build_chapter_script_prompt(plan, chapter_title, chapter_summary, target_seconds)
    )
    try:
        data = parse_json_object(response)
    except JSONExtractionError as exc:
        raise ProductionError(f"台本をJSONとして解釈できませんでした: {exc}") from exc
    try:
        return ChapterScript.model_validate(data)
    except ValidationError as exc:
        raise ProductionError(f"台本の形式が不正です: {exc}") from exc


def run_production(
    project_id: str, job_id: str, instruction: str, target_duration_minutes: float
) -> None:
    db = SessionLocal()
    current_step = "planning"
    started_at = time.time()
    resolved_model_id: str | None = None
    log_lines: list[str] = [
        job_log.timestamp_line("Production started"),
        job_log.timestamp_line("AI Provider: LM Studio"),
        job_log.timestamp_line(f"Endpoint: {LLM_BASE_URL}/chat/completions"),
        job_log.timestamp_line(f"Task: {STEP_LABELS['planning']}"),
    ]
    try:
        # Check LM Studio (server -> /v1/models -> requested model -> ready)
        # before doing any work, so a doomed job never gets past "Production
        # started" with only a vague error to show for it.
        status = llm_preflight.run_check(log_lines)
        if not status.ready:
            raise llm_client.LLMNotReadyError(status)
        resolved_model_id = status.configured_model

        project = db.get(Project, project_id)
        if project is None:
            raise ProductionError(f"Project {project_id} not found")

        # Re-running production replaces any previous plan for this project.
        db.query(Scene).filter(Scene.project_id == project_id).delete()
        db.query(Chapter).filter(Chapter.project_id == project_id).delete()
        db.query(ProductionSpec).filter(ProductionSpec.project_id == project_id).delete()
        db.commit()

        current_step = "planning"
        _update_job(db, job_id, status="running", progress=2.0, message="企画中", step=current_step)
        plan = _generate_plan(instruction, target_duration_minutes)
        log_lines.append(job_log.timestamp_line("Planning request completed"))

        db.add(
            ProductionSpec(
                project_id=project_id,
                instruction=instruction,
                target_duration_minutes=target_duration_minutes,
                title=plan.title,
                target_audience=plan.target_audience,
                tone=plan.tone,
            )
        )

        chapter_rows: list[Chapter] = []
        for i, ch in enumerate(plan.chapters):
            row = Chapter(project_id=project_id, order_index=i, title=ch.title, summary=ch.summary)
            db.add(row)
            chapter_rows.append(row)
        db.commit()
        for row in chapter_rows:
            db.refresh(row)

        n_chapters = len(chapter_rows)
        target_seconds_per_chapter = (target_duration_minutes * 60) / n_chapters
        total_scenes = 0

        current_step = "scene_generation"
        log_lines.append(job_log.timestamp_line(f"Task: {STEP_LABELS['scene_generation']}"))
        for i, chapter_row in enumerate(chapter_rows):
            _update_job(
                db,
                job_id,
                progress=round(15 + i / n_chapters * 80, 1),
                message=f"台本・絵コンテを生成中: 第{i + 1}章/{n_chapters}章「{chapter_row.title}」",
                step=current_step,
            )
            script = _generate_chapter_script(
                plan, chapter_row.title, chapter_row.summary, target_seconds_per_chapter
            )
            log_lines.append(
                job_log.timestamp_line(f"Chapter {i + 1}/{n_chapters} script generated")
            )
            for j, scene in enumerate(script.scenes):
                db.add(
                    Scene(
                        chapter_id=chapter_row.id,
                        project_id=project_id,
                        order_index=j,
                        narration=scene.narration,
                        visual_type=scene.visual_type,
                        visual_prompt=scene.visual_prompt,
                        estimated_duration=scene.estimated_duration,
                        status="pending",
                    )
                )
                total_scenes += 1
            db.commit()

        _write_plan_files(project_id, plan, chapter_rows, db)

        _update_job(
            db,
            job_id,
            status="completed",
            progress=100.0,
            message=f"企画完了: {n_chapters}章 / {total_scenes}シーン",
        )
        log_lines.append(job_log.timestamp_line("Production completed"))

        try:
            time_estimate_service.record_production(
                target_duration_minutes=target_duration_minutes,
                elapsed_seconds=time.time() - started_at,
                model_id=resolved_model_id,
            )
        except Exception:
            logger.exception("Failed to record perf history for production job %s", job_id)
    except Exception as exc:  # noqa: BLE001 - surfaced to the job row for the UI
        logger.exception("Production job %s failed", job_id)
        db.rollback()

        status = exc.status if isinstance(exc, llm_client.LLMNotReadyError) else llm_client.get_status()
        context = ai_diagnostics.AIContext(
            provider="LM Studio",
            model=status.configured_model or "(未解決)",
            task=STEP_LABELS.get(current_step, current_step),
            operation="Chat Completion",
            endpoint=f"{LLM_BASE_URL}/chat/completions",
            model_status="loaded" if status.can_generate else (
                "not_loaded" if status.api_ok else "unreachable"
            ),
            requested_model=status.configured_model or "",
            model_source=status.model_source,
            models_loaded=status.models_loaded,
            connection_status="OK" if status.server_reachable else "NG",
            error_code=status.error_code,
        )
        diagnosis = ai_diagnostics.diagnose(exc, context=context, step=current_step)
        log_lines.append(job_log.timestamp_line(f"ERROR: {diagnosis.summary}"))
        if diagnosis.error_code and not isinstance(exc, llm_client.LLMNotReadyError):
            log_lines.append(job_log.timestamp_line(f"[LM_STUDIO] ERROR: {diagnosis.error_code}"))
        log_lines.append(job_log.timestamp_line("Production aborted"))

        _update_job(
            db,
            job_id,
            status="failed",
            error=diagnosis.summary,
            error_detail=json.dumps(diagnosis.to_dict(), ensure_ascii=False),
            step=current_step,
            message="AI制作に失敗しました",
        )
    finally:
        job_log.write_log(project_id, "produce", job_id, log_lines)
        db.close()


def _write_plan_files(project_id: str, plan: PlanOutline, chapter_rows: list[Chapter], db) -> None:
    script_dir = project_dir(project_id) / "script"
    storyboard_dir = project_dir(project_id) / "storyboard"
    script_dir.mkdir(parents=True, exist_ok=True)
    storyboard_dir.mkdir(parents=True, exist_ok=True)

    plan_doc = {
        "title": plan.title,
        "target_audience": plan.target_audience,
        "tone": plan.tone,
        "chapters": [{"title": c.title, "summary": c.summary} for c in plan.chapters],
    }
    (script_dir / "plan.json").write_text(
        json.dumps(plan_doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    storyboard_doc = []
    for chapter_row in chapter_rows:
        scenes = (
            db.query(Scene)
            .filter(Scene.chapter_id == chapter_row.id)
            .order_by(Scene.order_index)
            .all()
        )
        storyboard_doc.append(
            {
                "chapter": chapter_row.title,
                "scenes": [
                    {
                        "narration": s.narration,
                        "visual_type": s.visual_type,
                        "visual_prompt": s.visual_prompt,
                        "estimated_duration": s.estimated_duration,
                    }
                    for s in scenes
                ],
            }
        )
    (storyboard_dir / "storyboard.json").write_text(
        json.dumps(storyboard_doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
