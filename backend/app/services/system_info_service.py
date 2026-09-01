"""PC / AI environment diagnostics (design doc section 9-12): what this
machine actually has, and - just as importantly - what Kairo's local AI
features can realistically do on it. Every field is either read from the
OS/runtime directly or is an explicit, labelled heuristic; nothing here is
presented as more certain than it is.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys

from app.core.config import DATA_ROOT, LLM_BASE_URL, LLM_MODEL
from app.services import llm_client, video_engines


def _run(cmd: list[str], timeout: float = 8.0) -> str | None:
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def get_cpu_info() -> dict:
    import psutil

    return {
        "name": platform.processor() or "不明",
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
    }


def get_ram_info() -> dict:
    import psutil

    vm = psutil.virtual_memory()
    return {
        "total_gb": round(vm.total / 1e9, 1),
        "available_gb": round(vm.available / 1e9, 1),
        "used_percent": vm.percent,
    }


def get_disk_info() -> dict:
    usage = shutil.disk_usage(DATA_ROOT)
    return {
        "total_gb": round(usage.total / 1e9, 1),
        "free_gb": round(usage.free / 1e9, 1),
        "data_root": str(DATA_ROOT),
    }


def get_gpu_info() -> dict:
    if platform.system() != "Windows":
        return {"names": None, "note": "Windows以外は未対応(手動確認してください)"}
    out = _run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
        ]
    )
    names = [line.strip() for line in out.splitlines() if line.strip()] if out else []
    return {"names": names or None}


def get_ffmpeg_info() -> dict:
    path = shutil.which("ffmpeg")
    if not path:
        return {"available": False, "path": None, "version": None}
    out = _run([path, "-version"])
    version = out.splitlines()[0] if out else "不明"
    return {"available": True, "path": path, "version": version}


def get_ai_runtime_info() -> dict:
    info: dict = {"python_version": sys.version.split()[0]}
    try:
        import torch

        info["torch_installed"] = True
        info["torch_version"] = torch.__version__
        info["cuda_available"] = bool(torch.cuda.is_available())
        mps = getattr(getattr(torch, "backends", None), "mps", None)
        info["mps_available"] = bool(mps and mps.is_available())
        info["xpu_available"] = bool(hasattr(torch, "xpu") and torch.xpu.is_available())
    except ImportError:
        info["torch_installed"] = False
        info["cuda_available"] = False
        info["mps_available"] = False
        info["xpu_available"] = False

    try:
        import openvino  # noqa: F401

        info["openvino_installed"] = True
    except ImportError:
        info["openvino_installed"] = False

    active_backends = []
    if info["cuda_available"]:
        active_backends.append("CUDA (NVIDIA)")
    if info["mps_available"]:
        active_backends.append("MPS (Apple Silicon)")
    if info["xpu_available"]:
        active_backends.append("XPU (Intel GPU)")
    if not active_backends and info["torch_installed"]:
        active_backends.append("CPU")
    info["active_backends"] = active_backends

    try:
        import faster_whisper  # noqa: F401

        info["whisper_installed"] = True
    except ImportError:
        info["whisper_installed"] = False

    return info


def _rating(label: str, level: str, reason: str) -> dict:
    return {"label": label, "level": level, "reason": reason}


def assess_capabilities(
    ram_gb: float, ai_runtime: dict, ffmpeg: dict, llm_status: "llm_client.LLMStatus"
) -> list[dict]:
    """The "このPCで何が実行可能か" summary (section 12). `level` is one of
    green/yellow/orange/red, matching the UI's status-dot convention."""
    gpu_accelerated = ai_runtime["cuda_available"] or ai_runtime["mps_available"] or ai_runtime["xpu_available"]
    results = []

    if not ai_runtime["torch_installed"]:
        results.append(
            _rating(
                "画像→動画生成 (Image-to-Video)",
                "red",
                "動画生成用の依存関係(torch/diffusers)が未インストールです。",
            )
        )
    elif ram_gb < 8:
        results.append(
            _rating("画像→動画生成 (Image-to-Video)", "red", f"RAMが{ram_gb:.0f}GBと不足しています(最低8GB目安)。")
        )
    elif not gpu_accelerated:
        results.append(
            _rating(
                "画像→動画生成 (Image-to-Video)",
                "yellow",
                "CPUのみで実行されます。動作はしますが、短いクリップでも数分〜十数分かかります。",
            )
        )
    else:
        results.append(
            _rating("画像→動画生成 (Image-to-Video)", "green", "GPUアクセラレーションが利用可能です。")
        )

    results.append(
        _rating(
            "高解像度 / 長尺動画生成",
            "orange" if not gpu_accelerated else "yellow",
            "GPUアクセラレーションが無いため非推奨です。" if not gpu_accelerated else "時間がかかる場合があります。",
        )
    )

    results.append(
        _rating(
            "動画編集・レンダリング (FFmpeg)",
            "green" if ffmpeg["available"] else "red",
            "FFmpeg利用可能" if ffmpeg["available"] else "FFmpegが見つかりません。",
        )
    )

    if llm_status.can_generate:
        results.append(
            _rating(
                "AI編集・台本生成 (ローカルLLM)",
                "green",
                f"LM Studioに接続でき、モデルがロードされています({', '.join(llm_status.models_loaded)})。",
            )
        )
    elif llm_status.server_reachable:
        results.append(
            _rating(
                "AI編集・台本生成 (ローカルLLM)",
                "orange",
                "LM Studioには接続できていますが、モデルがロードされていません。",
            )
        )
    else:
        results.append(
            _rating(
                "AI編集・台本生成 (ローカルLLM)",
                "red",
                f"LM Studioに接続できません({LLM_BASE_URL})。起動してください。",
            )
        )

    return results


def _engine_downloaded(engine_id: str) -> bool:
    try:
        return video_engines.get_engine(engine_id).is_model_downloaded()
    except Exception:
        return False


def get_system_report() -> dict:
    ram = get_ram_info()
    ffmpeg = get_ffmpeg_info()
    ai_runtime = get_ai_runtime_info()
    llm_status = llm_client.get_status()
    engines = video_engines.list_capabilities()
    return {
        "cpu": get_cpu_info(),
        "ram": ram,
        "disk": get_disk_info(),
        "gpu": get_gpu_info(),
        "ffmpeg": ffmpeg,
        "os": {"name": platform.system(), "version": platform.version(), "release": platform.release()},
        "ai_runtime": ai_runtime,
        "capabilities": assess_capabilities(ram["total_gb"], ai_runtime, ffmpeg, llm_status),
        "video_generation_engines": [
            {
                "id": c.id,
                "display_name": c.display_name,
                "commercial_use": c.commercial_use,
                "notes": c.notes,
            }
            for c in engines
        ],
        # "何のAIが今使えるか" section 11 の一覧。実際に実装・確認済みの
        # プロバイダのみを載せる(未実装のTTS/画像生成AIなどは含めない)。
        "ai_pipeline": [
            {
                "id": "llm",
                "label": "LLM (企画・台本生成 / AI編集)",
                "provider": "LM Studio",
                "model": LLM_MODEL,
                "ready": llm_status.can_generate,
                "detail": (
                    f"ロード済みモデル: {', '.join(llm_status.models_loaded)}"
                    if llm_status.models_loaded
                    else ("サーバーには接続できますが、モデルが未ロードです" if llm_status.server_reachable else "サーバーに接続できません")
                ),
            },
            {
                "id": "stt",
                "label": "音声認識 (字幕生成)",
                "provider": "faster-whisper (ローカル)",
                "model": None,
                "ready": ai_runtime["whisper_installed"],
                "detail": "利用可能" if ai_runtime["whisper_installed"] else "依存関係が未インストールです",
            },
            *[
                {
                    "id": e.id,
                    "label": "画像→動画生成",
                    "provider": e.display_name,
                    "model": e.id,
                    "ready": _engine_downloaded(e.id),
                    "detail": e.notes,
                }
                for e in engines
            ],
        ],
    }
