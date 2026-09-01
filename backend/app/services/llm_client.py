"""Client for a local, OpenAI-compatible chat completions server.

LM Studio (the AI backend this project targets) exposes exactly this API
shape when its local server is enabled, so no LM Studio-specific SDK is
needed - this same client works against any compatible local server,
keeping the "LLM backend is swappable" requirement intact.
"""
from __future__ import annotations

import requests

from app.core.config import LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT


class LLMUnavailableError(RuntimeError):
    pass


class LLMResponseError(RuntimeError):
    pass


def is_available() -> bool:
    try:
        resp = requests.get(f"{LLM_BASE_URL.rstrip('/')}/models", timeout=3)
        return resp.ok
    except requests.RequestException:
        return False


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
