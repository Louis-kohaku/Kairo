"""Optional diffusion-model scene visuals.

Only reachable once the user has downloaded a Stable Diffusion checkpoint
into Kairo's model root - `image_engines.get_engine("sd")` refuses before
that, so nothing here ever starts a multi-gigabyte download on its own
(design doc section 12).

torch/diffusers are imported inside the functions, never at module import
time, for the same reason `video_engines` does it: they are heavy optional
dependencies and importing this module must stay free.
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import MODELS_ROOT

logger = logging.getLogger(__name__)

id = "sd"

_pipeline = None


def is_available() -> bool:
    try:
        import diffusers  # noqa: F401
        import torch  # noqa: F401
    except Exception:
        return False
    return True


def _load_pipeline():
    global _pipeline
    if _pipeline is not None:
        return _pipeline

    import torch
    from diffusers import StableDiffusionPipeline

    # `local_files_only` keeps this honest: if the weights are not already
    # on disk this raises instead of quietly pulling several GB.
    _pipeline = StableDiffusionPipeline.from_pretrained(
        "stabilityai/stable-diffusion-2-1-base",
        cache_dir=str(MODELS_ROOT),
        local_files_only=True,
        torch_dtype=torch.float32,
        safety_checker=None,
    )
    _pipeline.set_progress_bar_config(disable=True)
    return _pipeline


def _build_prompt(spec) -> str:
    bits = [spec.visual_prompt]
    if spec.emotion:
        bits.append(spec.emotion)
    if spec.camera:
        bits.append(spec.camera)
    bits.append("cinematic lighting, high detail, shallow depth of field")
    return ", ".join(b for b in bits if b)


def render(spec, width: int, height: int, dest: Path) -> Path:
    """Generates one scene key frame. Falls back to the procedural composer
    on any failure rather than aborting a production, because a missing
    frame would stop the whole run for a purely optional upgrade."""
    try:
        pipe = _load_pipeline()
        # SD works in multiples of 8 and degrades badly far from its
        # training resolution, so generate at a sane size and let the clip
        # builder scale to the project's frame.
        gen_w, gen_h = (512, 896) if height > width else (896, 512)
        image = pipe(
            _build_prompt(spec),
            width=gen_w - gen_w % 8,
            height=gen_h - gen_h % 8,
            num_inference_steps=22,
            guidance_scale=7.0,
        ).images[0]
        image = image.resize((width, height))
        dest.parent.mkdir(parents=True, exist_ok=True)
        image.save(dest, format="PNG")
        return dest
    except Exception:
        logger.exception("SD scene render failed; falling back to procedural composer")
        from app.services.image_engines import procedural

        return procedural.render_scene_image(spec, width, height, dest)


def describe() -> dict:
    return {
        "id": "sd",
        "display_name": "Stable Diffusion (拡散モデル)",
        "provider": "Kairo Local / diffusers",
        "needs_download": True,
        "notes": "CPUのみの環境では1枚あたり数分かかります。",
    }
