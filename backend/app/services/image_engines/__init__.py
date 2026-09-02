"""Pluggable still-image generators for scene visuals.

Same shape as `app/services/video_engines`: engines are described without
importing anything heavy, and only instantiated when actually used. The
difference is that one engine here - `procedural` - has no download and no
optional dependency, so scene visuals are always producible. Everything
else is an upgrade the user opts into.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

from app.core.config import MODELS_ROOT

logger = logging.getLogger(__name__)


class ImageEngine(Protocol):
    id: str

    def is_ready(self) -> bool: ...

    def render(self, spec, width: int, height: int, dest: Path) -> Path: ...


def _sd_weights_present() -> bool:
    """Whether a diffusers text-to-image checkpoint has been downloaded into
    Kairo's own model root. Kairo never triggers this download itself
    (section 12) - it reports the state and lets the user decide."""
    try:
        for entry in MODELS_ROOT.glob("models--*"):
            name = entry.name.lower()
            if "stable-diffusion" in name and "video" not in name:
                return True
    except OSError:
        pass
    return False


def list_engines() -> list[dict]:
    from app.services.image_engines import procedural

    engines = [
        {
            **procedural.describe(),
            "ready": procedural.is_available(),
            "status": "ready" if procedural.is_available() else "unavailable",
            "status_reason": (
                "追加ダウンロードなしで利用できます。"
                if procedural.is_available()
                else "画像ライブラリ(Pillow)が利用できません。"
            ),
        },
    ]

    sd_ready = _sd_weights_present()
    engines.append(
        {
            "id": "sd",
            "display_name": "Stable Diffusion (拡散モデル)",
            "provider": "Kairo Local / diffusers",
            "needs_download": True,
            "approx_download_gb": 4.3,
            "ready": sd_ready,
            "status": "ready" if sd_ready else "not_downloaded",
            "status_reason": (
                "モデルを検出しました。シーン素材の生成に選択できます。"
                if sd_ready
                else (
                    "未ダウンロードです(約4.3GB)。Kairoが自動でダウンロードすることはありません。"
                    "導入しなくても制作は完了します。"
                )
            ),
            "notes": "写実的/絵画的な画像を生成できますが、CPUのみの環境では1枚あたり数分かかります。",
        }
    )
    return engines


def get_engine(engine_id: str):
    if engine_id in ("procedural", "", None):
        from app.services.image_engines import procedural

        return procedural
    if engine_id == "sd":
        if not _sd_weights_present():
            raise RuntimeError(
                "Stable Diffusionのモデルがダウンロードされていません。"
                "AIモデル画面から導入方法を確認してください。"
            )
        from app.services.image_engines import sd_engine

        return sd_engine
    raise KeyError(f"Unknown image engine: {engine_id}")


def resolve_engine_id(preferred: str | None = None) -> str:
    """The engine a production should use: the caller's choice when it is
    genuinely usable, otherwise the always-available one. Silently falling
    back is correct here *because* the caller is told which engine ran via
    the model plan and the production events."""
    if preferred and preferred != "procedural":
        try:
            get_engine(preferred)
            return preferred
        except Exception:
            logger.info("Image engine %s unavailable; using procedural", preferred)
    return "procedural"


def default_engine_status() -> dict:
    """Summary for the "今回使用するAI" table."""
    from app.services.image_engines import procedural

    ready = procedural.is_available()
    info = procedural.describe()
    return {
        "engine": info["display_name"],
        "provider": info["provider"],
        "ready": ready,
        "detail": (
            info["notes"]
            if ready
            else "画像生成ライブラリ(Pillow)が利用できないため、映像素材を生成できません。"
        ),
        "remedy": [] if ready else ["backend の依存関係を再インストールしてください (pip install -r requirements.txt)"],
    }
