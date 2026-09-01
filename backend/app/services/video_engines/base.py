"""Shared interface every video-generation engine implements.

This is intentionally the smallest contract that both today's engine
(SVD, image-to-video only) and future engines (text-to-video,
video-to-video, GPU-accelerated backends) can satisfy, so
`video_generation_service.py` and the API layer never need to know which
concrete engine is running.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

# (percent 0-100, human-readable Japanese status message)
ProgressCallback = Callable[[float, str], None]


@dataclass(frozen=True)
class EngineCapabilities:
    id: str
    display_name: str
    supports_text_to_video: bool = False
    supports_image_to_video: bool = False
    supports_video_to_video: bool = False
    # Whether a text prompt actually influences the generated motion/content.
    # SVD, for example, only conditions on the input image - a prompt field
    # shown next to it in the UI would be misleading unless this is True.
    prompt_conditioned: bool = False
    approx_download_gb: float = 0.0
    min_ram_gb: float = 0.0
    recommended_ram_gb: float = 0.0
    license: str = ""
    commercial_use: bool = False
    notes: str = ""


@dataclass
class GenerationResult:
    output_path: Path
    width: int
    height: int
    duration_seconds: float
    fps: float
    engine_id: str
    elapsed_seconds: float


class VideoGenerationEngine(ABC):
    capabilities: EngineCapabilities

    @abstractmethod
    def is_model_downloaded(self) -> bool:
        """Whether the weights are already on disk (no network needed)."""

    @abstractmethod
    def estimate_duration_seconds(self, **params) -> tuple[float, float]:
        """(low, high) wall-clock estimate for the given params on this
        machine. Callers must present this as an estimate, never a
        guarantee (section 15 of the design doc)."""

    def generate_image_to_video(
        self,
        image_path: Path,
        output_path: Path,
        prompt: str = "",
        progress_cb: Optional[ProgressCallback] = None,
        **params,
    ) -> GenerationResult:
        raise NotImplementedError(f"{self.capabilities.id} does not support image-to-video")

    def generate_text_to_video(
        self,
        prompt: str,
        output_path: Path,
        progress_cb: Optional[ProgressCallback] = None,
        **params,
    ) -> GenerationResult:
        raise NotImplementedError(f"{self.capabilities.id} does not support text-to-video")
