"""Persisting, de-duplicating, ageing and querying trend signals.

The store is what turns a series of one-off fetches into intelligence. Three
behaviours matter:

**Dedupe on identity, not on row.** A signal is identified by
(platform, normalised keyword, region). Seeing it again updates the existing
row - which is also the only way ``growth_rate`` can exist, since growth is
the difference between this observation and the last one of the same thing.

**Age, don't delete.** A trend that stopped trending is still evidence, so
rows are kept; what changes is their weight. ``effective_score`` applies an
exponential half-life to the stored score, and anything past ``expires_at``
is excluded from planning while remaining visible in history.

**Never fabricate.** Nothing here invents a signal, a category or a score.
A keyword the classifier cannot place stays "unknown", and a source that
returns nothing produces no rows.
"""
from __future__ import annotations

import json
import logging
import math
import unicodedata
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from app.models.trend import GenreProfile, TrendSignal
from app.schemas.trend import GenreProfileData, RawTrend, TrendSignalOut
from app.services.trends import genre as genre_module

logger = logging.getLogger(__name__)

# How long a signal stays eligible for planning. Trend keywords go stale
# fast; three days is long enough that a weekend of not opening Kairo does
# not leave the planner with nothing, and short enough that "現在のトレンド"
# means it.
DEFAULT_TTL_HOURS = 72
# Score halves every this many hours when computing `effective_score`, so a
# fresh 60 outranks a two-day-old 90.
SCORE_HALF_LIFE_HOURS = 30.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; every comparison here is UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def normalize_keyword(keyword: str) -> str:
    """Dedupe key: NFKC-folded, case-folded, whitespace-collapsed.

    NFKC matters for Japanese specifically - full-width and half-width forms
    of the same word arrive from different sources and are the same trend.
    """
    text = unicodedata.normalize("NFKC", keyword or "")
    return " ".join(text.split()).casefold()


def effective_score(score: float, observed_at: datetime | None, *, now: datetime | None = None) -> float:
    """The stored score decayed by how long ago it was observed."""
    observed = _aware(observed_at)
    if observed is None:
        return 0.0
    now = now or _now()
    hours = max(0.0, (now - observed).total_seconds() / 3600.0)
    return round(score * math.pow(0.5, hours / SCORE_HALF_LIFE_HOURS), 2)


# --------------------------------------------------------------- writing


def upsert(db, raw: RawTrend, *, ttl_hours: int = DEFAULT_TTL_HOURS) -> tuple[TrendSignal, bool]:
    """Stores one observation. Returns (row, created)."""
    norm = normalize_keyword(raw.keyword)
    now = _now()
    category = genre_module.classify(raw.keyword, hint=raw.category_hint)

    existing = (
        db.query(TrendSignal)
        .filter(
            TrendSignal.platform == raw.platform,
            TrendSignal.keyword_norm == norm,
            TrendSignal.region == raw.region,
        )
        .one_or_none()
    )

    if existing is None:
        row = TrendSignal(
            platform=raw.platform,
            keyword=raw.keyword[:300],
            keyword_norm=norm[:300],
            category=category,
            region=raw.region,
            score=raw.score,
            raw_score=raw.raw_score,
            growth_rate=0.0,
            observation_count=1,
            observed_at=now,
            first_seen_at=now,
            expires_at=now + timedelta(hours=ttl_hours),
            source=raw.source[:200],
            source_url=raw.source_url,
            metadata_json=json.dumps(raw.metadata, ensure_ascii=False),
        )
        db.add(row)
        return row, True

    existing.growth_rate = round(raw.score - existing.score, 2)
    existing.score = raw.score
    existing.raw_score = raw.raw_score
    existing.observation_count += 1
    existing.observed_at = now
    existing.expires_at = now + timedelta(hours=ttl_hours)
    existing.source = raw.source[:200]
    existing.source_url = raw.source_url
    existing.metadata_json = json.dumps(raw.metadata, ensure_ascii=False)
    # A keyword can change genre when a provider starts sending a category
    # hint it did not send before; an "unknown" is never written over a real
    # classification, because losing information is not an update.
    if category != "unknown":
        existing.category = category
    return existing, False


def upsert_many(db, raws: list[RawTrend], *, ttl_hours: int = DEFAULT_TTL_HOURS) -> tuple[int, int]:
    inserted = updated = 0
    for raw in raws:
        if not (raw.keyword or "").strip():
            continue
        _row, created = upsert(db, raw, ttl_hours=ttl_hours)
        if created:
            inserted += 1
        else:
            updated += 1
    db.commit()
    return inserted, updated


# --------------------------------------------------------------- reading


def to_out(row: TrendSignal, *, now: datetime | None = None) -> TrendSignalOut:
    now = now or _now()
    expires = _aware(row.expires_at)
    try:
        metadata = json.loads(row.metadata_json) if row.metadata_json else {}
    except ValueError:
        metadata = {}
    observed = _aware(row.observed_at)
    return TrendSignalOut(
        id=row.id,
        platform=row.platform,
        keyword=row.keyword,
        category=row.category,
        category_label=genre_module.label(row.category),
        region=row.region,
        score=row.score,
        growth_rate=row.growth_rate,
        observation_count=row.observation_count,
        observed_at=observed.isoformat() if observed else None,
        expires_at=expires.isoformat() if expires else None,
        source=row.source,
        source_url=row.source_url,
        metadata=metadata if isinstance(metadata, dict) else {},
        effective_score=effective_score(row.score, row.observed_at, now=now),
        stale=bool(expires and expires < now),
    )


def query_signals(
    db,
    *,
    category: str | None = None,
    region: str | None = None,
    platform: str | None = None,
    include_stale: bool = False,
    limit: int = 50,
) -> list[TrendSignalOut]:
    """Signals ranked by decayed score, freshest-strongest first."""
    now = _now()
    q = db.query(TrendSignal)
    if category and category != "all":
        q = q.filter(TrendSignal.category == category)
    if region:
        q = q.filter(TrendSignal.region == region)
    if platform and platform != "all":
        q = q.filter(TrendSignal.platform == platform)
    if not include_stale:
        q = q.filter(TrendSignal.expires_at >= now.replace(tzinfo=None))

    # Ordering by stored score first bounds how much is loaded; the final
    # ranking is by decayed score, which SQLite cannot compute.
    rows = q.order_by(TrendSignal.score.desc()).limit(max(limit * 4, 100)).all()
    out = [to_out(r, now=now) for r in rows]
    out.sort(key=lambda s: s.effective_score, reverse=True)
    return out[:limit]


def counts_by_category(db, *, region: str | None = None, include_stale: bool = False) -> dict[str, int]:
    q = db.query(TrendSignal.category, func.count(TrendSignal.id))
    if region:
        q = q.filter(TrendSignal.region == region)
    if not include_stale:
        q = q.filter(TrendSignal.expires_at >= _now().replace(tzinfo=None))
    return {category: count for category, count in q.group_by(TrendSignal.category).all()}


def total_count(db) -> int:
    return db.query(func.count(TrendSignal.id)).scalar() or 0


def fresh_count(db, *, region: str | None = None) -> int:
    q = db.query(func.count(TrendSignal.id)).filter(
        TrendSignal.expires_at >= _now().replace(tzinfo=None)
    )
    if region:
        q = q.filter(TrendSignal.region == region)
    return q.scalar() or 0


def reclassify(db, *, region: str | None = None) -> int:
    """Re-runs genre classification over stored rows.

    The taxonomy in `genre.py` changes as it is refined, and a row keeps
    whatever category it was given when it was first seen. Without this, a
    keyword that was mis-filed under an earlier version of the vocabulary
    stays mis-filed until it happens to be observed again - and the planner
    would keep reading it as evidence for the wrong genre.
    """
    q = db.query(TrendSignal)
    if region:
        q = q.filter(TrendSignal.region == region)
    changed = 0
    for row in q.all():
        category = genre_module.classify(row.keyword)
        if category != row.category:
            row.category = category
            changed += 1
    if changed:
        db.commit()
    return changed


def prune(db, *, keep_days: int = 30) -> int:
    """Drops observations nobody will look at again.

    History is useful, but unbounded history in a local SQLite file is not.
    Rows older than `keep_days` since their last observation are removed.
    """
    cutoff = (_now() - timedelta(days=keep_days)).replace(tzinfo=None)
    deleted = (
        db.query(TrendSignal).filter(TrendSignal.observed_at < cutoff).delete(synchronize_session=False)
    )
    db.commit()
    return int(deleted or 0)


# -------------------------------------------------------- genre profiles


def get_profile(db, genre_id: str, region: str = "JP") -> tuple[GenreProfileData, str, int, datetime | None]:
    """The stored profile for a genre, or the built-in default.

    Returns (profile, derived_from, sample_size, updated_at) so every caller
    can be explicit about whether it is showing an analysis or a convention.
    """
    row = (
        db.query(GenreProfile)
        .filter(GenreProfile.genre == genre_id, GenreProfile.region == region)
        .one_or_none()
    )
    if row is None:
        return genre_module.default_profile(genre_id), "defaults", 0, None
    try:
        profile = GenreProfileData.model_validate(json.loads(row.profile_json or "{}"))
    except Exception:
        logger.exception("Stored genre profile for %s is unreadable; using defaults", genre_id)
        return genre_module.default_profile(genre_id), "defaults", 0, None
    return profile, row.derived_from, row.sample_size, _aware(row.updated_at)


def save_profile(
    db,
    genre_id: str,
    region: str,
    profile: GenreProfileData,
    *,
    derived_from: str,
    sample_size: int,
) -> GenreProfile:
    row = (
        db.query(GenreProfile)
        .filter(GenreProfile.genre == genre_id, GenreProfile.region == region)
        .one_or_none()
    )
    payload = genre_module.profile_to_json(profile)
    if row is None:
        row = GenreProfile(
            genre=genre_id,
            region=region,
            profile_json=payload,
            derived_from=derived_from,
            sample_size=sample_size,
        )
        db.add(row)
    else:
        row.profile_json = payload
        row.derived_from = derived_from
        row.sample_size = sample_size
        row.updated_at = _now()
    db.commit()
    return row


def keywords_for_genre(db, genre_id: str, region: str = "JP", limit: int = 25) -> list[str]:
    return [s.keyword for s in query_signals(db, category=genre_id, region=region, limit=limit)]
