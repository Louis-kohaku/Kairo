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


@dataclass
class LLMStatus:
    """Separates "can we reach LM Studio" from "can we actually generate
    with it" - a server that is up but has no model loaded answers /models
    fine (server_reachable=True, api_ok=True) yet every chat completion
    will fail, so `can_generate` must be checked independently of the other
    two flags rather than inferred from them.
    """

    server_reachable: bool
    api_ok: bool
    models_loaded: list[str] = field(default_factory=list)
    configured_model: str = LLM_MODEL
    configured_model_loaded: bool = False
    can_generate: bool = False
    base_url: str = LLM_BASE_URL


def is_available() -> bool:
    try:
        resp = requests.get(f"{LLM_BASE_URL.rstrip('/')}/models", timeout=3)
        return resp.ok
    except requests.RequestException:
        return False


def get_status() -> LLMStatus:
    try:
        resp = requests.get(f"{LLM_BASE_URL.rstrip('/')}/models", timeout=3)
    except requests.RequestException:
        return LLMStatus(server_reachable=False, api_ok=False)

    if not resp.ok:
        return LLMStatus(server_reachable=True, api_ok=False)

    try:
        data = resp.json().get("data", [])
        models_loaded = [m["id"] for m in data if isinstance(m, dict) and "id" in m]
    except (ValueError, AttributeError, TypeError):
        return LLMStatus(server_reachable=True, api_ok=False)

    return LLMStatus(
        server_reachable=True,
        api_ok=True,
        models_loaded=models_loaded,
        configured_model_loaded=LLM_MODEL in models_loaded,
        # Loose gate: LM Studio's server dispatches to whatever is loaded
        # even when the "model" field in the request doesn't match it
        # exactly, so "some model is loaded" is the real precondition for
        # a chat completion to have a chance of succeeding - an exact-name
        # mismatch is reported as a fact (configured_model_loaded) but does
        # not by itself mean generation is impossible.
        can_generate=len(models_loaded) > 0,
    )


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
