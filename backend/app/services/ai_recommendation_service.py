"""PC-based AI model recommendation (design doc sections 9-17).

Combines what system_info_service already detects about this machine (RAM,
GPU) with the model catalog to answer three questions without ever
hardcoding a single reference PC's specs:

1. Given this PC, what tier of model is realistic? (recommend_model)
2. Does LM Studio already have something loaded that satisfies that tier,
   so nothing needs to be downloaded? (section 17: reuse existing models)
3. If not, what would setting up the recommended model actually cost in
   disk space and time - shown so the user can decide, never downloaded
   automatically (sections 15-16)?
"""
from __future__ import annotations

import shutil

from app.core.config import DATA_ROOT
from app.services import model_catalog, system_info_service
from app.services.model_catalog import ModelCatalogEntry


def _fits_comfortably(entry: ModelCatalogEntry, ram_gb: float, vram_gb: float, gpu_dedicated: bool) -> bool:
    if entry.min_vram_gb > 0 and not (gpu_dedicated and vram_gb >= entry.min_vram_gb):
        return False
    return ram_gb >= entry.recommended_ram_gb


def _fits_minimally(entry: ModelCatalogEntry, ram_gb: float, vram_gb: float, gpu_dedicated: bool) -> bool:
    if entry.min_vram_gb > 0 and not (gpu_dedicated and vram_gb >= entry.min_vram_gb):
        return False
    return ram_gb >= entry.min_ram_gb


def pick_best_fit_entry(ram_gb: float, gpu_dedicated: bool, vram_gb: float = 0.0) -> tuple[ModelCatalogEntry | None, bool]:
    """Returns (entry, comfortable). `comfortable=False` means it only just
    fits the minimum, not the recommended, requirement - callers should
    surface that as a caveat rather than an unqualified recommendation
    (section 10: never present an unrealistic model as a plain "recommended")."""
    entries = model_catalog.load_catalog()
    if not entries:
        return None, False

    comfortable = [e for e in entries if _fits_comfortably(e, ram_gb, vram_gb, gpu_dedicated)]
    if comfortable:
        # Best-fitting: use as much of the PC's headroom as is comfortable,
        # without going further "for free" (design doc section 10: don't
        # blindly recommend the largest model that merely fits).
        best = max(comfortable, key=lambda e: e.recommended_ram_gb)
        return best, True

    minimal = [e for e in entries if _fits_minimally(e, ram_gb, vram_gb, gpu_dedicated)]
    if minimal:
        best = max(minimal, key=lambda e: e.min_ram_gb)
        return best, False

    # Nothing in the catalog fits even minimally - offer the lightest entry
    # anyway so there is always something to point to, clearly flagged.
    lightest = min(entries, key=lambda e: e.min_ram_gb)
    return lightest, False


def _build_reasons(
    ram_gb: float, gpu_names: list[str], gpu_dedicated: bool, entry: ModelCatalogEntry, comfortable: bool
) -> list[str]:
    reasons = [
        f"RAM {ram_gb:.0f}GB",
        f"GPU: {', '.join(gpu_names) if gpu_names else '検出できませんでした'}"
        + ("(専用VRAM)" if gpu_dedicated else "(統合/共有VRAM)"),
        f"候補モデルサイズ: 約{entry.size_gb:.1f}GB ({entry.quant})",
        f"品質/速度: {entry.tier_label} ({entry.speed_tier})",
    ]
    if not comfortable:
        reasons.append(
            f"注意: このPCのRAMは推奨値({entry.recommended_ram_gb:.0f}GB)を下回っています。"
            "動作はしますが速度・安定性が低下する可能性があります。"
        )
    else:
        reasons.append("品質と処理時間のバランスが良いためこのモデルを推奨しています。")
    return reasons


def recommend_model(available_models: list[str]) -> dict:
    ram = system_info_service.get_ram_info()
    gpu = system_info_service.get_gpu_info()
    gpu_names = gpu.get("names") or []
    gpu_dedicated = any(gpu.get("dedicated") or [])
    ram_gb = ram["total_gb"]

    entry, comfortable = pick_best_fit_entry(ram_gb, gpu_dedicated)
    if entry is None:
        return {
            "ram_gb": ram_gb,
            "gpu_names": gpu_names,
            "gpu_dedicated": gpu_dedicated,
            "recommended_tier_label": "不明",
            "reasons": ["モデルカタログを読み込めませんでした。"],
            "recommended_model_id": None,
            "recommended_model_source": "none",
        }

    # Section 17: prefer a model the user already has loaded in LM Studio
    # over suggesting a fresh download, as long as it satisfies some
    # catalog entry this PC can realistically run. Reasons are built from
    # *that* matched entry (not the abstract best-fit one below) so the
    # displayed size/tier always matches the model actually being used.
    for model_id in available_models:
        matched = model_catalog.find_match(model_id)
        if matched is not None and _fits_minimally(matched, ram_gb, 0.0, gpu_dedicated):
            matched_reasons = _build_reasons(ram_gb, gpu_names, gpu_dedicated, matched, comfortable=True)
            matched_reasons.append(
                f"LM Studioに既にロード済みのモデル「{model_id}」がこの用途に適しているため、これを使用します。"
            )
            return {
                "ram_gb": ram_gb,
                "gpu_names": gpu_names,
                "gpu_dedicated": gpu_dedicated,
                "recommended_tier_label": matched.tier_label,
                "reasons": matched_reasons,
                "recommended_model_id": model_id,
                "recommended_model_source": "existing",
            }

    reasons = _build_reasons(ram_gb, gpu_names, gpu_dedicated, entry, comfortable)

    return {
        "ram_gb": ram_gb,
        "gpu_names": gpu_names,
        "gpu_dedicated": gpu_dedicated,
        "recommended_tier_label": entry.tier_label,
        "reasons": reasons,
        "recommended_model_id": None,
        "recommended_model_source": "catalog",
        "_catalog_entry": entry,
    }


def _download_time_minutes(size_gb: float) -> tuple[float, float]:
    # Deliberately a wide, labelled *estimate* range (design doc section 15)
    # rather than a false-precision single number - actual speed depends
    # entirely on the user's own connection, which Kairo cannot measure.
    # ~25MB/s (fast broadband) to ~8MB/s (slower connection).
    low = round(size_gb * 1024 / 25 / 60, 1)
    high = round(size_gb * 1024 / 8 / 60, 1)
    return max(low, 0.5), max(high, low + 1)


def build_setup_candidates(available_models: list[str]) -> list[dict]:
    ram = system_info_service.get_ram_info()
    gpu = system_info_service.get_gpu_info()
    gpu_dedicated = any(gpu.get("dedicated") or [])
    ram_gb = ram["total_gb"]
    disk = shutil.disk_usage(DATA_ROOT)
    free_gb = round(disk.free / 1e9, 1)

    best_entry, _ = pick_best_fit_entry(ram_gb, gpu_dedicated)
    candidates = []
    for entry in model_catalog.load_catalog():
        fits = _fits_minimally(entry, ram_gb, 0.0, gpu_dedicated)
        if not fits:
            continue
        required = round(entry.size_gb * 1.2, 1)
        low_min, high_min = _download_time_minutes(entry.size_gb)
        already_available = any(entry.matches(m) for m in available_models)
        stars = 5 if best_entry is not None and entry.id == best_entry.id else (
            4 if fits and entry.quality_tier == (best_entry.quality_tier if best_entry else "") else 3
        )
        candidates.append(
            {
                "id": entry.id,
                "display_name": entry.display_name,
                "purpose": entry.purpose,
                "size_gb": entry.size_gb,
                "quant": entry.quant,
                "tier_label": entry.tier_label,
                "required_free_gb": required,
                "current_free_gb": free_gb,
                "enough_disk_space": free_gb >= required,
                "estimated_download_minutes_low": low_min,
                "estimated_download_minutes_high": high_min,
                "recommendation_stars": stars,
                "already_available": already_available,
            }
        )
    candidates.sort(key=lambda c: c["recommendation_stars"], reverse=True)
    return candidates


_RESOLUTION_LABELS = {
    (1280, 720): "720p", (720, 1280): "720p",
    (1920, 1080): "1080p", (1080, 1920): "1080p",
    (3840, 2160): "4K", (2160, 3840): "4K",
}


def assess_video_setting(width: int, height: int, fps: float) -> dict:
    """Section 33/34: warn when a resolution/fps combo is unrealistic for
    this PC's detected GPU, without blocking the user from choosing it
    manually."""
    gpu = system_info_service.get_gpu_info()
    gpu_dedicated = any(gpu.get("dedicated") or [])
    pixels = width * height
    label = _RESOLUTION_LABELS.get((width, height), f"{width}x{height}")

    if pixels >= 3840 * 2160 * 0.9:
        if not gpu_dedicated:
            return {
                "level": "not_recommended",
                "reason": f"{label}は専用GPUの無いこのPCでは処理時間が非常に長くなる可能性があります。",
            }
        return {"level": "caution", "reason": f"{label}は処理時間が長くなる場合があります。"}

    if fps >= 60:
        if not gpu_dedicated:
            return {
                "level": "caution",
                "reason": "60fpsは専用GPUの無いこのPCでは生成・書き出し時間が長くなる可能性があります。",
            }
        return {"level": "caution", "reason": "60fpsは処理時間がやや長くなる場合があります。"}

    return {"level": "recommended", "reason": f"{label} / {fps:.0f}fpsはこのPCで問題なく扱える設定です。"}


def recommended_parallelism() -> int:
    """Section 10-style heuristic for a safe default job-concurrency limit:
    half the logical cores (leaving headroom for FFmpeg/AI workloads that
    are themselves multi-threaded), floored at 1 and capped at 4."""
    cpu = system_info_service.get_cpu_info()
    logical = cpu.get("logical_cores") or 4
    return max(1, min(logical // 2, 4))


def assess_parallelism(value: int) -> dict:
    """Section 33/34-style warning for the generation-settings "並列数":
    0 means Auto (always fine, resolved elsewhere), anything else is
    compared against this PC's logical core count."""
    if value <= 0:
        return {"level": "recommended", "reason": "Autoの場合、このPCのCPUコア数から安全な値を自動選択します。"}

    cpu = system_info_service.get_cpu_info()
    logical = cpu.get("logical_cores") or 4
    recommended = recommended_parallelism()

    if value > logical:
        return {
            "level": "not_recommended",
            "reason": f"このPCの論理コア数({logical})を超えています。処理が極端に遅くなるか失敗する可能性があります。",
        }
    if value > recommended:
        return {
            "level": "caution",
            "reason": f"推奨値は{recommended}です。{value}に設定すると他の処理が重くなる可能性があります。",
        }
    return {"level": "recommended", "reason": f"このPC(論理コア数{logical})で問題なく扱える設定です。"}
