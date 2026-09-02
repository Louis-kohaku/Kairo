"""Loads Kairo's recommended-model catalog (design doc section 11) from
app/data/model_catalog.json - kept as data rather than hardcoded Python so
entries can be added/tuned without a code change.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "model_catalog.json"

QualityTier = Literal["light", "standard", "high"]


class ModelCatalogEntry(BaseModel):
    id: str
    display_name: str
    purpose: str
    size_gb: float
    quant: str
    min_ram_gb: float
    recommended_ram_gb: float
    min_vram_gb: float
    context_length: int
    quality_tier: QualityTier
    speed_tier: str
    tier_label: str
    match_keywords: list[str] = []

    def matches(self, available_model_id: str) -> bool:
        lowered = available_model_id.lower()
        return any(kw.lower() in lowered for kw in self.match_keywords)


@lru_cache(maxsize=1)
def load_catalog() -> list[ModelCatalogEntry]:
    try:
        raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = []
    for item in raw.get("models", []):
        try:
            entries.append(ModelCatalogEntry.model_validate(item))
        except Exception:
            continue
    return entries


def find_match(available_model_id: str) -> ModelCatalogEntry | None:
    for entry in load_catalog():
        if entry.matches(available_model_id):
            return entry
    return None
