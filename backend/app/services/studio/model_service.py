"""What AI Kairo will actually use for a production, and whether it can
(design doc sections 9-15).

Two things live here:

1. **A richer view of LM Studio than /v1/models gives.** LM Studio's
   OpenAI-compatible `/v1/models` lists everything *downloaded*, not what
   is *loaded* - so a machine with six models on disk and none in memory
   reported "Loaded" in the old UI. LM Studio's own REST API
   (`/api/v0/models`) exposes `state`, `type` (llm / vlm / embeddings),
   quantization and context length, so when it is available Kairo shows
   the truth: downloaded vs. loaded, chat-capable vs. embedding-only.
   Everything degrades to the /v1 view if that endpoint isn't there.

2. **The model plan** - the "今回使用するAI" panel (section 9). Every role
   in the pipeline is listed with the model that will really serve it,
   resolved at call time from LM Studio + Kairo's settings. Nothing here
   is a hardcoded model name; a role whose model cannot be resolved says
   so instead of printing a plausible-looking id.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Optional

import requests

from app.core.config import LLM_BASE_URL
from app.services import llm_client, model_catalog, tts_service, video_engines
from app.services.ffmpeg.util import require_binary

logger = logging.getLogger(__name__)

# LM Studio's native REST API sits next to the OpenAI-compatible one:
# http://host:1234/v1 -> http://host:1234/api/v0
_NATIVE_API_BASE = LLM_BASE_URL.rstrip("/").removesuffix("/v1") + "/api/v0"


@dataclass
class LMModel:
    id: str
    # "loaded" | "downloaded" | "unknown" - `downloaded` is a perfectly
    # usable state, since LM Studio JIT-loads a model on first request.
    state: str = "unknown"
    kind: str = "llm"  # llm | vlm | embeddings | unknown
    quantization: str = ""
    max_context_length: Optional[int] = None
    publisher: str = ""
    arch: str = ""
    chat_capable: bool = True
    # Kairo's own catalog opinion, when the id matches a known entry.
    tier_label: Optional[str] = None
    recommended: bool = False
    size_gb: Optional[float] = None
    speed_label: str = ""


@dataclass
class RoleAssignment:
    """One line of the "今回使用するAI" table."""

    id: str
    label: str  # e.g. "企画・構成"
    purpose: str
    provider: str  # "LM Studio / Local", "Kairo Local", "FFmpeg / Local", ...
    model: Optional[str]
    ready: bool
    status: str  # ready | not_ready | degraded | unavailable
    detail: str
    # Filled only when the role cannot run, so the UI can offer the exact
    # next step instead of a generic error (section 11/15).
    remedy: list[str] = field(default_factory=list)


@dataclass
class ModelPlan:
    roles: list[RoleAssignment]
    llm_ready: bool
    llm_model: Optional[str]
    llm_model_source: str
    llm_error_code: str
    available_models: list[LMModel]
    blocking: list[str]
    warnings: list[str]

    def to_dict(self) -> dict:
        return {
            "roles": [asdict(r) for r in self.roles],
            "llm_ready": self.llm_ready,
            "llm_model": self.llm_model,
            "llm_model_source": self.llm_model_source,
            "llm_error_code": self.llm_error_code,
            "available_models": [asdict(m) for m in self.available_models],
            "blocking": self.blocking,
            "warnings": self.warnings,
        }


# Substrings that mark a model as unusable for chat generation. Mirrors
# llm_client's own filter so both agree on what "a usable model" means.
_NON_CHAT = ("embed", "rerank", "bge-", "gte-", "e5-small", "e5-large", "e5-base")


def _chat_capable(model_id: str, kind: str) -> bool:
    if kind in ("embeddings", "reranker"):
        return False
    low = model_id.lower()
    return not any(marker in low for marker in _NON_CHAT)


def _fetch_native() -> list[dict] | None:
    """LM Studio's own model listing, or None when this server doesn't
    expose it (another OpenAI-compatible backend, or an older build)."""
    try:
        resp = requests.get(f"{_NATIVE_API_BASE}/models", timeout=4)
    except requests.RequestException:
        return None
    if not resp.ok:
        return None
    try:
        data = resp.json().get("data", [])
    except ValueError:
        return None
    return data if isinstance(data, list) else None


def list_models() -> list[LMModel]:
    """Everything the local server offers, annotated with load state and
    Kairo's catalog opinion. Empty list when the server is unreachable -
    callers distinguish that from "reachable but empty" via
    `llm_client.get_status()`."""
    native = _fetch_native()
    models: list[LMModel] = []

    if native is not None:
        for item in native:
            model_id = item.get("id")
            if not isinstance(model_id, str):
                continue
            kind = str(item.get("type") or "unknown")
            raw_state = str(item.get("state") or "")
            state = "loaded" if raw_state == "loaded" else "downloaded"
            models.append(
                LMModel(
                    id=model_id,
                    state=state,
                    kind=kind,
                    quantization=str(item.get("quantization") or ""),
                    max_context_length=item.get("max_context_length"),
                    publisher=str(item.get("publisher") or ""),
                    arch=str(item.get("arch") or ""),
                    chat_capable=_chat_capable(model_id, kind),
                )
            )
    else:
        status = llm_client.get_status()
        for model_id in status.models_loaded:
            models.append(
                LMModel(
                    id=model_id,
                    state="unknown",
                    kind="unknown",
                    chat_capable=_chat_capable(model_id, "unknown"),
                )
            )

    for model in models:
        entry = model_catalog.find_match(model.id)
        if entry is not None:
            model.tier_label = entry.tier_label
            model.recommended = True
            model.size_gb = entry.size_gb
            model.speed_label = entry.speed_tier
    return models


def load_model(model_id: str) -> tuple[bool, str]:
    """Asks LM Studio to bring a downloaded model into memory.

    Implemented as a tiny chat completion rather than a load API call:
    LM Studio JIT-loads on demand and exposes no public load endpoint, so
    this is the one portable way to make "モデルをロードする" a button that
    genuinely does something. Returns (ok, human-readable detail).
    """
    url = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "ok"}],
        "max_tokens": 1,
        "temperature": 0,
    }
    try:
        # Loading a multi-GB model from disk can take a while on a cold
        # cache, so this timeout is deliberately generous.
        resp = requests.post(url, json=payload, timeout=300)
    except requests.RequestException as exc:
        return False, f"LM Studioに接続できませんでした: {exc}"
    if not resp.ok:
        return False, f"LM Studioがエラーを返しました ({resp.status_code}): {resp.text[:200]}"
    return True, f"{model_id} を読み込みました。"


# --------------------------------------------------------------- the plan

_ROLE_DEFS = [
    ("planning", "企画・構成", "動画のタイトル・視聴者・トーン・全体構成を決めます"),
    ("script", "脚本・Scene生成", "ナレーションと字幕、シーンごとの映像設計を書きます"),
    ("research", "リサーチ分析", "Web上の傾向を読み取り、共通点と差別化点に整理します"),
    ("quality", "品質チェック", "完成前の構成・テンポ・字幕・音を点検します"),
    ("cocreation", "AI Co-Creation", "チャットの指示を実際の編集操作に変換します"),
]


def build_plan(*, want_narration: bool = True, want_research: bool = True) -> ModelPlan:
    """The "今回使用するAI" table, resolved from the machine's real state."""
    status = llm_client.get_status()
    models = list_models()
    roles: list[RoleAssignment] = []
    blocking: list[str] = []
    warnings: list[str] = []

    llm_model = status.configured_model
    llm_ready = status.ready

    chat_models = [m for m in models if m.chat_capable]
    resolved = next((m for m in models if m.id == llm_model), None)

    if llm_ready and resolved is not None and resolved.state == "downloaded":
        warnings.append(
            f"{llm_model} はまだメモリに読み込まれていません。"
            "最初のリクエスト時にLM Studioが自動で読み込むため、"
            "初回の応答だけ時間がかかります。"
        )

    if not llm_ready:
        if not status.server_reachable:
            remedy = [
                "LM Studioを起動する",
                "LM StudioのDeveloper(Server)タブでLocal Serverを起動する",
                f"エンドポイント({LLM_BASE_URL})が合っているか確認する",
            ]
            detail = f"LM Studio({LLM_BASE_URL})に接続できません。"
        elif not chat_models:
            remedy = [
                "LM Studioでチャット用モデル(gemmaやqwenなど)をダウンロードする",
                "AIモデル画面から推奨モデルを確認する",
            ]
            detail = "LM Studioに接続できていますが、チャット生成に使えるモデルがありません。"
        else:
            remedy = [
                "AIモデル画面で利用可能なモデルを選び直す",
                "LM Studioで対象のモデルを読み込む",
            ]
            detail = (
                f"指定モデル「{llm_model}」がLM Studioで見つかりません。"
                f"利用可能: {', '.join(m.id for m in chat_models[:4])}"
            )
        blocking.append(detail)
    else:
        remedy = []
        detail = status.resolution_reason or "LM Studioで使用可能です。"

    for role_id, label, purpose in _ROLE_DEFS:
        if role_id == "research" and not want_research:
            roles.append(
                RoleAssignment(
                    id=role_id,
                    label=label,
                    purpose=purpose,
                    provider="LM Studio / Local",
                    model=llm_model,
                    ready=True,
                    status="skipped",
                    detail="今回はWebリサーチを行わない設定です。",
                )
            )
            continue
        roles.append(
            RoleAssignment(
                id=role_id,
                label=label,
                purpose=purpose,
                provider="LM Studio / Local",
                model=llm_model,
                ready=llm_ready,
                status="ready" if llm_ready else "not_ready",
                detail=detail,
                remedy=list(remedy),
            )
        )

    # --- Visual generation -------------------------------------------------
    from app.services import image_engines

    visual = image_engines.default_engine_status()
    roles.append(
        RoleAssignment(
            id="visual",
            label="映像素材生成",
            purpose="各シーンの映像をローカルで生成します",
            provider=visual["provider"],
            model=visual["engine"],
            ready=visual["ready"],
            status="ready" if visual["ready"] else "unavailable",
            detail=visual["detail"],
            remedy=visual.get("remedy", []),
        )
    )

    # Optional upgrade path: a downloaded image-to-video model turns still
    # scenes into moving ones. Reported honestly as an upgrade, never as
    # something that is silently in use.
    for caps in video_engines.list_capabilities():
        try:
            downloaded = video_engines.get_engine(caps.id).is_model_downloaded()
        except Exception:
            downloaded = False
        roles.append(
            RoleAssignment(
                id=f"video_engine_{caps.id}",
                label="動画生成(任意)",
                purpose="静止素材に動きを付ける追加エンジンです(未導入でも制作は進みます)",
                provider="Kairo Local",
                model=caps.display_name,
                ready=downloaded,
                status="ready" if downloaded else "optional",
                detail=(
                    "モデルは取得済みです。シーン単位で利用できます。"
                    if downloaded
                    else f"未ダウンロード(約{caps.approx_download_gb:.1f}GB)。無くても制作は完了します。"
                ),
            )
        )

    # --- Narration ---------------------------------------------------------
    if want_narration:
        voices = tts_service.list_voices() if tts_service.is_supported_platform() else []
        roles.append(
            RoleAssignment(
                id="narration",
                label="音声合成",
                purpose="ナレーションを読み上げます",
                provider="Windows SAPI / Local",
                model=(voices[0].name if voices else None),
                ready=bool(voices),
                status="ready" if voices else "unavailable",
                detail=(
                    f"{len(voices)}件の音声が利用可能です。"
                    if voices
                    else "この環境では音声合成が利用できません。ナレーション無しで制作を続行します。"
                ),
                remedy=(
                    []
                    if voices
                    else ["Windowsの「設定 > 時刻と言語 > 音声」から音声を追加する"]
                ),
            )
        )
        if not voices:
            warnings.append("音声合成が使えないため、ナレーション無しの動画になります。")

    # --- Editing / rendering ----------------------------------------------
    try:
        require_binary("ffmpeg")
        ffmpeg_ok, ffmpeg_detail = True, "MP4の書き出しに使用します。"
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        ffmpeg_ok, ffmpeg_detail = False, str(exc)
        blocking.append("FFmpegが見つからないため、動画を書き出せません。")

    roles.append(
        RoleAssignment(
            id="editor",
            label="動画編集・書き出し",
            purpose="素材の連結・音声合成・字幕焼き込み・MP4出力を行います",
            provider="FFmpeg / Local",
            model="FFmpeg",
            ready=ffmpeg_ok,
            status="ready" if ffmpeg_ok else "unavailable",
            detail=ffmpeg_detail,
            remedy=[] if ffmpeg_ok else ["FFmpegをインストールしてPATHに追加する"],
        )
    )

    return ModelPlan(
        roles=roles,
        llm_ready=llm_ready,
        llm_model=llm_model,
        llm_model_source=status.model_source,
        llm_error_code=status.error_code,
        available_models=models,
        blocking=blocking,
        warnings=warnings,
    )


def download_instructions(model_id: str) -> dict:
    """How to obtain a model Kairo recommends but the machine doesn't have.

    Kairo never starts a multi-gigabyte download by itself (section 12) -
    it hands over the exact command and the size so the user decides.
    """
    entry = model_catalog.find_match(model_id)
    return {
        "model_id": model_id,
        "display_name": entry.display_name if entry else model_id,
        "approx_size_gb": entry.size_gb if entry else None,
        "purpose": entry.purpose if entry else "企画・脚本・Scene構成の生成",
        "command": f"lms get {model_id}",
        "steps": [
            "LM Studioを開く",
            "検索(Discover)タブでモデル名を検索する",
            "ダウンロードを実行する(容量と通信量に注意してください)",
            "Kairoに戻って「再確認」を押す",
        ],
        "note": "Kairoが自動でダウンロードすることはありません。実行前に必ず容量とライセンスを確認してください。",
    }
