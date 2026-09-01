"""Stable Video Diffusion (img2vid) engine.

First real local video-generation backend wired into Kairo. Runs entirely
on CPU via PyTorch/diffusers (no CUDA, no cloud). Loaded lazily and cached
in-process, mirroring whisper_service.py's pattern for the other large
model this app holds in memory.

Important, verified-by-testing limitation: SVD's img2vid pipeline has no
text encoder at all - it conditions purely on the input image plus
motion_bucket_id/fps/noise_aug_strength. A `prompt` argument is accepted
for interface compatibility with other engines but is intentionally
ignored here; `capabilities.prompt_conditioned = False` is what the API/UI
use to warn the user instead of silently pretending the prompt did
something.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Optional

from app.core.config import MODELS_ROOT
from app.services.video_engines.base import (
    EngineCapabilities,
    GenerationResult,
    ProgressCallback,
    VideoGenerationEngine,
)

logger = logging.getLogger(__name__)

MODEL_ID = "stabilityai/stable-video-diffusion-img2vid"


class SVDEngine(VideoGenerationEngine):
    capabilities = EngineCapabilities(
        id="svd",
        display_name="Stable Video Diffusion (img2vid)",
        supports_image_to_video=True,
        prompt_conditioned=False,
        approx_download_gb=9.5,
        min_ram_gb=12.0,
        recommended_ram_gb=24.0,
        license="Stable Video Diffusion Non-Commercial Research Community License",
        commercial_use=False,
        notes=(
            "テキストプロンプトには対応していません(入力画像と動きの強さのみで生成されます)。"
            "非商用ライセンスのため商用利用不可。CPU実行のみ対応(GPUアクセラレーションは未実装)。"
        ),
    )

    def __init__(self) -> None:
        self._pipe = None
        self._lock = threading.Lock()

    def is_model_downloaded(self) -> bool:
        try:
            from huggingface_hub import scan_cache_dir
        except ImportError:
            return False
        try:
            cache_info = scan_cache_dir(str(MODELS_ROOT))
        except Exception:
            return False
        return any(repo.repo_id == MODEL_ID for repo in cache_info.repos)

    # seconds-per-step scales roughly linearly with (num_frames * width *
    # height) - this constant is fitted from two real measured runs on the
    # Intel Core Ultra 7 155H / 32GB reference machine (see README
    # "実機検証" section): 47s/step at 8 frames/384x256, 135s/step at 14
    # frames/512x320 (predicted 137s from this formula - within 2%).
    _SECONDS_PER_STEP_PER_PIXEL_FRAME = 5.976e-5

    def estimate_duration_seconds(self, **params) -> tuple[float, float]:
        num_frames = params.get("num_frames", 14)
        steps = params.get("num_inference_steps", 15)
        width = params.get("width", 512)
        height = params.get("height", 320)
        seconds_per_step = self._SECONDS_PER_STEP_PER_PIXEL_FRAME * num_frames * width * height
        est = steps * seconds_per_step
        # This is a rough model fitted from two data points on one machine,
        # not a guarantee - actual time depends on other running processes,
        # thermals, and how different your CPU is from the reference one.
        # Presented as a range for exactly that reason (design doc section 15).
        return round(est * 0.7, 1), round(est * 1.6, 1)

    def _load_pipeline(self, progress_cb: Optional[ProgressCallback] = None):
        if self._pipe is not None:
            return self._pipe
        with self._lock:
            if self._pipe is not None:
                return self._pipe
            if progress_cb:
                progress_cb(3.0, "モデルを読み込み中(初回はダウンロードが発生します。数GB単位です)")
            import torch
            from diffusers import StableVideoDiffusionPipeline

            pipe = StableVideoDiffusionPipeline.from_pretrained(
                MODEL_ID,
                torch_dtype=torch.float32,
                cache_dir=str(MODELS_ROOT),
            )
            pipe.to("cpu")
            self._pipe = pipe
            if progress_cb:
                progress_cb(10.0, "モデルの読み込み完了")
            return pipe

    def generate_image_to_video(
        self,
        image_path: Path,
        output_path: Path,
        prompt: str = "",
        progress_cb: Optional[ProgressCallback] = None,
        **params,
    ) -> GenerationResult:
        if prompt:
            logger.info(
                "SVDEngine: prompt %r was supplied but is ignored - "
                "this model is not text-conditioned",
                prompt,
            )

        import imageio
        import torch
        from PIL import Image

        width = int(params.get("width", 512))
        height = int(params.get("height", 320))
        num_frames = int(params.get("num_frames", 14))
        steps = int(params.get("num_inference_steps", 15))
        fps = float(params.get("fps", 7))
        motion_bucket_id = int(params.get("motion_bucket_id", 127))
        noise_aug_strength = float(params.get("noise_aug_strength", 0.02))
        seed = params.get("seed")

        pipe = self._load_pipeline(progress_cb)
        image = Image.open(image_path).convert("RGB").resize((width, height))

        generator = None
        if seed is not None:
            generator = torch.Generator(device="cpu").manual_seed(int(seed))

        if progress_cb:
            progress_cb(15.0, f"推論を開始します(CPU / {steps}ステップ / {num_frames}フレーム)")

        start = time.time()
        result = pipe(
            image,
            height=height,
            width=width,
            num_frames=num_frames,
            num_inference_steps=steps,
            fps=int(fps),
            motion_bucket_id=motion_bucket_id,
            noise_aug_strength=noise_aug_strength,
            generator=generator,
        )
        elapsed = time.time() - start
        self._measured_seconds_per_step = elapsed / max(steps, 1)

        frames = result.frames[0]

        if progress_cb:
            progress_cb(92.0, "mp4に書き出し中")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        writer_kwargs = {"fps": fps, "codec": "libx264", "quality": 8}
        imageio.mimsave(str(output_path), frames, **writer_kwargs)

        if progress_cb:
            progress_cb(100.0, "完了")

        return GenerationResult(
            output_path=output_path,
            width=width,
            height=height,
            duration_seconds=num_frames / fps,
            fps=fps,
            engine_id=self.capabilities.id,
            elapsed_seconds=elapsed,
        )
