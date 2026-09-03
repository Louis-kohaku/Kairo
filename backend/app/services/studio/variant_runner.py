"""Runs an A/B/C variant job on a worker thread.

Thin by design: it owns the database session, the Job row's progress, and
the failure reporting, and hands the actual work to `variants.produce`. That
split is what lets the variant logic be exercised without a Job row (the
tests call `produce` directly) while the HTTP path still gets progress and a
diagnosed failure.
"""
from __future__ import annotations

import json
import logging

from app.core.db import SessionLocal
from app.models.job import Job
from app.models.project import Project
from app.services import ai_diagnostics
from app.services.studio import planning_service, run_service, variants
from app.services.trends import service as trend_service

logger = logging.getLogger(__name__)


def _update(db, job: Job, **fields) -> None:
    for key, value in fields.items():
        setattr(job, key, value)
    db.commit()


def run_variants(project_id: str, job_id: str, variant_ids: list[str]) -> None:
    db = SessionLocal()
    job = db.get(Job, job_id)
    try:
        project = db.get(Project, project_id)
        if project is None or job is None:
            raise RuntimeError(f"Project {project_id} not found")

        run = run_service.latest_run(db, project_id)
        if run is None:
            raise RuntimeError("制作ランが見つかりません。先に制作を実行してください。")

        strategy = planning_service.strategy_from_json(run.strategy_json)
        trend = None
        if run.trend_json:
            from app.schemas.trend import TrendContext

            try:
                trend = TrendContext.model_validate(json.loads(run.trend_json))
            except Exception:
                trend = None
        if trend is None:
            trend = trend_service.build_context(db, run.instruction)

        wanted = variant_ids or ["A", "B", "C"]
        _update(
            db,
            job,
            status="running",
            progress=1.0,
            message=f"{len(wanted)}パターンを作成します",
            step="variants",
        )

        done = {"n": 0}

        def on_progress(message: str) -> None:
            # Progress is reported per completed variant rather than
            # smoothly: the expensive part is a full render, and a bar that
            # crept during an encode would be inventing information.
            if message.startswith("バリエーション") and "点" in message:
                done["n"] += 1
            _update(
                db,
                job,
                progress=round(min(95.0, done["n"] / max(1, len(wanted)) * 100.0), 1),
                message=message,
            )

        outcome = variants.produce(
            db,
            project,
            run,
            strategy=strategy,
            trend=trend,
            variant_ids=wanted,
            on_progress=on_progress,
        )

        run.variants_json = variants.to_json(outcome)
        db.commit()

        summary = " / ".join(f"{r.id}:{r.score:.0f}点" for r in outcome.records)
        _update(
            db,
            job,
            status="completed",
            progress=100.0,
            message=(
                f"{summary} → Best: {outcome.best_id}"
                if outcome.best_id
                else (outcome.error or "バリエーションを作成できませんでした")
            ),
            output_path=run.output_path,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced onto the job row
        logger.exception("Variant job %s failed", job_id)
        db.rollback()
        diagnosis = ai_diagnostics.diagnose(exc, step="variants")
        if job is not None:
            _update(
                db,
                job,
                status="failed",
                error=diagnosis.summary,
                error_detail=json.dumps(diagnosis.to_dict(), ensure_ascii=False),
                message="バリエーションの作成に失敗しました",
            )
    finally:
        db.close()
