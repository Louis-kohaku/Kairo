"""One collection pass: fetch -> normalise -> dedupe -> classify -> store.

Separated from the worker so the same pass can be triggered three ways -
on the schedule, from the Settings UI ("今すぐ更新"), and by a production
run that found no usable data - without duplicating the failure handling.

A pass never raises. A source that is down is a recorded per-source failure,
and the pass reports `partial`; the planner then works with whatever is in
the store, including nothing.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone

from app.core.db import SessionLocal
from app.models.trend import TrendCollectionRun
from app.services import settings_service
from app.services.trends import genre as genre_module
from app.services.trends import sources, store

logger = logging.getLogger(__name__)

# One pass at a time, process-wide. Two concurrent passes would race on the
# same upsert identities and double-count `observation_count`.
_lock = threading.Lock()

# Per-source outcome of the most recent attempt, for the Settings UI. In
# memory only: it describes this process's connectivity, and a stale answer
# from a previous run would be worse than none.
_last_status: dict[str, dict] = {}


def last_status() -> dict[str, dict]:
    return dict(_last_status)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def collect_once(*, region: str | None = None, source_ids: list[str] | None = None) -> dict:
    """Runs one collection pass and returns a summary dict.

    Returns immediately with `status="busy"` if a pass is already running,
    rather than queueing: the next scheduled pass is minutes away and two
    passes would collect the same thing.
    """
    if not _lock.acquire(blocking=False):
        return {"status": "busy", "detail": "既にトレンド収集が実行中です。"}

    db = SessionLocal()
    settings = settings_service.get_settings()
    region = region or settings.trends.region
    wanted = source_ids if source_ids is not None else settings.trends.sources
    limit = settings.trends.max_signals_per_source

    run = TrendCollectionRun(status="running")
    db.add(run)
    db.commit()

    details: list[dict] = []
    collected = inserted = updated = 0
    try:
        for spec in sources.SOURCE_SPECS:
            if spec.id not in wanted:
                details.append(
                    {"id": spec.id, "ok": False, "count": 0, "error": "設定で無効化されています",
                     "skipped": True}
                )
                continue
            if not sources.has_key(spec):
                message = f"APIキー未設定 ({spec.key_env})"
                details.append(
                    {"id": spec.id, "ok": False, "count": 0, "error": message, "skipped": True}
                )
                _last_status[spec.id] = {"ok": False, "error": message, "count": 0,
                                         "at": _now().isoformat()}
                continue

            try:
                raws = sources.fetch(spec.id, region=region, limit=limit)
            except Exception as exc:  # noqa: BLE001 - one bad source must not stop the pass
                logger.info("Trend source %s failed: %s", spec.id, exc)
                details.append({"id": spec.id, "ok": False, "count": 0, "error": str(exc)})
                _last_status[spec.id] = {"ok": False, "error": str(exc), "count": 0,
                                         "at": _now().isoformat()}
                continue

            ins, upd = store.upsert_many(db, raws)
            collected += len(raws)
            inserted += ins
            updated += upd
            details.append({"id": spec.id, "ok": True, "count": len(raws), "error": ""})
            _last_status[spec.id] = {"ok": True, "error": "", "count": len(raws),
                                     "at": _now().isoformat()}

        ok_count = sum(1 for d in details if d.get("ok"))
        attempted = sum(1 for d in details if not d.get("skipped"))
        if attempted == 0:
            status = "failed"
        elif ok_count == attempted:
            status = "ok"
        elif ok_count == 0:
            status = "failed"
        else:
            status = "partial"

        run.status = status
        run.collected = collected
        run.inserted = inserted
        run.updated = updated
        run.detail_json = json.dumps(details, ensure_ascii=False)
        run.finished_at = _now()
        db.commit()

        store.prune(db)
        # Keep every stored row's genre in step with the current taxonomy,
        # not just the ones this pass happened to re-observe.
        store.reclassify(db, region=region)
        if collected:
            refresh_profiles(db, region=region)

        return {
            "status": status,
            "collected": collected,
            "inserted": inserted,
            "updated": updated,
            "sources": details,
            "finished_at": run.finished_at.isoformat(),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("Trend collection pass failed")
        run.status = "failed"
        run.detail_json = json.dumps(details + [{"id": "_pass", "ok": False, "error": str(exc)}],
                                     ensure_ascii=False)
        run.finished_at = _now()
        db.commit()
        return {"status": "failed", "error": str(exc), "sources": details}
    finally:
        db.close()
        _lock.release()


# How many signals a genre needs before Kairo will ask the model to profile
# it. Below this the "analysis" would be the model's priors dressed up as a
# finding, so the built-in convention profile is used and labelled as such.
MIN_SIGNALS_FOR_ANALYSIS = 5


def refresh_profiles(db, *, region: str = "JP", force: bool = False) -> list[str]:
    """Re-derives genre profiles for genres with enough fresh evidence.

    Only genres that cleared `MIN_SIGNALS_FOR_ANALYSIS` are analysed; the
    rest keep (or fall back to) the built-in convention profile, so a
    profile is never presented as derived from data that does not exist.
    """
    counts = store.counts_by_category(db, region=region)
    refreshed: list[str] = []
    for genre_id, count in counts.items():
        if genre_id == "unknown":
            continue
        if count < MIN_SIGNALS_FOR_ANALYSIS and not force:
            continue
        keywords = store.keywords_for_genre(db, genre_id, region=region)
        profile, derived_from = genre_module.analyze(genre_id, keywords)
        store.save_profile(
            db,
            genre_id,
            region,
            profile,
            derived_from=derived_from,
            sample_size=len(keywords) if derived_from == "llm" else 0,
        )
        refreshed.append(genre_id)
    return refreshed


def latest_run(db) -> TrendCollectionRun | None:
    return (
        db.query(TrendCollectionRun)
        .order_by(TrendCollectionRun.started_at.desc())
        .first()
    )
