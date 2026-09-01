"""Pluggable local video-generation backends.

Kairo never hardcodes a single video generation model. Every engine
implements the same `VideoGenerationEngine` interface (base.py), so a
better free/local model can be swapped in later (or an Intel-GPU /
Apple-Silicon-accelerated backend added) without touching the API,
job runner, or UI that call into `get_engine()`.

Engines are looked up by id and instantiated lazily - importing this
module must never import torch/diffusers at module load time, since
those are heavy optional dependencies (see backend/requirements-videogen.txt)
that most Kairo installs may not have installed.
"""
from __future__ import annotations

from app.services.video_engines.base import (
    EngineCapabilities,
    GenerationResult,
    VideoGenerationEngine,
)

# id -> (capabilities, factory). The factory is only called (and only then
# imports torch/diffusers) when an engine is actually used.
_REGISTRY: dict[str, tuple[EngineCapabilities, "type[VideoGenerationEngine] | None"]] = {}

_engine_instances: dict[str, VideoGenerationEngine] = {}


def _register_svd() -> None:
    from app.services.video_engines.svd_engine import SVDEngine

    _REGISTRY["svd"] = (SVDEngine.capabilities, SVDEngine)


def list_capabilities() -> list[EngineCapabilities]:
    """Capability metadata for every known engine, without loading any of
    them. Safe to call even if torch/diffusers are not installed."""
    if not _REGISTRY:
        # Registering only defines capability dataclasses + a class ref;
        # SVDEngine's module-level code itself does not import torch.
        _register_svd()
    return [caps for caps, _cls in _REGISTRY.values()]


def get_engine(engine_id: str) -> VideoGenerationEngine:
    if engine_id not in _engine_instances:
        if not _REGISTRY:
            _register_svd()
        if engine_id not in _REGISTRY:
            raise KeyError(f"Unknown video generation engine: {engine_id}")
        _caps, cls = _REGISTRY[engine_id]
        if cls is None:
            raise RuntimeError(f"Engine {engine_id} has no implementation registered")
        _engine_instances[engine_id] = cls()
    return _engine_instances[engine_id]


__all__ = [
    "EngineCapabilities",
    "GenerationResult",
    "VideoGenerationEngine",
    "list_capabilities",
    "get_engine",
]
