"""What the production pipeline and the UI ask Trend Intelligence for.

Two questions, and they are deliberately different:

* `build_context(instruction)` - "what should this specific video know about
  what is currently trending?" Returns a `TrendContext` that is stored on
  the run, so the finished video can always show which trend data informed
  it and a later report never has to re-query and get a different answer.
* `overview()` - "what does Kairo currently know?" Powers the Trends screen
  and the connected-services view.

`build_context` never blocks on the network. If the store is empty it says
so (`used=False` with a reason) and the pipeline plans from the genre's
built-in conventions - a video is still a video when the trend feed is down.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.models.trend import TrendSignal
from app.schemas.trend import (
    GenreProfileData,
    TrendContext,
    TrendOverview,
    TrendSourceStatus,
)
from app.services import settings_service
from app.services.trends import collector, genre as genre_module, sources, store, worker

logger = logging.getLogger(__name__)

# How many signals a production is given. Enough for the planner to see a
# pattern, few enough that they do not crowd the brief out of the prompt.
CONTEXT_SIGNAL_LIMIT = 12


def build_context(db, instruction: str, *, genre_id: str | None = None) -> TrendContext:
    """The trend slice for one production run."""
    settings = settings_service.get_settings().trends
    resolved_genre = genre_id or genre_module.classify_instruction(instruction)
    label = genre_module.label(resolved_genre)
    region = settings.region

    if not settings.use_in_production:
        profile, derived_from, _sample, _updated = store.get_profile(db, resolved_genre, region)
        return TrendContext(
            used=False,
            reason="設定でトレンド情報を制作に使用しない指定になっています。",
            genre=resolved_genre,
            genre_label=label,
            region=region,
            profile=profile,
            profile_source=derived_from,
        )

    signals = store.query_signals(
        db, category=resolved_genre, region=region, limit=CONTEXT_SIGNAL_LIMIT
    )
    # A genre with nothing in it is common (Kairo has been running an hour,
    # or nobody is searching for cat videos today). Falling back to the
    # region's overall top signals is honest - they are real observations -
    # and the context records that the genre had none of its own.
    fallback_used = False
    if not signals:
        signals = store.query_signals(db, region=region, limit=CONTEXT_SIGNAL_LIMIT)
        fallback_used = bool(signals)

    profile, derived_from, sample_size, _updated = store.get_profile(db, resolved_genre, region)

    if not signals:
        return TrendContext(
            used=False,
            reason=(
                "蓄積されたトレンドデータがまだありません。"
                "ジャンルの定石で制作を続けます。"
            ),
            genre=resolved_genre,
            genre_label=label,
            region=region,
            profile=profile,
            profile_source=derived_from,
        )

    newest = max(
        (s.observed_at for s in signals if s.observed_at), default=None
    )
    reason = (
        f"{label}ジャンルの蓄積トレンド{len(signals)}件を使用しました。"
        if not fallback_used
        else (
            f"{label}ジャンルの直近トレンドがなかったため、"
            f"{region}全体の上位{len(signals)}件を参考にしました。"
        )
    )
    if derived_from == "defaults":
        reason += f"（ジャンル傾向はKairo組み込みの定石、サンプル数{sample_size}）"
    else:
        reason += f"（ジャンル傾向はトレンド{sample_size}件からローカルLLMが分析）"

    return TrendContext(
        used=True,
        reason=reason,
        genre=resolved_genre,
        genre_label=label,
        region=region,
        signals=signals,
        profile=profile,
        profile_source=derived_from,
        collected_at=newest,
    )


def profile_for(db, genre_id: str, region: str = "JP") -> tuple[GenreProfileData, str, int]:
    profile, derived_from, sample_size, _updated = store.get_profile(db, genre_id, region)
    return profile, derived_from, sample_size


# ------------------------------------------------------------- overview


def source_statuses() -> list[TrendSourceStatus]:
    settings = settings_service.get_settings().trends
    live = collector.last_status()
    out: list[TrendSourceStatus] = []
    for spec in sources.SOURCE_SPECS:
        recent = live.get(spec.id, {})
        out.append(
            TrendSourceStatus(
                id=spec.id,
                label=spec.label,
                kind=spec.kind,
                enabled=spec.id in settings.sources,
                configured=sources.has_key(spec),
                requires_key=spec.requires_key,
                key_env=spec.key_env,
                endpoint=spec.endpoint,
                terms_url=spec.terms_url,
                note=spec.note,
                last_ok=recent.get("at") if recent.get("ok") else None,
                last_error=str(recent.get("error") or ""),
                last_count=int(recent.get("count") or 0),
            )
        )
    return out


def overview(db, *, top_limit: int = 20) -> TrendOverview:
    settings = settings_service.get_settings().trends
    run = collector.latest_run(db)
    last_run_at = None
    if run is not None and run.started_at is not None:
        started = run.started_at
        last_run_at = (
            started if started.tzinfo else started.replace(tzinfo=timezone.utc)
        ).isoformat()

    return TrendOverview(
        enabled=settings.enabled,
        region=settings.region,
        interval_minutes=settings.interval_minutes,
        last_run_at=last_run_at,
        last_run_status=run.status if run is not None else "",
        next_run_at=worker.status().get("next_run_at"),
        total_signals=store.total_count(db),
        fresh_signals=store.fresh_count(db, region=settings.region),
        sources=source_statuses(),
        top=store.query_signals(db, region=settings.region, limit=top_limit),
        by_category=store.counts_by_category(db, region=settings.region),
    )


def genre_breakdown(db, *, region: str | None = None, per_genre: int = 5) -> list[dict]:
    """Per-genre trend view: counts, top keywords, and the genre profile."""
    settings = settings_service.get_settings().trends
    region = region or settings.region
    counts = store.counts_by_category(db, region=region)
    out: list[dict] = []
    for g in genre_module.GENRES:
        profile, derived_from, sample_size, updated = store.get_profile(db, g.id, region)
        out.append(
            {
                "genre": g.id,
                "label": g.label,
                "count": counts.get(g.id, 0),
                "signals": [
                    s.model_dump()
                    for s in store.query_signals(
                        db, category=g.id, region=region, limit=per_genre
                    )
                ],
                "profile": profile.model_dump(),
                "derived_from": derived_from,
                "sample_size": sample_size,
                "updated_at": updated.isoformat() if updated else None,
            }
        )
    out.sort(key=lambda row: row["count"], reverse=True)
    return out


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def signal_count(db) -> int:
    return db.query(TrendSignal).count()
