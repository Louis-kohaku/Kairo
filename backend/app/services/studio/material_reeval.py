"""Re-deciding material on a video that already exists.

Design requirement 12: after a production has finished, the user can drop
in three more photos of the sea and expect the video to get better, not to
have to start again.

What this does, in order:

1. analyses whatever material has not been analysed yet;
2. re-runs the same matching the production used, over the *same* scenes;
3. rebuilds only the scenes whose material actually changed;
4. reassembles the timeline and re-renders the MP4.

Steps 3 and 4 are what make it a real feature rather than a database
update: a scene whose photo changed but whose clip was never re-encoded
would still play the old picture. Everything goes through
`material_service.rebuild_scene` and `assembly_service.assemble`, the same
two functions the pipeline uses, so a re-evaluated video is built exactly
like a freshly produced one.

Progress is reported both on the Job row (so the generic job UI works) and
as production events on the project's latest run (so it appears in the
studio's own log, where the user is actually looking).
"""
from __future__ import annotations

import json
import logging

from app.core.db import SessionLocal
from app.models.job import Job
from app.models.media_asset import MediaAsset
from app.models.project import Project
from app.services import ai_diagnostics, render_service, settings_service
from app.services.studio import (
    assembly_service,
    events,
    material_analysis,
    material_plan,
    material_service,
    planning_service,
    run_service,
)

logger = logging.getLogger(__name__)

_CRF_BY_PRESET = {"fast": 26, "standard": 21, "high": 18, "ultra": 15, "custom": 21}


def run_reevaluate(
    project_id: str,
    job_id: str,
    *,
    mode: str = "ai_auto",
    selected_ids: list[str] | None = None,
    rerender: bool = True,
) -> None:
    db = SessionLocal()
    run = None
    try:
        job = db.get(Job, job_id)
        project = db.get(Project, project_id)
        if job is None or project is None:
            raise RuntimeError("プロジェクトまたはジョブが見つかりません。")
        job.status = "running"
        job.progress = 0.0
        db.commit()

        run = run_service.latest_run(db, project_id)

        def report(
            message: str, *, reason: str = "", status: str = "running", progress: float | None = None
        ) -> None:
            row = db.get(Job, job_id)
            if row is not None:
                row.message = message
                if progress is not None:
                    row.progress = progress
                db.commit()
            if run is not None:
                events.emit(
                    run.id,
                    project_id,
                    phase="material_match",
                    task="追加素材を反映しています",
                    status=status,
                    message=message,
                    reason=reason,
                )

        scenes = planning_service.ordered_scenes(db, project_id)
        if not scenes:
            raise RuntimeError(
                "このプロジェクトにはシーンがありません。先に制作を実行してください。"
            )

        report("追加された素材を解析しています", progress=5.0)
        material_analysis.analyze_project(db, project_id)

        # Keyed on the pin, not on the provenance: a scene whose generated
        # background is unchanged must not be re-encoded just because the
        # plan was recomputed.
        before = {scene.id: (scene.asset_source, scene.user_asset_id) for scene in scenes}
        strategy = planning_service.strategy_from_json(run.strategy_json if run else None)
        orientation = run.orientation if run else "vertical"

        report(
            "素材の割り当てをやり直しています",
            reason="追加素材を含めて全シーンを再評価します",
            progress=15.0,
        )
        plan = material_plan.build_plan(
            db,
            project_id,
            scenes,
            mode=mode,
            selected_ids=selected_ids or [],
            orientation=orientation,
        )
        material_plan.apply_plan(db, plan, scenes)
        if run is not None:
            run.material_plan_json = material_plan.to_json(plan)
            run.material_mode = mode
            run.selected_asset_ids = json.dumps(selected_ids or [])
            db.commit()

        changed = [
            i
            for i, scene in enumerate(scenes)
            if before.get(scene.id) != (scene.asset_source, scene.user_asset_id)
        ]

        if not changed:
            report(
                "より良い素材は見つかりませんでした。現在の構成のままです。",
                reason="既存の割り当てのほうが一致度が高いと判断されました",
                status="done",
                progress=100.0,
            )
            row = db.get(Job, job_id)
            row.status = "completed"
            db.commit()
            return

        report(f"{len(changed)}シーンの素材が変わりました。作り直します。", progress=20.0)
        settings = settings_service.get_settings()
        crf = _CRF_BY_PRESET.get(settings.video.quality_preset, 21)
        sources = plan.available_fill_sources

        for count, index in enumerate(changed):
            scene = scenes[index]
            if scene.asset_source not in ("user", "web") or not scene.user_asset_id:
                # This scene lost its pinned material to a better-matching
                # scene, so it needs a replacement picture before it can be
                # re-encoded.
                material_service.fill_missing_visual(
                    db,
                    project,
                    scene,
                    index,
                    strategy,
                    keywords=material_plan.shortage_keywords(scene),
                    sources=sources,
                    orientation=orientation,
                )
            report(
                f"Scene {index + 1} を新しい素材で作り直しています",
                reason=scene.material_note or "",
                progress=20.0 + 50.0 * (count / max(1, len(changed))),
            )
            material_service.rebuild_scene(
                db,
                project,
                scene,
                index,
                strategy,
                engine_id=settings.generation.default_engine_id or "procedural",
                crf=crf,
                use_narration=bool(scene.narration_duration),
                voice_id=settings.tts.selected_voice,
                is_last=(index == len(scenes) - 1),
            )

        bgm = (
            db.query(MediaAsset)
            .filter(
                MediaAsset.project_id == project_id,
                MediaAsset.kind == "audio",
                MediaAsset.original_filename.like("AI生成BGM%"),
            )
            .order_by(MediaAsset.imported_at.desc())
            .first()
        )
        assembly_service.assemble(db, project, scenes, bgm)
        report("タイムラインを更新しました", progress=75.0)

        if rerender:
            report("新しい素材でMP4を書き出しています", progress=80.0)
            render_job = Job(project_id=project_id, type="render", status="pending")
            db.add(render_job)
            db.commit()
            db.refresh(render_job)
            render_service.run_render(project_id, render_job.id, settings.subtitle.enabled, crf)
            db.expire_all()
            finished = db.get(Job, render_job.id)
            if finished is None or finished.status != "completed":
                raise RuntimeError(
                    (finished.error if finished else None) or "書き出しに失敗しました"
                )
            if run is not None:
                run.output_path = finished.output_path
                run.render_job_id = render_job.id
                db.commit()

        row = db.get(Job, job_id)
        row.status = "completed"
        row.progress = 100.0
        db.commit()
        report(
            f"追加素材を反映しました（{len(changed)}シーンを更新）",
            status="done",
            progress=100.0,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced on the job row
        logger.exception("Material re-evaluation failed for project %s", project_id)
        db.rollback()
        diagnosis = ai_diagnostics.diagnose(exc, step="material_reeval")
        row = db.get(Job, job_id)
        if row is not None:
            row.status = "failed"
            row.error = diagnosis.summary
            row.error_detail = json.dumps(diagnosis.to_dict(), ensure_ascii=False)
            db.commit()
        if run is not None:
            events.emit(
                run.id,
                project_id,
                phase="material_match",
                status="failed",
                message=diagnosis.summary,
                reason=diagnosis.cause,
                error=diagnosis.to_dict(),
            )
    finally:
        db.close()
