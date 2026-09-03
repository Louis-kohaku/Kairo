"""Finding licence-checkable stock material on the web.

This exists to serve one narrow position in the material priority order:
when the user's own photos and videos do not cover a beat, and before
falling back to something Kairo draws itself, look for a real photograph
whose licence is explicitly stated.

Two sources are queried, in order: Openverse (the Creative Commons search
index) and Wikimedia Commons. Both are used rather than a general image
search for exactly one reason: every result carries a machine-readable
licence, so "ライセンスを確認できるWeb素材" is a property of the data and not
a hope. Results whose licence Kairo does not recognise are discarded, and
the licence and source page are stored on the asset so the finished video
can say where each shot came from.

Having two matters in practice: which of them a given network can reach
varies, and a source that times out should cost the user nothing more than
the other source being used.

Everything here is best-effort and offline-safe. No network, a rate limit,
a dead endpoint or a result that will not download all produce the same
outcome: `search()` returns nothing, the caller moves down the priority
order, and the run reports honestly that no web material was used.
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import requests

from app.core.paths import assets_dir
from app.services.studio.research_service import _is_safe_url

logger = logging.getLogger(__name__)

_API = "https://api.openverse.org/v1/images/"
_COMMONS_API = "https://commons.wikimedia.org/w/api.php"
_TIMEOUT = 12.0
_DOWNLOAD_TIMEOUT = 25.0
_MAX_BYTES = 25 * 1024 * 1024
_USER_AGENT = "Kairo/0.1 (local video tool; +https://github.com/)"

# Licences whose terms allow use with attribution, which is what the
# completion screen records. Anything else - including "unknown" - is
# dropped rather than used and hoped about.
_ALLOWED_LICENSES = {"cc0", "pdm", "by", "by-sa", "by-nc", "by-nc-sa"}

_CONTENT_TYPE_SUFFIX = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


@dataclass
class WebMaterial:
    title: str
    url: str
    source_page: str
    license_code: str
    license_url: str
    creator: str
    width: int | None
    height: int | None
    provider: str = "Openverse"

    @property
    def attribution(self) -> str:
        parts = [self.title or "(無題)"]
        if self.creator:
            parts.append(f"by {self.creator}")
        if self.license_code:
            parts.append(self.license_code.upper())
        parts.append(self.provider)
        return " / ".join(parts)


class WebMaterialUnavailable(RuntimeError):
    """No web material could be obtained, with the reason to show the user."""


def _query_for(keywords: list[str]) -> str:
    words = [w.strip() for w in keywords if w and w.strip()]
    return " ".join(words[:4])


def search(keywords: list[str], *, limit: int = 5, orientation: str = "") -> list[WebMaterial]:
    """Licence-filtered image results, or an empty list if none can be had.

    Sources are tried in order and the first that answers wins; a source
    that is unreachable simply contributes nothing.
    """
    words = [w.strip() for w in keywords if w and w.strip()]
    if not words:
        return []

    # Widen the query until something comes back. A stock index ANDs its
    # terms, so the four most specific words from a scene description
    # usually match nothing at all - while the first one or two ("砂浜",
    # "海") match plenty. Starting narrow keeps the best result when there
    # is one; falling back is what stops a gap being filled with an
    # abstract background merely because the prompt was wordy.
    for take in (4, 2, 1):
        query = " ".join(words[:take])
        if not query:
            continue
        results = _search_openverse(query, limit, orientation)
        if results:
            return results
        results = _search_commons(query, limit)
        if results:
            return results
        if take >= len(words):
            # Already searched every word we have; narrower steps would
            # just repeat the same query.
            continue
    return []


# Licence strings Wikimedia Commons reports that Kairo will use. Matched
# case-insensitively as a prefix, so "CC BY-SA 4.0" and "CC BY-SA 3.0" both
# pass while "Fair use" and any non-free tag do not.
_COMMONS_LICENSE_PREFIXES = ("cc0", "cc by", "cc-by", "public domain", "pd-")


def _search_commons(query: str, limit: int) -> list[WebMaterial]:
    """Wikimedia Commons file search, licence-filtered."""
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"file: {query}",
        "gsrnamespace": "6",
        "gsrlimit": str(max(1, min(limit * 3, 20))),
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|size|mime",
        "iiurlwidth": "1600",
    }
    try:
        resp = requests.get(
            _COMMONS_API, params=params, timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT}
        )
    except requests.RequestException as exc:
        logger.info("Wikimedia Commons search failed: %s", exc)
        return []
    if not resp.ok:
        logger.info("Wikimedia Commons search returned %s", resp.status_code)
        return []

    try:
        pages = (resp.json().get("query") or {}).get("pages") or {}
    except ValueError:
        return []

    materials: list[WebMaterial] = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        license_name = str((meta.get("LicenseShortName") or {}).get("value") or "")
        low = license_name.lower()
        if not any(low.startswith(prefix) for prefix in _COMMONS_LICENSE_PREFIXES):
            continue
        mime = str(info.get("mime") or "")
        if mime not in ("image/jpeg", "image/png", "image/webp"):
            continue
        # The scaled rendition, so a 4000px original is not downloaded to
        # fill a 1080-wide frame.
        url = info.get("thumburl") or info.get("url") or ""
        if not url:
            continue
        ok, _reason = _is_safe_url(url)
        if not ok:
            continue
        creator = re.sub(
            r"<[^>]+>", "", str((meta.get("Artist") or {}).get("value") or "")
        ).strip()
        materials.append(
            WebMaterial(
                title=str(page.get("title") or "").replace("File:", "")[:120],
                url=url,
                source_page=info.get("descriptionurl") or "",
                license_code=license_name,
                license_url=str((meta.get("LicenseUrl") or {}).get("value") or ""),
                creator=creator[:80],
                width=info.get("thumbwidth") or info.get("width"),
                height=info.get("thumbheight") or info.get("height"),
                provider="Wikimedia Commons",
            )
        )
        if len(materials) >= limit:
            break
    return materials


def _search_openverse(query: str, limit: int, orientation: str) -> list[WebMaterial]:
    params: dict[str, str | int] = {
        "q": query,
        "page_size": max(1, min(limit * 3, 20)),
        "license_type": "all-cc",
        "mature": "false",
    }
    if orientation == "vertical":
        params["aspect_ratio"] = "tall"
    elif orientation == "horizontal":
        params["aspect_ratio"] = "wide"

    try:
        resp = requests.get(
            _API, params=params, timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT}
        )
    except requests.RequestException as exc:
        logger.info("Openverse search failed: %s", exc)
        return []
    if not resp.ok:
        logger.info("Openverse search returned %s", resp.status_code)
        return []

    try:
        payload = resp.json()
    except ValueError:
        return []

    materials: list[WebMaterial] = []
    for item in payload.get("results", []) or []:
        license_code = str(item.get("license") or "").lower()
        if license_code not in _ALLOWED_LICENSES:
            continue
        url = item.get("url") or ""
        if not url:
            continue
        ok, _reason = _is_safe_url(url)
        if not ok:
            continue
        materials.append(
            WebMaterial(
                title=str(item.get("title") or "")[:120],
                url=url,
                source_page=str(item.get("foreign_landing_url") or ""),
                license_code=license_code,
                license_url=str(item.get("license_url") or ""),
                creator=str(item.get("creator") or "")[:80],
                width=item.get("width"),
                height=item.get("height"),
            )
        )
        if len(materials) >= limit:
            break
    return materials


def download(material: WebMaterial, project_id: str) -> Path:
    """Fetches one result into the project's assets directory.

    Raises `WebMaterialUnavailable` with a user-readable reason rather than
    returning a half-written file, so the caller can fall through to the
    next source in the priority order and say why.
    """
    ok, reason = _is_safe_url(material.url)
    if not ok:
        raise WebMaterialUnavailable(f"取得できないURLでした: {reason}")

    try:
        with requests.get(
            material.url,
            timeout=_DOWNLOAD_TIMEOUT,
            stream=True,
            headers={"User-Agent": _USER_AGENT},
        ) as resp:
            if not resp.ok:
                raise WebMaterialUnavailable(
                    f"Web素材のダウンロードに失敗しました (HTTP {resp.status_code})。"
                )
            content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            suffix = _CONTENT_TYPE_SUFFIX.get(content_type)
            if suffix is None:
                guessed = Path(re.sub(r"\?.*$", "", material.url)).suffix.lower()
                suffix = guessed if guessed in (".jpg", ".jpeg", ".png", ".webp") else None
            if suffix is None:
                raise WebMaterialUnavailable(
                    f"対応していない画像形式でした（{content_type or '不明'}）。"
                )

            dest_dir = assets_dir(project_id)
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"web_{uuid.uuid4().hex[:10]}{suffix}"

            written = 0
            with dest.open("wb") as out:
                for chunk in resp.iter_content(chunk_size=256 * 1024):
                    written += len(chunk)
                    if written > _MAX_BYTES:
                        out.close()
                        dest.unlink(missing_ok=True)
                        raise WebMaterialUnavailable("Web素材のファイルサイズが大きすぎました。")
                    out.write(chunk)
    except requests.RequestException as exc:
        raise WebMaterialUnavailable(f"Web素材を取得できませんでした: {exc}") from exc

    if not dest.exists() or dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        raise WebMaterialUnavailable("Web素材のダウンロード結果が空でした。")
    return dest


# Reachability is cached because the material plan is rebuilt every time
# the start screen refreshes, and an unreachable source costs the full
# timeout each time. Five minutes is long enough that the start screen
# stays responsive and short enough that plugging the network back in is
# noticed without a restart.
_REACHABLE_TTL = 300.0
_reachable_cache: tuple[float, bool] | None = None


def is_reachable(*, force: bool = False) -> bool:
    """Whether any web material source can be used right now.

    Called when building the material plan so the "補完方法" the user
    confirms lists only sources that actually work in this environment,
    rather than promising a web search that will silently turn into a
    generated image.
    """
    global _reachable_cache
    now = time.monotonic()
    if not force and _reachable_cache is not None and now - _reachable_cache[0] < _REACHABLE_TTL:
        return _reachable_cache[1]

    ok = False
    for probe in (
        (_API, {"q": "sky", "page_size": 1}),
        (_COMMONS_API, {"action": "query", "format": "json", "meta": "siteinfo"}),
    ):
        try:
            resp = requests.get(
                probe[0], params=probe[1], timeout=5.0, headers={"User-Agent": _USER_AGENT}
            )
        except requests.RequestException:
            continue
        if resp.ok:
            ok = True
            break
    _reachable_cache = (now, ok)
    return ok
