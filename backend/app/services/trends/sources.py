"""Where trend signals actually come from.

Every provider here is either a public feed its publisher offers for
programmatic reading, or an official API used with a key the *user*
supplies. There is deliberately no scraper for a service whose terms do not
allow it: TikTok and Instagram have no free public trends API, so Kairo
reports them as 未接続 in the UI rather than pretending, and never
screen-scrapes them.

Each provider is a small callable returning ``list[RawTrend]``. It may
raise; the collector records the failure per-source and keeps the others.
No provider is allowed to be required - Kairo is a local-first product and
must produce videos with the network unplugged.

Normalisation contract: every provider maps its own numbers onto a 0-100
``score`` so signals from different sources can be ranked against each
other, while keeping the provider's native number in ``raw_score`` so the
UI can show what was actually measured.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from xml.etree import ElementTree

import requests

from app.schemas.trend import RawTrend

logger = logging.getLogger(__name__)

# Identifies Kairo to the services it reads, as those services ask. A
# contactable identity is a condition of the Wikimedia API's terms.
USER_AGENT = (
    "KairoVideoAgent/1.0 (local video production agent; "
    "https://github.com/Louis-kohaku/Kairo)"
)
_TIMEOUT = 12.0


class TrendSourceError(RuntimeError):
    """A source could not be read. Never fatal to a collection pass."""


@dataclass(frozen=True)
class SourceSpec:
    id: str
    label: str
    kind: str  # public_feed | official_api
    endpoint: str
    terms_url: str
    requires_key: bool = False
    key_env: str = ""
    note: str = ""


SOURCE_SPECS: tuple[SourceSpec, ...] = (
    SourceSpec(
        "google_trends",
        "Google Trends (公開RSS)",
        "public_feed",
        "https://trends.google.co.jp/trending/rss?geo={region}",
        "https://policies.google.com/terms",
        note="Googleが公開している急上昇ワードのRSSフィード。APIキー不要。",
    ),
    SourceSpec(
        "wikipedia",
        "Wikimedia Pageviews API",
        "official_api",
        "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/{project}/all-access/{date}",
        "https://www.mediawiki.org/wiki/REST_API",
        note="Wikimedia公式のページビューAPI。APIキー不要、User-Agentの明示が必要。",
    ),
    SourceSpec(
        "youtube",
        "YouTube Data API v3 (人気動画)",
        "official_api",
        "https://www.googleapis.com/youtube/v3/videos",
        "https://developers.google.com/youtube/terms/api-services-terms-of-service",
        requires_key=True,
        key_env="KAIRO_YOUTUBE_API_KEY",
        note=(
            "無料枠あり(既定10,000ユニット/日)。APIキーを .env の "
            "KAIRO_YOUTUBE_API_KEY に設定したときだけ有効になります。"
        ),
    ),
)

SPEC_BY_ID: dict[str, SourceSpec] = {s.id: s for s in SOURCE_SPECS}

# Platforms Kairo deliberately does not collect from, surfaced in the UI so
# the absence is an explained decision rather than a silent gap.
UNAVAILABLE_PLATFORMS: tuple[dict, str] = (
    {
        "id": "tiktok",
        "label": "TikTok",
        "reason": (
            "一般公開のトレンドAPIが提供されておらず、規約上スクレイピングも行えないため"
            "接続していません。Research API は審査申請が必要です。"
        ),
        "docs": "https://developers.tiktok.com/doc/about-research-api/",
    },
    {
        "id": "instagram",
        "label": "Instagram Reels",
        "reason": (
            "トレンド取得に使える公開APIがなく、Graph APIはビジネスアカウントと"
            "審査が必要なため接続していません。"
        ),
        "docs": "https://developers.facebook.com/docs/instagram-platform",
    },
)


def _get(url: str, **kwargs) -> requests.Response:
    resp = requests.get(
        url, headers={"User-Agent": USER_AGENT}, timeout=_TIMEOUT, **kwargs
    )
    if not resp.ok:
        raise TrendSourceError(f"HTTP {resp.status_code} ({url.split('?')[0]})")
    return resp


def has_key(spec: SourceSpec) -> bool:
    """Whether this source is configured to run.

    Key-less sources are always configured. A key is read from the process
    environment (.env is loaded by app.core.config) and never stored in the
    repository.
    """
    if not spec.requires_key:
        return True
    return bool(os.environ.get(spec.key_env, "").strip())


# ------------------------------------------------------------ providers

_TRAFFIC_RE = re.compile(r"([\d,\.]+)\s*([KkMm万千]?)\+?")


def _parse_traffic(text: str) -> float:
    """"20万+" / "50K+" / "1,000+" -> a float. 0.0 when unparseable."""
    match = _TRAFFIC_RE.search(text or "")
    if not match:
        return 0.0
    try:
        value = float(match.group(1).replace(",", ""))
    except ValueError:
        return 0.0
    unit = match.group(2)
    multiplier = {"K": 1e3, "k": 1e3, "M": 1e6, "m": 1e6, "万": 1e4, "千": 1e3}
    return value * multiplier.get(unit, 1.0)


def fetch_google_trends(region: str = "JP", limit: int = 30) -> list[RawTrend]:
    """Google's published trending-searches RSS for one region."""
    url = SPEC_BY_ID["google_trends"].endpoint.format(region=quote(region))
    try:
        resp = _get(url)
    except requests.RequestException as exc:
        raise TrendSourceError(f"接続できませんでした: {exc}") from exc

    try:
        root = ElementTree.fromstring(resp.content)
    except ElementTree.ParseError as exc:
        raise TrendSourceError(f"RSSを解釈できませんでした: {exc}") from exc

    ns = {"ht": "https://trends.google.com/trending/rss"}
    items = root.findall(".//item")
    if not items:
        raise TrendSourceError("RSSに項目がありませんでした")

    results: list[RawTrend] = []
    traffic_values: list[float] = []
    parsed: list[tuple[str, float, str, list[str]]] = []
    for item in items[:limit]:
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        traffic = _parse_traffic(item.findtext("ht:approx_traffic", default="", namespaces=ns))
        link = (item.findtext("link") or "").strip()
        news = [
            (n.findtext("ht:news_item_title", default="", namespaces=ns) or "").strip()
            for n in item.findall("ht:news_item", ns)
        ]
        parsed.append((title, traffic, link, [n for n in news if n][:3]))
        traffic_values.append(traffic)

    peak = max(traffic_values) if traffic_values else 0.0
    total = len(parsed)
    for rank, (title, traffic, link, news) in enumerate(parsed):
        # Traffic when the feed reports it, rank otherwise: an item with no
        # traffic figure still has a real position in the feed, and
        # inventing a volume for it would be worse than using that.
        if peak > 0 and traffic > 0:
            score = round(min(100.0, 40.0 + 60.0 * (traffic / peak)), 1)
        else:
            score = round(90.0 * (1 - rank / max(1, total)) + 10.0, 1)
        results.append(
            RawTrend(
                platform="google_trends",
                keyword=title,
                region=region,
                raw_score=traffic,
                score=score,
                source="Google Trends RSS",
                source_url=link or url,
                metadata={
                    "rank": rank + 1,
                    "approx_traffic": traffic,
                    "news_titles": news,
                },
            )
        )
    return results


_WIKI_PROJECT_BY_REGION = {"JP": "ja.wikipedia", "US": "en.wikipedia", "GB": "en.wikipedia"}
# Portal/maintenance pages dominate the raw top list and say nothing about
# what people are interested in, so they are dropped rather than ranked.
_WIKI_SKIP_PREFIXES = (
    "特別:", "Special:", "メインページ", "Main_Page", "Wikipedia:", "ファイル:",
    "File:", "Help:", "Category:", "カテゴリ:", "Portal:", "-",
)


def fetch_wikipedia(region: str = "JP", limit: int = 30) -> list[RawTrend]:
    """Yesterday's most-read articles, as a broad public-interest signal.

    Yesterday rather than today because the endpoint only publishes a day
    once it is complete; asking for today returns 404 for most of the day.
    """
    project = _WIKI_PROJECT_BY_REGION.get(region.upper(), "en.wikipedia")
    day = datetime.now(timezone.utc) - timedelta(days=1)
    url = (
        "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/"
        f"{project}/all-access/{day.year:04d}/{day.month:02d}/{day.day:02d}"
    )
    try:
        resp = _get(url)
    except requests.RequestException as exc:
        raise TrendSourceError(f"接続できませんでした: {exc}") from exc

    try:
        articles = resp.json()["items"][0]["articles"]
    except (ValueError, KeyError, IndexError) as exc:
        raise TrendSourceError(f"応答を解釈できませんでした: {exc}") from exc

    kept = [
        a
        for a in articles
        if not str(a.get("article", "")).startswith(_WIKI_SKIP_PREFIXES)
    ][:limit]
    if not kept:
        raise TrendSourceError("有効な記事が返りませんでした")

    peak = max(float(a.get("views", 0)) for a in kept) or 1.0
    lang = project.split(".")[0]
    results: list[RawTrend] = []
    for a in kept:
        article = str(a.get("article", ""))
        views = float(a.get("views", 0))
        results.append(
            RawTrend(
                platform="wikipedia",
                keyword=article.replace("_", " "),
                region=region,
                raw_score=views,
                score=round(min(100.0, 30.0 + 70.0 * (views / peak)), 1),
                source=f"Wikimedia Pageviews ({project})",
                source_url=f"https://{lang}.wikipedia.org/wiki/{quote(article)}",
                metadata={"rank": a.get("rank"), "views": views, "date": day.date().isoformat()},
            )
        )
    return results


# YouTube's numeric category ids, so a video's own classification can be
# passed to the genre classifier as a hint instead of guessed from the title.
_YT_CATEGORY_NAMES = {
    "1": "映画 アニメ", "2": "自動車", "10": "音楽", "15": "ペット 動物",
    "17": "スポーツ", "19": "旅行 travel", "20": "ゲーム gaming",
    "22": "vlog 日常", "23": "コメディ お笑い", "24": "エンタメ",
    "25": "ニュース news", "26": "howto 使い方", "27": "教育 education",
    "28": "テクノロジー tech",
}


def fetch_youtube(region: str = "JP", limit: int = 30) -> list[RawTrend]:
    """YouTube's own most-popular chart, via the official Data API.

    Only runs when the user has put a key in ``KAIRO_YOUTUBE_API_KEY``.
    Kairo never ships a key and never falls back to scraping youtube.com.
    """
    spec = SPEC_BY_ID["youtube"]
    key = os.environ.get(spec.key_env, "").strip()
    if not key:
        raise TrendSourceError(
            f"APIキーが未設定です（.env の {spec.key_env} に設定すると有効になります）"
        )

    params = {
        "part": "snippet,statistics",
        "chart": "mostPopular",
        "regionCode": region,
        "maxResults": str(min(50, max(1, limit))),
        "key": key,
    }
    try:
        resp = requests.get(
            spec.endpoint,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise TrendSourceError(f"接続できませんでした: {exc}") from exc
    if resp.status_code in (401, 403):
        raise TrendSourceError(
            "APIキーが拒否されました（キーの有効性とYouTube Data API v3の有効化を確認してください）"
        )
    if not resp.ok:
        raise TrendSourceError(f"HTTP {resp.status_code}")

    try:
        items = resp.json().get("items", [])
    except ValueError as exc:
        raise TrendSourceError(f"応答を解釈できませんでした: {exc}") from exc
    if not items:
        raise TrendSourceError("人気動画が返りませんでした")

    views = [float(i.get("statistics", {}).get("viewCount", 0) or 0) for i in items]
    peak = max(views) or 1.0
    results: list[RawTrend] = []
    for item, view_count in zip(items, views):
        snippet = item.get("snippet", {})
        title = str(snippet.get("title", "")).strip()
        if not title:
            continue
        category_id = str(snippet.get("categoryId", ""))
        results.append(
            RawTrend(
                platform="youtube",
                keyword=title,
                region=region,
                raw_score=view_count,
                score=round(min(100.0, 35.0 + 65.0 * (view_count / peak)), 1),
                source="YouTube Data API v3 (mostPopular)",
                source_url=f"https://www.youtube.com/watch?v={item.get('id', '')}",
                category_hint=_YT_CATEGORY_NAMES.get(category_id, ""),
                metadata={
                    "channel": snippet.get("channelTitle", ""),
                    "published_at": snippet.get("publishedAt", ""),
                    "view_count": view_count,
                    "like_count": item.get("statistics", {}).get("likeCount"),
                    "tags": (snippet.get("tags") or [])[:8],
                    "category_id": category_id,
                },
            )
        )
    return results


PROVIDERS = {
    "google_trends": fetch_google_trends,
    "wikipedia": fetch_wikipedia,
    "youtube": fetch_youtube,
}


def fetch(source_id: str, region: str, limit: int = 30) -> list[RawTrend]:
    provider = PROVIDERS.get(source_id)
    if provider is None:
        raise TrendSourceError(f"未知のトレンド取得元です: {source_id}")
    return provider(region=region, limit=limit)
