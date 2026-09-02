"""Local persistence for Kairo's user settings (design doc sections 38-40).

Stored as a single JSON file under DATA_ROOT - never uploaded or synced
anywhere. This is a single-user local desktop app, so a plain
read-modify-write with no locking is sufficient (matches the "local-only,
no external server" requirement more directly than adding a DB table +
migration would).
"""
from __future__ import annotations

import json
import threading

from app.core.config import DATA_ROOT
from app.schemas.settings import AppSettings, AppSettingsPatch

SETTINGS_PATH = DATA_ROOT / "settings.json"

_lock = threading.Lock()


def _read() -> AppSettings:
    if not SETTINGS_PATH.exists():
        return AppSettings()
    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return AppSettings()
    try:
        return AppSettings.model_validate(raw)
    except Exception:
        # A corrupt/old-shape settings file must never crash the app - fall
        # back to defaults rather than 500ing every request that reads it.
        return AppSettings()


def _write(settings: AppSettings) -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(settings.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_settings() -> AppSettings:
    with _lock:
        return _read()


def update_settings(patch: AppSettingsPatch) -> AppSettings:
    with _lock:
        current = _read()

        if patch.ai is not None:
            if patch.ai.mode is not None:
                current.ai.mode = patch.ai.mode
            if patch.ai.clear_selected_model:
                current.ai.selected_model = None
            elif patch.ai.selected_model is not None:
                current.ai.selected_model = patch.ai.selected_model

        if patch.video is not None:
            for field in (
                "aspect_ratio",
                "width",
                "height",
                "fps",
                "quality_preset",
                "duration_seconds",
            ):
                value = getattr(patch.video, field)
                if value is not None:
                    setattr(current.video, field, value)

        if patch.performance is not None:
            if patch.performance.profile is not None:
                current.performance.profile = patch.performance.profile
            if patch.performance.custom is not None:
                current.performance.custom = patch.performance.custom

        if patch.tts is not None:
            if patch.tts.mode is not None:
                current.tts.mode = patch.tts.mode
            if patch.tts.clear_selected_voice:
                current.tts.selected_voice = None
            elif patch.tts.selected_voice is not None:
                current.tts.selected_voice = patch.tts.selected_voice

        if patch.subtitle is not None:
            for field in ("enabled", "font", "size", "position", "color", "style"):
                value = getattr(patch.subtitle, field)
                if value is not None:
                    setattr(current.subtitle, field, value)

        if patch.generation is not None:
            if patch.generation.parallelism is not None:
                current.generation.parallelism = patch.generation.parallelism
            if patch.generation.cache_enabled is not None:
                current.generation.cache_enabled = patch.generation.cache_enabled
            if patch.generation.clear_default_engine_id:
                current.generation.default_engine_id = None
            elif patch.generation.default_engine_id is not None:
                current.generation.default_engine_id = patch.generation.default_engine_id

        _write(current)
        return current


def reset_settings() -> AppSettings:
    with _lock:
        defaults = AppSettings()
        _write(defaults)
        return defaults
