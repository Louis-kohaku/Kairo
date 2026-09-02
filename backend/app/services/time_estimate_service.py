"""Processing time estimates (design doc sections 15/35-37).

Every estimate returned to the UI is a labelled (low, high) range, never a
single number presented as a guarantee. Where enough local history exists
for a similar task, the range is narrowed using actually-measured times on
*this* machine instead of the generic per-engine formula alone - purely
local, nothing is ever sent anywhere.
"""
from __future__ import annotations

import json
import statistics

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.perf_record import PerfRecord
from app.services import system_info_service, video_engines

MIN_HISTORY_SAMPLES = 3
RESOLUTION_TOLERANCE = 0.2  # +/-20% pixel count counts as "similar"


def record_generation(
    engine_id: str, width: int, height: int, num_frames: int, fps: float, elapsed_seconds: float
) -> None:
    _record(
        task_type="image_to_video",
        engine_id=engine_id,
        width=width,
        height=height,
        fps=fps,
        num_frames=num_frames,
        elapsed_seconds=elapsed_seconds,
    )


def record_production(target_duration_minutes: float, elapsed_seconds: float, model_id: str | None) -> None:
    _record(
        task_type="production",
        model_id=model_id,
        duration_seconds_requested=target_duration_minutes * 60,
        elapsed_seconds=elapsed_seconds,
    )


def _record(**fields) -> None:
    db: Session = SessionLocal()
    try:
        ram_gb = system_info_service.get_ram_info()["total_gb"]
        gpu_names = system_info_service.get_gpu_info().get("names") or []
        db.add(PerfRecord(ram_gb=ram_gb, gpu_names=json.dumps(gpu_names, ensure_ascii=False), **fields))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _similar_generation_samples(engine_id: str, width: int, height: int) -> list[float]:
    db: Session = SessionLocal()
    try:
        rows = (
            db.query(PerfRecord)
            .filter(PerfRecord.task_type == "image_to_video", PerfRecord.engine_id == engine_id)
            .order_by(PerfRecord.created_at.desc())
            .limit(50)
            .all()
        )
    finally:
        db.close()

    target_pixels = width * height
    samples = []
    for row in rows:
        if not row.width or not row.height:
            continue
        pixels = row.width * row.height
        if abs(pixels - target_pixels) / target_pixels <= RESOLUTION_TOLERANCE:
            samples.append(row.elapsed_seconds)
    return samples


def _production_samples() -> list[float]:
    db: Session = SessionLocal()
    try:
        rows = (
            db.query(PerfRecord)
            .filter(PerfRecord.task_type == "production")
            .order_by(PerfRecord.created_at.desc())
            .limit(50)
            .all()
        )
    finally:
        db.close()
    return [r.elapsed_seconds for r in rows]


def _range_from_samples(samples: list[float]) -> tuple[float, float] | None:
    if len(samples) < MIN_HISTORY_SAMPLES:
        return None
    mean = statistics.mean(samples)
    stdev = statistics.pstdev(samples) if len(samples) > 1 else mean * 0.2
    low = max(mean - stdev, mean * 0.5)
    high = mean + stdev
    return round(low, 1), round(high, 1)


def estimate_generation(engine_id: str, width: int, height: int, num_frames: int, num_inference_steps: int) -> tuple[tuple[float, float], bool]:
    samples = _similar_generation_samples(engine_id, width, height)
    ranged = _range_from_samples(samples)
    if ranged:
        return ranged, True

    try:
        engine = video_engines.get_engine(engine_id)
        low, high = engine.estimate_duration_seconds(
            width=width, height=height, num_frames=num_frames, num_inference_steps=num_inference_steps
        )
        return (low, high), False
    except Exception:
        return (60.0, 600.0), False


def estimate_production(target_duration_minutes: float) -> tuple[tuple[float, float], bool]:
    samples = _production_samples()
    ranged = _range_from_samples(samples)
    if ranged:
        return ranged, True

    # No history yet: a rough heuristic based on chapter count (roughly one
    # chapter per 2 minutes of target video, per production_service's own
    # duration-per-chapter logic) and ~15-40s per LLM call on a typical
    # local model.
    n_chapters = max(1, round(target_duration_minutes / 2))
    low = n_chapters * 20
    high = n_chapters * 60 + 30
    return (float(low), float(high)), False


# Kairo's image-to-video generation always runs at one of these fixed,
# CPU-realistic parameter sets (see api/generation.py's own lightweight
# defaults) regardless of the project's final output resolution - a scene
# gets upscaled/composited at render time, it is not generated at 1080p/4K
# directly. Estimating generation time from the *project's* resolution
# would wildly overstate it (e.g. a 1080x1920 target does not mean SVD
# itself runs at that size), so the estimate uses these instead.
_QUALITY_GENERATION_PARAMS = {
    "fast": {"width": 384, "height": 256, "num_frames": 6, "num_inference_steps": 8},
    "standard": {"width": 384, "height": 256, "num_frames": 8, "num_inference_steps": 10},
    "high": {"width": 512, "height": 320, "num_frames": 14, "num_inference_steps": 15},
    "ultra": {"width": 512, "height": 320, "num_frames": 14, "num_inference_steps": 25},
    "custom": {"width": 384, "height": 256, "num_frames": 8, "num_inference_steps": 10},
}


def estimate_total(duration_seconds: float, quality_preset: str = "standard", engine_id: str = "svd") -> dict:
    target_minutes = duration_seconds / 60
    (p_low, p_high), p_history = estimate_production(target_minutes)

    params = _QUALITY_GENERATION_PARAMS.get(quality_preset, _QUALITY_GENERATION_PARAMS["standard"])
    # Rough scene-count assumption for the generation-time contribution:
    # production_service's own prompt actively favors variety (diagrams /
    # charts / photos / text animation, not just AI video), so only a
    # fraction of scenes are assumed to need this engine - about one scene
    # per 6 seconds of footage, roughly a third of which are AI video.
    n_scenes = max(1, round(duration_seconds / 6 * 0.35))
    (g_low, g_high), g_history = estimate_generation(
        engine_id, params["width"], params["height"], params["num_frames"], params["num_inference_steps"]
    )
    g_low, g_high = g_low * n_scenes, g_high * n_scenes

    total_low, total_high = p_low + g_low, p_high + g_high
    based_on_history = p_history or g_history
    return {
        "planning": {"low_seconds": p_low, "high_seconds": p_high},
        "generation": {"low_seconds": g_low, "high_seconds": g_high},
        "total": {"low_seconds": total_low, "high_seconds": total_high},
        "based_on_history": based_on_history,
        "note": (
            "過去の実測値に基づく推定です。" if based_on_history else
            "実測データがまだ無いため、モデル・設定からの理論値による推定です。"
            "AI動画生成を使うシーン数の仮定を含む概算のため、実際の時間は内容・PCの状態により前後します。"
        ),
    }
