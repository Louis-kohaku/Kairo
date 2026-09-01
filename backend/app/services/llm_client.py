"""Client for a local, OpenAI-compatible chat completions server.

LM Studio (the AI backend this project targets) exposes exactly this API
shape when its local server is enabled, so no LM Studio-specific SDK is
needed - this same client works against any compatible local server,
keeping the "LLM backend is swappable" requirement intact.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import requests

from app.core.config import LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT


class LLMUnavailableError(RuntimeError):
    pass


class LLMResponseError(RuntimeError):
    pass


# Error codes a preflight check classifies LM Studio's state into. "OK"
# means the app's configured model was actually found among the models
# LM Studio currently has loaded - anything else means a chat completion
# would very likely fail, and the specific code tells the user why instead
# of a single generic "モデルがロードされていません" message.
ERROR_CONNECTION_FAILED = "LM_STUDIO_CONNECTION_FAILED"
ERROR_MODELS_FETCH_FAILED = "MODELS_FETCH_FAILED"
ERROR_MODEL_NOT_LOADED = "MODEL_NOT_LOADED"
ERROR_MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
ERROR_MODEL_ID_MISMATCH = "MODEL_ID_MISMATCH"
ERROR_OK = "OK"

# Values KAIRO_LLM_MODEL is known to take as a stand-in rather than a real
# LM Studio model id - e.g. this app's own shipped default. Never reported
# to the user as if it were an actual model LM Studio should have loaded.
PLACEHOLDER_MODEL_NAMES = {"local-model", "default", "placeholder", ""}


def is_placeholder_model(model_id: str) -> bool:
    return model_id.strip().lower() in PLACEHOLDER_MODEL_NAMES


@dataclass
class LLMStatus:
    """Separates "can we reach LM Studio" from "can we actually generate
    with it" - a server that is up but has no model loaded answers /models
    fine (server_reachable=True, api_ok=True) yet every chat completion
    will fail, so `can_generate` must be checked independently of the other
    two flags rather than inferred from them.

    `error_code`/`ready` go one step further: they classify *why*
    generation would (or wouldn't) succeed with the app's *specific*
    configured model, so the UI never has to guess from a generic error.
    `can_generate` is kept as the looser "is any model loaded at all"
    signal used by places (system info, the status badge) that only care
    about the LLM pipeline in general, not this exact model id.
    """

    server_reachable: bool
    api_ok: bool
    models_loaded: list[str] = field(default_factory=list)
    configured_model: str = LLM_MODEL
    configured_model_loaded: bool = False
    can_generate: bool = False
    base_url: str = LLM_BASE_URL
    is_placeholder_model: bool = False
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
    placeholder = is_placeholder_model(LLM_MODEL)

    try:
        resp = requests.get(f"{LLM_BASE_URL.rstrip('/')}/models", timeout=3)
    except requests.RequestException as exc:
        return LLMStatus(
            server_reachable=False,
            api_ok=False,
            is_placeholder_model=placeholder,
            error_code=ERROR_CONNECTION_FAILED,
            connection_error=str(exc),
        )

    if not resp.ok:
        return LLMStatus(
            server_reachable=True,
            api_ok=False,
            is_placeholder_model=placeholder,
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
            is_placeholder_model=placeholder,
            error_code=ERROR_MODELS_FETCH_FAILED,
            connection_error=f"/models の応答を解釈できませんでした: {exc}",
        )

    configured_model_loaded = LLM_MODEL in models_loaded

    if not models_loaded:
        error_code = ERROR_MODEL_NOT_LOADED
    elif configured_model_loaded:
        error_code = ERROR_OK
    elif placeholder:
        error_code = ERROR_MODEL_ID_MISMATCH
    else:
        error_code = ERROR_MODEL_NOT_FOUND

    return LLMStatus(
        server_reachable=True,
        api_ok=True,
        models_loaded=models_loaded,
        configured_model_loaded=configured_model_loaded,
        # Loose gate, kept only for the general "is the LLM pipeline usable
        # at all" signal: LM Studio dispatches to whatever is loaded even
        # when the "model" field doesn't match exactly, so "some model is
        # loaded" alone can still mean *some* chat completion would work.
        # `ready` below is the strict gate for "this app's configured
        # model specifically will work" and is what preflight checks use.
        can_generate=len(models_loaded) > 0,
        is_placeholder_model=placeholder,
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


def chat_completion(messages: list[dict], temperature: float = 0.2) -> str:
    url = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"
    payload = {"model": LLM_MODEL, "messages": messages, "temperature": temperature}

    try:
        resp = requests.post(url, json=payload, timeout=LLM_TIMEOUT)
    except requests.RequestException as exc:
        raise LLMUnavailableError(
            f"LM Studioに接続できません ({LLM_BASE_URL})。"
            "LM Studioを起動し、ローカルサーバーを有効にしてください。"
        ) from exc

    if not resp.ok:
        raise LLMResponseError(f"LM Studioがエラーを返しました ({resp.status_code}): {resp.text[:300]}")

    try:
        body = resp.json()
        return body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError) as exc:
        raise LLMResponseError(f"LM Studioからの応答を解釈できませんでした: {resp.text[:300]}") from exc
