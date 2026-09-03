"""Choosing assets, and being able to say why.

Every function here returns a `Selection`: the asset, a score, and a
human-readable reason built from the criteria that actually moved the score.
The reason is not decoration - the UI shows it as "AIが選んだ理由", and a
selection that cannot explain itself is indistinguishable from a random one.

Licence is a filter, not a factor. An asset whose status is outside
`AUTO_USABLE_STATUSES` is removed from the candidate list before scoring, so
there is no weighting under which an unlicensed asset can win. When that
leaves nothing, the caller is told there is nothing - never handed the best
of the ineligible.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from app.models.library import LibraryAsset
from app.schemas.trend import GenreProfileData
from app.services.library import licenses

logger = logging.getLogger(__name__)


@dataclass
class Selection:
    asset: LibraryAsset | None
    score: float = 0.0
    reason: str = ""
    reasons: list[str] = field(default_factory=list)
    considered: int = 0
    rejected_for_license: int = 0
    fallback: bool = False

    @property
    def found(self) -> bool:
        return self.asset is not None

    def to_dict(self) -> dict:
        if self.asset is None:
            return {
                "found": False,
                "reason": self.reason,
                "considered": self.considered,
                "rejected_for_license": self.rejected_for_license,
            }
        return {
            "found": True,
            "id": self.asset.id,
            "kind": self.asset.kind,
            "name": self.asset.name,
            "family": self.asset.family,
            "path": self.asset.path,
            "category": self.asset.category,
            "mood": self.asset.mood,
            "bpm": self.asset.bpm,
            "duration": self.asset.duration,
            "loudness_lufs": self.asset.loudness_lufs,
            "readability": self.asset.readability or None,
            "score": round(self.score, 1),
            "reason": self.reason,
            "reasons": self.reasons,
            "license": {
                "id": self.asset.license_id,
                "name": self.asset.license_name,
                "status": self.asset.license_status,
                "status_label": licenses.status_label(self.asset.license_status),
                "url": self.asset.license_url,
                "attribution_required": self.asset.attribution_required,
                "attribution": self.asset.attribution_text,
                "commercial_use": self.asset.commercial_use,
            },
            "source": self.asset.source,
            "source_url": self.asset.source_url,
            "considered": self.considered,
            "rejected_for_license": self.rejected_for_license,
            "fallback": self.fallback,
        }


def _tags(row: LibraryAsset) -> set[str]:
    try:
        return set(json.loads(row.tags_json or "[]"))
    except ValueError:
        return set()


def _genres(row: LibraryAsset) -> set[str]:
    try:
        return set(json.loads(row.genres_json or "[]"))
    except ValueError:
        return set()


def _eligible(rows: list[LibraryAsset], *, require_commercial: bool) -> tuple[list, int]:
    ok: list[LibraryAsset] = []
    rejected = 0
    for row in rows:
        if not row.available:
            continue
        if licenses.is_auto_usable(
            row.license_status,
            require_commercial=require_commercial,
            license_id=row.license_id,
        ):
            ok.append(row)
        else:
            rejected += 1
    return ok, rejected


# ------------------------------------------------------------------ fonts


def select_font(
    db,
    *,
    genre: str,
    profile: GenreProfileData | None = None,
    require_japanese: bool = True,
    require_commercial: bool = True,
    prefer_styles: list[str] | None = None,
    min_readability: int = 60,
) -> Selection:
    """The caption face for one production.

    Japanese capability is a hard requirement by default rather than a
    weighting: a caption in a font without kana renders as boxes, which is
    not a worse choice than another font - it is a broken video.
    """
    rows = db.query(LibraryAsset).filter(LibraryAsset.kind == "font").all()
    if require_japanese:
        rows = [r for r in rows if r.supports_japanese]
    eligible, rejected = _eligible(rows, require_commercial=require_commercial)

    wanted = set(prefer_styles or [])
    if profile is not None:
        wanted |= set(profile.font_style or [])

    scored: list[tuple[float, list[str], LibraryAsset]] = []
    for row in eligible:
        tags = _tags(row)
        genres = _genres(row)
        reasons: list[str] = []
        score = 0.0

        # Readability is the dominant term: a short-form caption is read in
        # under a second on a small screen.
        score += (row.readability or 0) * 0.6
        if (row.readability or 0) >= 85:
            reasons.append(f"可読性スコア{row.readability}（推定）")

        if genre in genres:
            score += 22.0
            reasons.append(f"{genre}ジャンル向けの字形")

        matched = wanted & tags
        if matched:
            score += 8.0 * len(matched)
            reasons.append(f"求めるスタイルに一致: {', '.join(sorted(matched))}")

        # Captions want weight; a light face disappears against footage.
        if 500 <= (row.weight or 400) <= 800:
            score += 12.0
            reasons.append("字幕向きの太さ")
        elif (row.weight or 400) < 350:
            score -= 15.0

        if "decorative" in tags or "symbol" in tags:
            score -= 40.0
        if "mono" in tags:
            score -= 10.0
        if "italic" in tags:
            score -= 12.0

        # A font Kairo fetched with its licence beats an OS font of equal
        # merit: its terms are explicit and it is the same on every machine.
        if not row.is_system:
            score += 6.0
            reasons.append("ライセンス明示のKairoライブラリ書体")

        if (row.readability or 0) < min_readability:
            score -= 25.0

        scored.append((score, reasons, row))

    if not scored:
        return Selection(
            None,
            reason=(
                "使用できるフォントが見つかりませんでした。"
                + (
                    f"（ライセンス条件で{rejected}件を除外）"
                    if rejected
                    else "日本語対応フォントがインストールされていない可能性があります。"
                )
            ),
            considered=len(rows),
            rejected_for_license=rejected,
        )

    scored.sort(key=lambda item: item[0], reverse=True)
    score, reasons, row = scored[0]
    if not reasons:
        reasons = ["条件に最も近い書体として選択"]
    return Selection(
        row,
        score=score,
        reason=" / ".join(reasons[:3]),
        reasons=reasons,
        considered=len(rows),
        rejected_for_license=rejected,
    )


# ------------------------------------------------------------------ music


def select_music(
    db,
    *,
    mood: str,
    duration: float,
    profile: GenreProfileData | None = None,
    tempo: str = "medium",
    require_commercial: bool = True,
    require_beat: bool = False,
) -> Selection:
    """The BGM bed for one production.

    `require_beat` is what Beat Sync sets: without a measured or declared
    tempo there is no grid to cut against, so a track with no BPM is not a
    lower-ranked candidate, it is not a candidate.
    """
    rows = db.query(LibraryAsset).filter(LibraryAsset.kind == "music").all()
    eligible, rejected = _eligible(rows, require_commercial=require_commercial)
    if require_beat:
        eligible = [r for r in eligible if r.bpm]

    target_range = list(profile.bgm_bpm_range or []) if profile else []
    if len(target_range) != 2:
        target_range = {"fast": [120.0, 150.0], "slow": [78.0, 100.0]}.get(
            tempo, [95.0, 122.0]
        )
    target_bpm = sum(target_range) / 2.0

    scored: list[tuple[float, list[str], LibraryAsset]] = []
    for row in eligible:
        reasons: list[str] = []
        score = 40.0

        if row.mood and row.mood == mood:
            score += 30.0
            reasons.append(f"雰囲気「{mood}」に一致")
        elif row.category == mood:
            score += 24.0
            reasons.append(f"カテゴリ「{row.category}」が指定の雰囲気に一致")

        if row.bpm:
            distance = abs(row.bpm - target_bpm)
            score += max(-20.0, 25.0 - distance * 0.8)
            if distance <= 12:
                reasons.append(
                    f"テンポ{row.bpm:.0f}BPMが目標({target_range[0]:.0f}-{target_range[1]:.0f})に近い"
                )
        elif require_beat:
            continue

        # A bed shorter than the video has to loop; not fatal, but a longer
        # one is genuinely better, so it is worth a few points.
        if row.duration and row.duration >= duration:
            score += 10.0
            reasons.append("動画尺をそのままカバーできる長さ")

        scored.append((score, reasons, row))

    if not scored:
        detail = "ライセンス条件を満たすBGMがライブラリにありません。"
        if require_beat:
            detail = "テンポが判明しているBGMがライブラリにありません。"
        return Selection(
            None,
            reason=detail + (f"（{rejected}件をライセンスで除外）" if rejected else ""),
            considered=len(rows),
            rejected_for_license=rejected,
        )

    scored.sort(key=lambda item: item[0], reverse=True)
    score, reasons, row = scored[0]
    return Selection(
        row,
        score=score,
        reason=" / ".join(reasons[:3]) or "条件に最も近いBGMとして選択",
        reasons=reasons,
        considered=len(rows),
        rejected_for_license=rejected,
    )


# -------------------------------------------------------------------- SFX


def select_sfx(db, category: str, *, require_commercial: bool = True) -> Selection:
    rows = (
        db.query(LibraryAsset)
        .filter(LibraryAsset.kind == "sfx", LibraryAsset.category == category)
        .all()
    )
    eligible, rejected = _eligible(rows, require_commercial=require_commercial)
    if not eligible:
        return Selection(
            None,
            reason=f"「{category}」の効果音がライブラリにありません。",
            considered=len(rows),
            rejected_for_license=rejected,
        )
    # Shortest first: an accent that outlasts the moment it marks stops
    # being an accent.
    eligible.sort(key=lambda r: (r.duration or 99.0))
    row = eligible[0]
    return Selection(
        row,
        score=100.0,
        reason=f"「{category}」用の効果音",
        reasons=[f"カテゴリ{category}に登録された効果音"],
        considered=len(rows),
        rejected_for_license=rejected,
    )


def library_summary(db) -> dict:
    """Counts by kind and licence status, for the library screen."""
    rows = db.query(LibraryAsset).all()
    summary: dict[str, dict] = {}
    for row in rows:
        bucket = summary.setdefault(
            row.kind, {"total": 0, "available": 0, "by_status": {}, "auto_usable": 0}
        )
        bucket["total"] += 1
        if row.available:
            bucket["available"] += 1
        bucket["by_status"][row.license_status] = (
            bucket["by_status"].get(row.license_status, 0) + 1
        )
        if row.available and licenses.is_auto_usable(row.license_status):
            bucket["auto_usable"] += 1
    return summary
