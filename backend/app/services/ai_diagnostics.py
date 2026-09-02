"""Turns a raw exception from any AI/media job (LLM planning & editing,
image-to-video generation, subtitle transcription, ffmpeg rendering) into
the structured, plain-language explanation the diagnostics UI needs: what
happened, what was actually confirmed, what's only a guess, and what to do
about it - "原因を特定できませんでした" (cause could not be determined)
instead of a confident-sounding guess when nothing matches.

Started as `generation_diagnostics.py`, scoped to the image-to-video path
only. Generalized here to cover every job type so a single Diagnosis shape
(and a single frontend component) can render any failure in this app,
including local-LLM-specific failures like "connected to LM Studio but no
model is loaded" - the failure mode that motivated this module.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from app.core.config import MODELS_ROOT
from app.services import llm_client

# One of these, chosen by `diagnose()`. Kept as a plain string (not an Enum)
# so it round-trips through JSON without extra handling on the frontend.
Category = str  # ai_provider | model | api | network | resource | memory |
# ffmpeg | input_material | configuration | unknown


@dataclass
class Suggestion:
    label: str
    action: str  # machine-readable id the frontend maps to a button


@dataclass
class AIContext:
    """What Kairo was trying to use when the failure happened - shown to
    the user up front so "何のAIを使おうとしたのか" is never a mystery."""

    provider: str
    model: str
    task: str
    operation: str
    endpoint: str
    model_status: str
    # LM Studio-specific detail (empty/default for non-LLM contexts, e.g.
    # image-to-video generation) so the UI can show "何が要求されていて、
    # LM Studio側に今何があるのか" side by side instead of one vague line.
    requested_model: str = ""
    model_source: str = ""
    models_loaded: list[str] = field(default_factory=list)
    connection_status: str = ""
    error_code: str = ""


@dataclass
class Diagnosis:
    summary: str
    cause_known: bool
    cause: str
    category: Category = "unknown"
    facts: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)
    ai_context: dict | None = None
    step: str | None = None
    retryable: bool = True
    raw_error: str = ""
    # Machine-readable code for LM Studio failures (e.g. MODEL_NOT_LOADED) -
    # "" when this diagnosis isn't one of the classified LM Studio states.
    error_code: str = ""

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "cause_known": self.cause_known,
            "cause": self.cause,
            "category": self.category,
            "facts": self.facts,
            "candidates": self.candidates,
            "suggestions": [asdict(s) for s in self.suggestions],
            "ai_context": self.ai_context,
            "step": self.step,
            "retryable": self.retryable,
            "raw_error": self.raw_error,
            "error_code": self.error_code,
        }


def _finish(
    diag: Diagnosis, exc: Exception, context: AIContext | None, step: str | None
) -> Diagnosis:
    diag.raw_error = f"{type(exc).__name__}: {exc}"
    diag.ai_context = asdict(context) if context is not None else None
    diag.step = step
    return diag


def diagnose_llm_status(
    status: llm_client.LLMStatus, *, context: AIContext | None = None
) -> Diagnosis:
    """Explains an LLMStatus in the same terms `diagnose()` uses for a
    failed job, but doesn't need an exception to produce one - used both
    for a preflight failure (via LLMNotReadyError below) and for the
    "モデル状態を確認" button, which asks this question with nothing having
    failed yet."""
    available = status.models_loaded

    if status.error_code == llm_client.ERROR_CONNECTION_FAILED:
        diag = Diagnosis(
            summary="LM Studio APIに接続できません。",
            category="ai_provider",
            error_code=status.error_code,
            cause_known=True,
            cause=f"LM Studioのローカルサーバー({status.base_url})に接続できませんでした。",
            facts=[
                f"Endpoint: {status.base_url}",
                status.connection_error or "接続エラーの詳細は取得できませんでした。",
            ],
            candidates=[
                "LM Studioが起動しているか",
                "LM StudioのLocal Serverが起動しているか",
                "ポート番号(既定: 1234)が設定と一致しているか",
            ],
            suggestions=[
                Suggestion("LM Studioを起動する", "recheck_status"),
                Suggestion("LM StudioのDeveloper/ServerタブでLocal Serverを起動する", "recheck_status"),
                Suggestion("状態を再確認", "recheck_status"),
            ],
        )
    elif status.error_code == llm_client.ERROR_MODELS_FETCH_FAILED:
        diag = Diagnosis(
            summary="LM StudioのAPI(/v1/models)からモデル一覧を取得できませんでした。",
            category="api",
            error_code=status.error_code,
            cause_known=True,
            cause=(
                "LM Studioのサーバーには接続できましたが、モデル一覧の取得に失敗しました"
                "(想定外の応答、またはエラーを返しています)。"
            ),
            facts=[
                f"Endpoint: {status.base_url}/models",
                status.connection_error or "応答の詳細は取得できませんでした。",
            ],
            candidates=["LM Studioのバージョンが対応していない", "LM Studio側で一時的なエラーが発生している"],
            suggestions=[
                Suggestion("LM Studioを再起動する", "recheck_status"),
                Suggestion("状態を再確認", "recheck_status"),
            ],
        )
    elif status.error_code == llm_client.ERROR_MODEL_NOT_LOADED:
        embedding_only = len(available) > 0
        diag = Diagnosis(
            summary=(
                "LM Studioに接続できていますが、チャット生成に使えるモデルがありません。"
                if embedding_only
                else "LM Studioに接続できていますが、利用可能なモデルがありません。"
            ),
            category="model",
            error_code=status.error_code,
            cause_known=True,
            cause=(
                "LM Studioには接続できていますが、ロードされているのは埋め込み/リランク用のモデルのみで、"
                "チャット生成(企画・台本・編集指示の解釈)に使えるモデルがロードされていません。"
                if embedding_only
                else "LM Studioには接続できていますが、現在ロードされているモデルがありません。"
                "LM Studioでモデルをロードしてください。"
            ),
            facts=[
                "LM Studioサーバーには接続できました。",
                "現在ロードされているモデル: " + (", ".join(available) if available else "なし"),
            ],
            suggestions=[
                Suggestion("LM StudioのDeveloper/ServerタブでチャットモデルをLoadする", "recheck_status"),
                Suggestion("AIセットアップ画面で推奨モデルを確認する", "open_ai_setup"),
                Suggestion("状態を再確認", "recheck_status"),
                Suggestion("再試行", "retry"),
            ],
        )
    elif status.error_code == llm_client.ERROR_MODEL_NOT_FOUND:
        via_env = status.model_source == "env"
        diag = Diagnosis(
            summary="指定されたモデルがLM Studioで利用できません。",
            category="model",
            error_code=status.error_code,
            cause_known=True,
            cause=(
                f"{'環境変数 KAIRO_LLM_MODEL で' if via_env else ''}指定されているモデル"
                f"「{status.configured_model}」は、現在LM Studioにロードされているモデルの中に"
                "見つかりませんでした。"
            ),
            facts=[
                f"指定: {status.configured_model}",
                "利用可能: " + (", ".join(available) if available else "(なし)"),
            ],
            candidates=(
                ["環境変数 KAIRO_LLM_MODEL のモデル名が間違っている", "目的のモデルがLM Studioでまだロードされていない"]
                if via_env
                else ["設定したモデルがLM Studioでアンロードされた", "目的のモデルがLM Studioでまだロードされていない"]
            ),
            suggestions=[
                Suggestion("利用可能なモデルを使用する(Kairoの設定をAutoに切り替える)", "use_available_model"),
                Suggestion("設定を変更する(AI設定でModelを選び直す)", "open_ai_settings"),
                Suggestion("状態を再確認", "recheck_status"),
            ],
        )
    else:
        diag = Diagnosis(
            summary="LM Studioは使用準備ができています。",
            category="ai_provider",
            error_code=llm_client.ERROR_OK,
            cause_known=True,
            cause="",
            facts=[f"ロード済みモデル: {', '.join(available)}" if available else ""],
            retryable=False,
        )

    diag.ai_context = asdict(context) if context is not None else None
    return diag


def diagnose(
    exc: Exception, *, context: AIContext | None = None, step: str | None = None
) -> Diagnosis:
    text = f"{type(exc).__name__}: {exc}".lower()
    exc_name = type(exc).__name__

    if isinstance(exc, llm_client.LLMNotReadyError):
        return _finish(diagnose_llm_status(exc.status, context=context), exc, context, step)

    if isinstance(exc, llm_client.LLMUnavailableError):
        return _finish(
            Diagnosis(
                summary="LM Studioに接続できません。",
                category="ai_provider",
                cause_known=True,
                cause="LM Studioのローカルサーバーに接続できませんでした。",
                facts=["LM StudioのAPIエンドポイントへの接続に失敗しました。"],
                suggestions=[
                    Suggestion("LM Studioを起動し、ローカルサーバーを有効にする", "recheck_status"),
                    Suggestion("状態を再確認", "recheck_status"),
                    Suggestion("再試行", "retry"),
                ],
            ),
            exc,
            context,
            step,
        )

    if isinstance(exc, llm_client.LLMResponseError):
        if "no model" in text and "loaded" in text:
            return _finish(
                Diagnosis(
                    summary="使用予定のモデルがロードされていません。",
                    category="model",
                    cause_known=True,
                    cause=(
                        "LM Studioには接続できていますが、生成に使用するモデルが"
                        "ロードされていません。"
                    ),
                    facts=[
                        "LM Studioサーバーには接続できました。",
                        "APIは応答しましたが、エラーを返しました。",
                        "現在ロードされているモデルはありません。",
                    ],
                    suggestions=[
                        Suggestion("LM StudioでDeveloper/ServerからモデルをLoadする", "recheck_status"),
                        Suggestion("状態を再確認", "recheck_status"),
                        Suggestion("再試行", "retry"),
                    ],
                ),
                exc,
                context,
                step,
            )
        if "model" in text and ("not found" in text or "does not exist" in text):
            return _finish(
                Diagnosis(
                    summary="指定されたモデルがLM Studioで利用できません。",
                    category="model",
                    cause_known=True,
                    cause="設定されているモデル名がLM Studioにロードされているモデルと一致しません。",
                    facts=[
                        "LM Studioサーバーには接続できました。",
                        "APIは応答しましたが、モデルが見つからないエラーを返しました。",
                    ],
                    suggestions=[
                        Suggestion("設定のモデル名とLM Studioでロード中のモデル名を確認する", "recheck_status"),
                        Suggestion("再試行", "retry"),
                    ],
                ),
                exc,
                context,
                step,
            )
        return _finish(
            Diagnosis(
                summary="LM StudioがAPIエラーを返しました。",
                category="api",
                cause_known=True,
                cause="LM StudioのAPIリクエストがエラーで終了しました。",
                facts=["LM Studioサーバーには接続できました。", "APIがエラーを返しました。"],
                suggestions=[Suggestion("詳細ログを見る", "view_log"), Suggestion("再試行", "retry")],
            ),
            exc,
            context,
            step,
        )

    if exc_name in ("ProductionError", "AIEditError") and "json" in text:
        return _finish(
            Diagnosis(
                summary="AIモデルの出力を解釈できませんでした。",
                category="model",
                cause_known=True,
                cause=(
                    "AIモデルの応答がJSON形式として不正でした。"
                    "小型・低精度なモデルほど発生しやすい問題です。"
                ),
                facts=["LM Studioからの応答は受信できました。", "応答の形式が期待するJSONと一致しませんでした。"],
                suggestions=[
                    Suggestion("より大きい/高精度なモデルへの切り替えを検討", "recheck_status"),
                    Suggestion("再試行", "retry"),
                ],
            ),
            exc,
            context,
            step,
        )

    if "out of memory" in text or isinstance(exc, MemoryError):
        return _finish(
            Diagnosis(
                summary="処理に失敗しました。",
                category="memory",
                cause_known=True,
                cause=(
                    "選択したモデル・解像度・フレーム数に対して、現在のPCのメモリが"
                    "不足している可能性があります。"
                ),
                suggestions=[
                    Suggestion("解像度とフレーム数を下げて再試行", "apply_lightweight_preset"),
                    Suggestion("再試行", "retry"),
                ],
            ),
            exc,
            context,
            step,
        )

    if any(
        k in text
        for k in ("connectionerror", "timeout", "max retries exceeded", "name resolution", "httpstatuserror")
    ):
        return _finish(
            Diagnosis(
                summary="モデルのダウンロードに失敗しました。",
                category="network",
                cause_known=True,
                cause=(
                    "初回利用時のモデルダウンロード中にネットワークエラーが発生しました。"
                    "インターネット接続、またはファイアウォール/プロキシ設定が原因の可能性があります。"
                ),
                suggestions=[Suggestion("再試行", "retry")],
            ),
            exc,
            context,
            step,
        )

    if "no space left" in text or "disk quota" in text:
        return _finish(
            Diagnosis(
                summary="処理に失敗しました。",
                category="resource",
                cause_known=True,
                cause=f"ストレージの空き容量が不足しています(モデル保存先: {MODELS_ROOT})。",
                suggestions=[Suggestion("空き容量を確認してから再試行", "check_disk")],
            ),
            exc,
            context,
            step,
        )

    if "ffmpeg" in text or ("imageio" in text and "codec" in text):
        return _finish(
            Diagnosis(
                summary="動画の書き出し/処理に失敗しました。",
                category="ffmpeg",
                cause_known=True,
                cause="FFmpeg/コーデック関連の処理でエラーが発生しました。FFmpegが正しくインストールされているか確認してください。",
                suggestions=[Suggestion("再試行", "retry")],
            ),
            exc,
            context,
            step,
        )

    if "cannot identify image" in text or "unidentifiedimageerror" in text:
        return _finish(
            Diagnosis(
                summary="画像の読み込みに失敗しました。",
                category="input_material",
                cause_known=True,
                cause="アップロードされたファイルが対応形式(JPG/JPEG/PNG/WebP)の画像として認識できませんでした。",
                suggestions=[Suggestion("別の画像で再試行", "retry")],
            ),
            exc,
            context,
            step,
        )

    return _finish(
        Diagnosis(
            summary="処理に失敗しました。",
            category="unknown",
            cause_known=False,
            cause="原因を特定できませんでした。",
            candidates=[
                "PCのメモリ/ストレージ不足",
                "モデルファイルの破損(再ダウンロードで解消する場合があります)",
                "Python/PyTorch/diffusers等の環境不整合",
                "入力データの形式・破損",
            ],
            suggestions=[Suggestion("再試行", "retry"), Suggestion("詳細ログを見る", "view_log")],
        ),
        exc,
        context,
        step,
    )
