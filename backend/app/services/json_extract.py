"""Shared helper for pulling a JSON object out of an LLM's raw text reply.

Local models frequently wrap JSON in markdown fences or add stray prose
despite instructions not to - this is the one place that tolerance lives,
so every LLM-JSON call site (AI-edit, production planning/scripting)
handles it the same way.
"""
from __future__ import annotations

import json
import re
from typing import Any


class JSONExtractionError(ValueError):
    pass


def extract_json_text(text: str) -> str:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        return fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        return json.loads(extract_json_text(text))
    except json.JSONDecodeError as exc:
        raise JSONExtractionError(f"JSONとして解釈できませんでした: {text[:300]}") from exc
