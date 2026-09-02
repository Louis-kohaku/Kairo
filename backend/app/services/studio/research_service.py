"""Web research as a production input, not a search screen (section 16).

The flow is: build queries from the user's brief -> search -> fetch a
handful of results -> hand the extracted text to the local model -> get
back a structured TrendReport that later stages consume. Nothing here is
shown as "search results"; the output is an analysis of *how* videos on
this subject are usually built.

Two rules shape the implementation.

**Nothing is copied.** Section 18: the report separates what everyone does
(`common_patterns`) from where this video will differ
(`differentiation`), and the fetched text is used to infer structure,
pacing and phrasing conventions - never sentences to reuse.

**The network is untrusted.** Everything reached here is an address that
came out of a search engine, so `_is_safe_url` rejects non-HTTP schemes and
anything that resolves to a private, loopback, link-local or reserved
address before a request is made (SSRF: this backend sits on a LAN
alongside LM Studio and the user's own devices). Responses are capped in
size, decoded defensively, and stripped to text; no fetched byte ever
reaches a shell, a file path, or an ffmpeg argument.

Research is also entirely optional. Offline, blocked, or simply
unproductive, the stage returns `performed=False` with a reason and the
pipeline continues - a video that cannot be researched is still a video.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
import time
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, urlparse

import requests
from pydantic import ValidationError

from app.schemas.studio import ResearchResult, ResearchSource, TrendReport
from app.services import llm_client
from app.services.json_extract import JSONExtractionError, parse_json_object

logger = logging.getLogger(__name__)

# DuckDuckGo's no-JavaScript endpoint: no API key, no account, and a stable
# HTML shape. Kairo stays local-first; this is the one outbound call the
# product makes, it is opt-out, and it sends only the search query.
_SEARCH_ENDPOINT = "https://html.duckduckgo.com/html/"
_USER_AGENT = "Mozilla/5.0 (compatible; KairoResearch/1.0; local video studio)"

_SEARCH_TIMEOUT = 12.0
_FETCH_TIMEOUT = 10.0
_MAX_BYTES = 400_000  # per page; enough for article text, bounded for safety
_MAX_TEXT_CHARS = 1_200  # per page, handed to the model
# Total corpus sizes tried, largest first. LM Studio loads a model with its
# own n_ctx (commonly 8192) regardless of the model's advertised maximum,
# and there is no API that reports the *loaded* context length - so rather
# than guess, the analysis starts small and steps down on an overflow.
# Japanese runs close to one token per character, so these are roughly
# token counts too.
_CORPUS_SIZES = (3_500, 1_800, 900)
_MAX_FETCH = 6


class ResearchUnavailable(RuntimeError):
    """Research could not run. Never fatal - the caller reports and moves on."""


# ------------------------------------------------------------ URL safety


_BLOCKED_SCHEMES = ("file", "ftp", "data", "javascript", "gopher")


def _is_safe_url(url: str) -> tuple[bool, str]:
    """Whether it is safe to issue a GET for this URL.

    Resolves the hostname and rejects any address that is private,
    loopback, link-local, multicast or otherwise reserved, so a crafted or
    poisoned search result cannot make Kairo probe the user's own network
    (LM Studio on :1234, a router admin page, a NAS).
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "URLを解釈できません"

    if parsed.scheme in _BLOCKED_SCHEMES:
        return False, f"許可されていないスキームです: {parsed.scheme}"
    if parsed.scheme not in ("http", "https"):
        return False, "http/https以外のURLは取得しません"
    host = parsed.hostname
    if not host:
        return False, "ホスト名がありません"

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False, "ホスト名を解決できません"

    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False, "IPアドレスを解釈できません"
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False, "内部ネットワーク宛のURLは取得しません"
    return True, ""


# ---------------------------------------------------------- HTML -> text


class _TextExtractor(HTMLParser):
    """Minimal readable-text extraction.

    A dedicated parser (bs4/readability) would be better, but adding a
    dependency for one optional stage is a poor trade; this drops script,
    style and nav content, which is enough for the model to infer format
    conventions from.
    """

    _SKIP = {"script", "style", "noscript", "svg", "head", "nav", "footer", "form"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title and not self.title:
            self.title = text[:200]
        self.parts.append(text)

    def text(self) -> str:
        joined = " ".join(self.parts)
        return re.sub(r"\s+", " ", joined).strip()


def _extract_text(html: str) -> tuple[str, str]:
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:  # malformed markup shouldn't sink the stage
        logger.debug("HTML parse failed; using raw strip")
        stripped = re.sub(r"<[^>]+>", " ", html)
        return "", re.sub(r"\s+", " ", unescape(stripped)).strip()[:_MAX_TEXT_CHARS]
    return parser.title, parser.text()[:_MAX_TEXT_CHARS]


# ------------------------------------------------------------- searching

_RESULT_RE = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL
)
_SNIPPET_RE = re.compile(
    r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', re.DOTALL
)


def _clean(fragment: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


def _unwrap_redirect(href: str) -> str:
    """DuckDuckGo wraps results as /l/?uddg=<encoded target>."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg")
        if target:
            return target[0]
    return href


def search(query: str, limit: int = 10) -> list[ResearchSource]:
    """Runs one search and returns candidate sources (not yet fetched)."""
    url = f"{_SEARCH_ENDPOINT}?q={quote_plus(query)}"
    try:
        resp = requests.get(
            url, headers={"User-Agent": _USER_AGENT}, timeout=_SEARCH_TIMEOUT
        )
    except requests.RequestException as exc:
        raise ResearchUnavailable(f"検索サービスに接続できませんでした: {exc}") from exc
    if not resp.ok:
        raise ResearchUnavailable(f"検索がHTTP {resp.status_code} を返しました")

    html = resp.text
    snippets = [_clean(s) for s in _SNIPPET_RE.findall(html)]
    sources: list[ResearchSource] = []
    for i, (href, title_html) in enumerate(_RESULT_RE.findall(html)):
        target = _unwrap_redirect(href)
        ok, _reason = _is_safe_url(target)
        if not ok:
            continue
        sources.append(
            ResearchSource(
                title=_clean(title_html)[:200],
                url=target,
                snippet=(snippets[i] if i < len(snippets) else "")[:400],
                fetched=False,
            )
        )
        if len(sources) >= limit:
            break
    return sources


def fetch_page(url: str) -> str:
    """Downloads one page and returns its readable text, or "" on failure."""
    ok, reason = _is_safe_url(url)
    if not ok:
        logger.info("Skipping unsafe research URL %s: %s", url, reason)
        return ""
    try:
        with requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_FETCH_TIMEOUT,
            stream=True,
        ) as resp:
            if not resp.ok:
                return ""
            content_type = resp.headers.get("Content-Type", "")
            if "html" not in content_type and "text" not in content_type:
                return ""
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_content(16_384):
                chunks.append(chunk)
                total += len(chunk)
                if total >= _MAX_BYTES:
                    break
            raw = b"".join(chunks)
        html = raw.decode(resp.encoding or "utf-8", errors="replace")
    except requests.RequestException:
        return ""
    _title, text = _extract_text(html)
    return text


# ------------------------------------------------------------- analysis


def _build_query_prompt(instruction: str) -> list[dict]:
    system = (
        "あなたは動画制作のリサーチャーです。ユーザーの動画制作依頼から、"
        "参考になる動画の作り方を調べるための検索クエリを日本語で3つ作ってください。"
        "JSONオブジェクトのみを出力してください。\n\n"
        '出力形式: {"queries": ["...", "...", "..."]}\n\n'
        "クエリは「どんな構成・見せ方が定番か」を調べる目的にしてください。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": instruction},
    ]


def _build_analysis_prompt(instruction: str, corpus: str) -> list[dict]:
    system = (
        "あなたは動画フォーマットのアナリストです。与えられた参考テキストから、"
        "このテーマの動画で一般的な作り方(共通トレンド)と、"
        "他と差をつけられる余地(差別化機会)を分けて抽出してください。\n\n"
        "重要な制約:\n"
        "- 参考テキストの文章をそのまま使わないこと。表現や構成の傾向だけを抽象化すること。\n"
        "- 事実が不明な項目は空配列/nullにすること。推測で埋めないこと。\n"
        "- JSONオブジェクトのみを出力すること。\n\n"
        "出力形式:\n"
        '{"common_patterns": ["..."], "differentiation": ["..."], '
        '"typical_duration_seconds": 45, "typical_scene_seconds": 3.0, '
        '"hook_patterns": ["..."], "subtitle_patterns": ["..."], '
        '"audio_patterns": ["..."], "ending_patterns": ["..."], "notes": "..."}'
    )
    user = f"動画制作の依頼:\n{instruction}\n\n参考テキスト(抜粋):\n{corpus}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _fallback_trends(instruction: str) -> TrendReport:
    """What Kairo knows about short-form structure without any research.

    Used when the network or the model is unavailable. These are format
    conventions, not findings, and `notes` says so - the alternative would
    be an empty strategy that produces a shapeless video.
    """
    return TrendReport(
        query=instruction[:120],
        common_patterns=[
            "冒頭2〜3秒で被写体と状況を提示する",
            "1シーン2〜4秒程度でテンポよく切り替える",
            "画面中央〜下部に短く大きな字幕を置く",
            "音は軽めのBGM + 場面に合った効果音",
            "最後に一言のオチや余韻を置く",
        ],
        differentiation=[
            "ありがちな展開を1箇所だけ裏切る",
            "字幕の言い回しに固有のトーンを持たせる",
            "終わり方を冒頭につながる形にしてループさせる",
        ],
        typical_duration_seconds=45.0,
        typical_scene_seconds=3.0,
        hook_patterns=["結論・見どころを先に見せる", "動きのある瞬間から始める"],
        subtitle_patterns=["1行10〜16文字程度", "短く区切る"],
        audio_patterns=["BGMは控えめ", "変化点に効果音"],
        ending_patterns=["オチ", "余韻", "ループ"],
        notes="Webリサーチを実行できなかったため、ショート動画の一般的な定石を使用しています。",
    )


def build_queries(instruction: str) -> list[str]:
    try:
        raw = llm_client.chat_completion(_build_query_prompt(instruction), temperature=0.3)
        data = parse_json_object(raw)
        queries = [str(q) for q in data.get("queries", []) if str(q).strip()]
        if queries:
            return queries[:3]
    except (
        JSONExtractionError,
        llm_client.LLMUnavailableError,
        llm_client.LLMTimeoutError,
        llm_client.LLMResponseError,
    ):
        logger.info("Query generation failed; using the instruction as the query")
    except Exception:
        logger.exception("Unexpected failure building research queries")
    # The user's own words are a perfectly good query.
    return [instruction[:120]]


def run_research(
    instruction: str,
    *,
    enabled: bool = True,
    max_sources: int = _MAX_FETCH,
    on_progress=None,
) -> ResearchResult:
    """Full research pass. Never raises: an unusable network is a reported
    outcome, not a failed production."""
    if not enabled:
        return ResearchResult(
            performed=False,
            skipped_reason="設定によりWebリサーチを行わない指定になっています。",
            trends=_fallback_trends(instruction),
        )

    def report(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    queries = build_queries(instruction)
    report(f"検索クエリを作成しました: {queries[0]}")

    sources: list[ResearchSource] = []
    seen: set[str] = set()
    for query in queries:
        try:
            for source in search(query, limit=8):
                if source.url in seen:
                    continue
                seen.add(source.url)
                sources.append(source)
        except ResearchUnavailable as exc:
            if not sources:
                return ResearchResult(
                    performed=False,
                    skipped_reason=str(exc),
                    queries=queries,
                    trends=_fallback_trends(instruction),
                )
            break
        if len(sources) >= max_sources * 2:
            break

    if not sources:
        return ResearchResult(
            performed=False,
            skipped_reason="検索結果を取得できませんでした。",
            queries=queries,
            trends=_fallback_trends(instruction),
        )

    report(f"{len(sources)}件の候補から上位{min(max_sources, len(sources))}件を分析します")

    corpus_parts: list[str] = []
    for source in sources[:max_sources]:
        text = fetch_page(source.url)
        if text:
            source.fetched = True
            corpus_parts.append(f"# {source.title}\n{text}")
            report(f"参照中: {source.title[:40]}")
        # Politeness delay: this is someone else's server.
        time.sleep(0.3)

    if not corpus_parts:
        # Search worked, pages didn't - the snippets are still real signal.
        corpus_parts = [f"{s.title}: {s.snippet}" for s in sources[:max_sources]]

    corpus = "\n\n".join(corpus_parts)[:12_000]

    try:
        raw = llm_client.chat_completion(
            _build_analysis_prompt(instruction, corpus), temperature=0.2
        )
        data = parse_json_object(raw)
        trends = TrendReport.model_validate({**data, "query": queries[0]})
    except (JSONExtractionError, ValidationError):
        logger.info("Trend analysis returned unusable JSON; using format defaults")
        trends = _fallback_trends(instruction)
        trends.notes = (
            "参照ページの取得はできましたが、AIの分析結果を解釈できなかったため、"
            "ショート動画の一般的な定石を使用しています。"
        )
    except Exception as exc:  # noqa: BLE001 - research must not fail a run
        logger.exception("Trend analysis failed")
        trends = _fallback_trends(instruction)
        trends.notes = f"分析に失敗したため一般的な定石を使用しています ({exc})."

    return ResearchResult(
        performed=True,
        queries=queries,
        sources=sources[:max_sources],
        trends=trends,
    )


def _is_context_overflow(exc: Exception) -> bool:
    text = str(exc).lower()
    return "context length" in text or "n_ctx" in text or "too long" in text


def _analyze(instruction: str, corpus: str, query: str, report) -> TrendReport:
    """Runs the trend analysis, shrinking the corpus until it fits.

    A context overflow is not a failure of the analysis - it means we sent
    too much - so it is retried with less material before falling back to
    format defaults.
    """
    last_error: Exception | None = None
    for size in _CORPUS_SIZES:
        chunk = corpus[:size]
        try:
            raw = llm_client.chat_completion(
                _build_analysis_prompt(instruction, chunk), temperature=0.2
            )
            data = parse_json_object(raw)
            return TrendReport.model_validate({**data, "query": query})
        except (JSONExtractionError, ValidationError) as exc:
            # Bad JSON won't improve with less input; stop retrying.
            logger.info("Trend analysis returned unusable JSON: %s", exc)
            trends = _fallback_trends(instruction)
            trends.notes = (
                "参照ページの取得はできましたが、AIの分析結果を解釈できなかったため、"
                "ショート動画の一般的な定石を使用しています。"
            )
            return trends
        except Exception as exc:  # noqa: BLE001 - research must not fail a run
            last_error = exc
            if _is_context_overflow(exc) and size != _CORPUS_SIZES[-1]:
                report(f"参照テキストが長すぎたため、{size}文字に縮めて再分析します")
                continue
            logger.exception("Trend analysis failed")
            break

    trends = _fallback_trends(instruction)
    detail = f" ({last_error})" if last_error else ""
    trends.notes = f"AIによる分析ができなかったため、一般的な定石を使用しています。{detail}"
    return trends


def to_json(result: ResearchResult) -> str:
    return json.dumps(result.model_dump(), ensure_ascii=False)
