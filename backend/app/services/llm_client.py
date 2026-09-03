"""Client for a local, OpenAI-compatible chat completions server.

LM Studio (the AI backend this project targets) exposes exactly this API
shape when its local server is enabled, so no LM Studio-specific SDK is
needed - this same client works against any compatible local server,
keeping the "LLM backend is swappable" requirement intact.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Literal

import requests

from app.core.config import LLM_BASE_URL, LLM_MODEL_ENV, LLM_TIMEOUT

logger = logging.getLogger(__name__)


class LLMUnavailableError(RuntimeError):
    pass


class LLMTimeoutError(RuntimeError):
    """The server accepted the request but did not answer in time.

    Kept separate from LLMUnavailableError because the two need opposite
    advice: an unreachable server means "start LM Studio", while a timeout
    means the model is running but too slowly for the current limit - and
    reporting the second as the first sends the user to check something
    that is already working.
    """


class LLMResponseError(RuntimeError):
    pass


class LLMModelCrashedError(LLMResponseError):
    """LM Studio reported that the model itself died.

    A subclass of LLMResponseError so every existing `except
    LLMResponseError` keeps catching it - the pipeline's optional stages
    must go on treating it as "this stage could not run", not as something
    new they fail on.
    """


# Error codes a preflight check classifies LM Studio's state into. "OK"
# means the resolved model was actually found among the models LM Studio
# currently has loaded - anything else means a chat completion would very
# likely fail, and the specific code tells the user why instead of a single
# generic "モデルがロードされていません" message.
ERROR_CONNECTION_FAILED = "LM_STUDIO_CONNECTION_FAILED"
ERROR_MODELS_FETCH_FAILED = "MODELS_FETCH_FAILED"
ERROR_MODEL_NOT_LOADED = "MODEL_NOT_LOADED"
ERROR_MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
ERROR_OK = "OK"

ModelSource = Literal["env", "user", "auto", "fallback", "none"]


@dataclass
class ResolvedModel:
    model_id: str | None
    source: ModelSource
    reason: str


# Substrings identifying embedding/reranker models, which are commonly kept
# loaded in LM Studio alongside a chat model (e.g. for RAG) but cannot serve
# chat completions. Auto/fallback selection must never pick one of these as
# "the model" - an explicit env/Manual choice is left alone since that is
# the user's deliberate pick, not Kairo guessing.
_NON_CHAT_MODEL_MARKERS = ("embed", "rerank", "bge-", "gte-", "e5-small", "e5-large", "e5-base")


def _is_chat_capable(model_id: str) -> bool:
    low = model_id.lower()
    return not any(marker in low for marker in _NON_CHAT_MODEL_MARKERS)


def resolve_model(available_models: list[str]) -> ResolvedModel:
    """Model selection priority (design doc section 4): explicit env var ->
    user's Manual choice (persisted in settings) -> PC-based Auto
    recommendation -> first model LM Studio actually has loaded. Never
    falls back to a fake placeholder id like the old "local-model" default -
    `source="none"` means there is genuinely nothing usable yet, and the
    caller (get_status) is responsible for surfacing that clearly."""
    if LLM_MODEL_ENV:
        if LLM_MODEL_ENV in available_models:
            return ResolvedModel(LLM_MODEL_ENV, "env", "環境変数 KAIRO_LLM_MODEL で指定されたモデルです。")
        return ResolvedModel(
            LLM_MODEL_ENV, "env",
            "環境変数 KAIRO_LLM_MODEL で指定されていますが、LM Studioには見つかりません。",
        )

    # Deferred imports: settings_service/ai_recommendation_service sit
    # "above" llm_client in the dependency graph (ai_recommendation_service
    # -> system_info_service -> llm_client), so importing them at module
    # load time would create a circular import. By call time every module
    # involved has already finished loading.
    from app.services import settings_service

    settings = settings_service.get_settings()
    if settings.ai.mode == "manual" and settings.ai.selected_model:
        chosen = settings.ai.selected_model
        if chosen in available_models:
            return ResolvedModel(chosen, "user", "設定でManual選択されたモデルです。")
        return ResolvedModel(
            chosen, "user", "設定でManual選択されていますが、LM Studioには見つかりません。"
        )

    chat_models = [m for m in available_models if _is_chat_capable(m)]

    # Text generation is what this model is being resolved *for* - scripts,
    # scene design, reviews. A vision model does that job more slowly than a
    # text-only model of the same size because it carries an image encoder,
    # and `vision_model()` resolves the image-analysis model independently,
    # so nothing is lost by setting VLMs aside when a text-only model is
    # also loaded.
    text_only = [m for m in chat_models if not is_vision_model(m)]
    preferred = text_only or chat_models
    vision_deferred = bool(text_only) and len(text_only) < len(chat_models)

    if preferred:
        from app.services import ai_recommendation_service

        rec = ai_recommendation_service.recommend_model(preferred)
        note = (
            "（画像対応モデルは素材解析用に温存し、文章生成にはテキスト専用モデルを使います）"
            if vision_deferred
            else ""
        )
        if rec.get("recommended_model_id"):
            return ResolvedModel(
                rec["recommended_model_id"], "auto", "; ".join(rec["reasons"]) + note
            )
        return ResolvedModel(
            preferred[0],
            "fallback",
            "PC性能に適した既知のモデルとは一致しませんでしたが、"
            "LM Studioにロードされているモデルを使用します。" + note,
        )

    if available_models:
        # Only embedding/reranker models are loaded - nothing here can serve
        # a chat completion, so this is reported the same as "no model" is,
        # rather than silently handing chat requests to an embedding model.
        return ResolvedModel(
            None, "none",
            "LM Studioにはモデルがロードされていますが、チャット生成に使えるモデルがありません"
            "(埋め込み/リランク用モデルのみ検出されました)。",
        )

    return ResolvedModel(None, "none", "LM Studioに利用可能なモデルがありません。")


@dataclass
class LLMStatus:
    """Separates "can we reach LM Studio" from "can we actually generate
    with it" - a server that is up but has no model loaded answers /models
    fine (server_reachable=True, api_ok=True) yet every chat completion
    will fail, so `can_generate` must be checked independently of the other
    two flags rather than inferred from them.

    `error_code`/`ready` go one step further: they classify *why*
    generation would (or wouldn't) succeed with the *resolved* model (see
    `resolve_model`), so the UI never has to guess from a generic error.
    `model_source`/`resolution_reason` say *how* that model was chosen
    (env override / user's Manual pick / Auto recommendation / fallback),
    which is what the AI settings UI's "なぜ？" explanation is built from.
    """

    server_reachable: bool
    api_ok: bool
    models_loaded: list[str] = field(default_factory=list)
    configured_model: str | None = None
    configured_model_loaded: bool = False
    model_source: ModelSource = "none"
    resolution_reason: str = ""
    can_generate: bool = False
    base_url: str = LLM_BASE_URL
    error_code: str = ERROR_CONNECTION_FAILED
    ready: bool = False
    connection_error: str | None = None


def is_available() -> bool:
    try:
        resp = requests.get(f"{LLM_BASE_URL.rstrip('/')}/models", timeout=3)
        return resp.ok
    except requests.RequestException:
        return False


def get_status() -> LLMStatus:
    try:
        resp = requests.get(f"{LLM_BASE_URL.rstrip('/')}/models", timeout=3)
    except requests.RequestException as exc:
        return LLMStatus(
            server_reachable=False,
            api_ok=False,
            error_code=ERROR_CONNECTION_FAILED,
            connection_error=str(exc),
        )

    if not resp.ok:
        return LLMStatus(
            server_reachable=True,
            api_ok=False,
            error_code=ERROR_MODELS_FETCH_FAILED,
            connection_error=f"/models がHTTP {resp.status_code} を返しました",
        )

    try:
        data = resp.json().get("data", [])
        models_loaded = [m["id"] for m in data if isinstance(m, dict) and "id" in m]
    except (ValueError, AttributeError, TypeError) as exc:
        return LLMStatus(
            server_reachable=True,
            api_ok=False,
            error_code=ERROR_MODELS_FETCH_FAILED,
            connection_error=f"/models の応答を解釈できませんでした: {exc}",
        )

    resolved = resolve_model(models_loaded)

    if not models_loaded or resolved.model_id is None:
        # Either nothing is loaded at all, or only non-chat models
        # (embedding/reranker) are - either way nothing can currently serve
        # a chat completion, which is what ERROR_MODEL_NOT_LOADED means to
        # the UI (see resolve_model's _is_chat_capable filtering).
        return LLMStatus(
            server_reachable=True,
            api_ok=True,
            models_loaded=models_loaded,
            configured_model=resolved.model_id,
            model_source=resolved.source,
            resolution_reason=resolved.reason,
            can_generate=False,
            error_code=ERROR_MODEL_NOT_LOADED,
            ready=False,
        )

    configured_model_loaded = resolved.model_id in models_loaded
    error_code = ERROR_OK if configured_model_loaded else ERROR_MODEL_NOT_FOUND

    return LLMStatus(
        server_reachable=True,
        api_ok=True,
        models_loaded=models_loaded,
        configured_model=resolved.model_id,
        configured_model_loaded=configured_model_loaded,
        model_source=resolved.source,
        resolution_reason=resolved.reason,
        can_generate=True,
        error_code=error_code,
        ready=error_code == ERROR_OK,
    )


class LLMNotReadyError(RuntimeError):
    """Raised by preflight checks (see app.services.llm_preflight) before a
    chat completion is even attempted, so a doomed request never has to run
    to produce a diagnosis - `status.error_code` says exactly why."""

    def __init__(self, status: LLMStatus):
        self.status = status
        super().__init__(status.error_code)


# Substrings identifying models that accept images alongside text. LM
# Studio exposes no capability flag on /v1/models, so the model id is the
# only signal available - and guessing wrong in the permissive direction is
# what produces a confusing 400 halfway through an analysis. The list is
# therefore deliberately conservative: an unlisted vision model is reported
# as "no vision model loaded", which degrades to metadata analysis rather
# than failing.
_VISION_MODEL_MARKERS = (
    "vl",           # qwen2-vl, qwen2.5-vl, internvl
    "vision",
    "llava",
    "bakllava",
    "moondream",
    "minicpm-v",
    "pixtral",
    "gemma-3",      # Gemma 3 is multimodal from 4B up
    "phi-3.5-vision",
    "phi-4-multimodal",
    "idefics",
    "cogvlm",
)


def is_vision_model(model_id: str) -> bool:
    low = (model_id or "").lower()
    return any(marker in low for marker in _VISION_MODEL_MARKERS)


def vision_model() -> str | None:
    """The loaded model that can look at an image, if there is one.

    Prefers the model already resolved for text work when it happens to be
    multimodal, so a single loaded VLM serves both jobs without a reload.
    """
    status = get_status()
    if status.configured_model and is_vision_model(status.configured_model):
        return status.configured_model
    for model_id in status.models_loaded:
        if is_vision_model(model_id):
            return model_id
    return None


def vision_completion(
    prompt: str,
    images: list[tuple[str, bytes]],
    *,
    model_id: str | None = None,
    temperature: float = 0.1,
    system: str = "",
) -> str:
    """Asks a loaded vision model what is in one or more images.

    `images` are (mime_type, raw_bytes) pairs, sent as data URLs in the
    OpenAI-compatible `image_url` content parts LM Studio accepts. Raises
    LLMUnavailableError when no vision model is loaded - the caller is
    expected to fall back to metadata analysis and *say* that it did,
    rather than presenting a guess as an AI result.
    """
    import base64

    resolved = model_id or vision_model()
    if not resolved:
        raise LLMUnavailableError(
            "画像を解析できるAIモデル（Vision対応モデル）がLM Studioにロードされていません。"
        )

    content: list[dict] = [{"type": "text", "text": prompt}]
    for mime, blob in images:
        encoded = base64.b64encode(blob).decode("ascii")
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}
        )

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": content})

    payload = {"model": resolved, "messages": messages, "temperature": temperature}
    resp = _post_completion(payload, what="画像解析モデル", model_id=resolved)

    try:
        return resp.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError) as exc:
        raise LLMResponseError(
            f"画像解析の応答を解釈できませんでした: {resp.text[:300]}"
        ) from exc


# LM Studio drops in-flight requests when it swaps a model (JIT loading, or
# an idle model being unloaded and reloaded). It reports that as a 400 with
# this body, which is indistinguishable from a client error by status code
# alone - hence the body match. It is transient: the next request succeeds.
_RELOAD_MARKERS = ("model reloaded", "model unloaded", "model is loading", "loading model")
# 5xx from a local inference server is the same kind of "ask again" condition.
_TRANSIENT_STATUSES = (500, 502, 503, 504)
# A crashed model is a different thing from a reloading one: it will not
# answer the next request either, so it is reported rather than retried.
_CRASH_MARKERS = ("has crashed", "model crashed", "exit code")
# One retry, not a loop. If the second attempt fails the same way, something
# is actually wrong and burning another full timeout would only delay saying so.
_MAX_TRANSIENT_RETRIES = 1
# Long enough for LM Studio to finish swapping a model in, short enough that
# a user watching the progress log does not think it has hung.
_RETRY_BACKOFF_SECONDS = 3.0


def _is_transient_response(resp: requests.Response) -> bool:
    if resp.status_code in _TRANSIENT_STATUSES:
        return True
    if resp.status_code == 400:
        body = (resp.text or "").casefold()
        return any(marker in body for marker in _RELOAD_MARKERS)
    return False


def _post_completion(payload: dict, *, what: str, model_id: str) -> requests.Response:
    """POSTs one chat completion, retrying only genuinely transient failures.

    A timeout is deliberately *not* retried: the wait already cost
    LLM_TIMEOUT seconds, and a second one would double a failure the user is
    waiting on rather than fixing it. Reloads and connection resets are
    retried, because for those the next attempt really does succeed.
    """
    url = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"
    attempt = 0
    while True:
        try:
            resp = requests.post(url, json=payload, timeout=LLM_TIMEOUT)
        except requests.Timeout as exc:
            raise LLMTimeoutError(
                f"{what}「{model_id}」からの応答が{LLM_TIMEOUT:.0f}秒以内に返りませんでした。"
            ) from exc
        except requests.ConnectionError as exc:
            # LM Studio restarting, or the server toggled off mid-request.
            if attempt < _MAX_TRANSIENT_RETRIES:
                attempt += 1
                logger.info(
                    "LM Studio connection dropped (%s); retrying once in %.0fs",
                    exc,
                    _RETRY_BACKOFF_SECONDS,
                )
                time.sleep(_RETRY_BACKOFF_SECONDS)
                continue
            raise LLMUnavailableError(
                f"LM Studioに接続できません ({LLM_BASE_URL})。"
                "LM Studioを起動し、ローカルサーバーを有効にしてください。"
            ) from exc
        except requests.RequestException as exc:
            raise LLMUnavailableError(
                f"LM Studioに接続できません ({LLM_BASE_URL})。"
                "LM Studioを起動し、ローカルサーバーを有効にしてください。"
            ) from exc

        if resp.ok:
            return resp

        if _is_transient_response(resp) and attempt < _MAX_TRANSIENT_RETRIES:
            attempt += 1
            logger.info(
                "LM Studio returned a transient %s (%s); retrying once in %.0fs",
                resp.status_code,
                (resp.text or "")[:120],
                _RETRY_BACKOFF_SECONDS,
            )
            time.sleep(_RETRY_BACKOFF_SECONDS)
            continue

        detail = (resp.text or "")[:300]
        body = (resp.text or "").casefold()
        if any(marker in body for marker in _CRASH_MARKERS):
            raise LLMModelCrashedError(
                f"AIモデル「{model_id}」がLM Studio側でクラッシュしました。"
                "メモリ不足の可能性があります（動画の書き出しと同時に大きなモデルを"
                "動かすと発生しやすくなります）。LM Studioでモデルを読み込み直すか、"
                f"より小さいモデルに切り替えてください。 詳細: {detail}"
            )
        if _is_transient_response(resp):
            raise LLMResponseError(
                f"LM Studioがモデルの再読み込み中で応答できませんでした ({resp.status_code})。"
                "再試行しても同じ状態でした。LM Studioでモデルがロード済みか確認してください。"
                f" 詳細: {detail}"
            )
        raise LLMResponseError(f"LM Studioがエラーを返しました ({resp.status_code}): {detail}")


def chat_completion(messages: list[dict], temperature: float = 0.2) -> str:
    # Resolved fresh on every call (not a module-level constant) so a model
    # switched in LM Studio, or an AI setting changed in Kairo's UI, takes
    # effect on the very next request without a restart.
    status = get_status()
    model_id = status.configured_model or ""

    payload = {"model": model_id, "messages": messages, "temperature": temperature}
    resp = _post_completion(payload, what="AIモデル", model_id=model_id)

    try:
        body = resp.json()
        return body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError) as exc:
        raise LLMResponseError(f"LM Studioからの応答を解釈できませんでした: {resp.text[:300]}") from exc
