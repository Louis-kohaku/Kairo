"""The canonical production pipeline (design doc sections 1/5/46).

One ordered list, used by every consumer: the Full Auto orchestrator runs
it, the progress UI renders it, resume finds its restart point in it, and
the event log labels itself from it. Nothing else is allowed to invent its
own step names - that is exactly how the old UI ended up claiming stages
that had no implementation behind them.

Each phase carries the *user-facing* language for what it is doing and why,
so the "AIが何をしているのか分からない" problem is solved by data rather
than by scattering Japanese strings through the orchestrator.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Phase:
    id: str
    label: str
    # One line describing what this phase is for, shown under the current
    # task so the user understands the *purpose*, not just the name.
    purpose: str
    # Rough share of total wall-clock, used only to turn per-phase progress
    # into a single overall percentage. Weights, not promises.
    weight: float = 1.0
    # Phases that produce nothing when the pipeline is offline / degraded
    # are allowed to report "skipped" instead of failing the whole run.
    skippable: bool = False


PHASES: tuple[Phase, ...] = (
    Phase("environment", "制作環境確認", "FFmpeg・保存先・メモリなど、制作に必要な環境を確認します", 0.5),
    Phase("models", "AIモデル確認", "今回の制作で使うAIモデルを決定し、使用できる状態か確認します", 0.5),
    Phase(
        "material_analysis",
        "素材解析",
        "ユーザーがアップロードした写真・動画に何が写っているかを解析します",
        2.0,
        skippable=True,
    ),
    Phase("research", "Webリサーチ", "同じテーマの動画がどう作られているかを調べます", 2.0, skippable=True),
    Phase("trends", "トレンド分析", "調査結果から共通パターンと差別化の余地を抽出します", 1.5, skippable=True),
    Phase("strategy", "制作戦略", "この動画の狙い・テンポ・字幕・音の方針を決めます", 1.5),
    Phase("planning", "企画", "タイトル・視聴者・トーン・構成を決めます", 1.5),
    Phase("script", "脚本", "話す内容と画面に出す言葉を書きます", 2.0),
    Phase("scenes", "Scene設計", "シーンごとの尺・感情・カメラ・映像内容を設計します", 2.0),
    Phase(
        "material_match",
        "素材マッチング",
        "どのシーンにどの素材を使うかを決め、不足している素材を洗い出します",
        1.5,
    ),
    Phase("assets", "素材生成", "ユーザー素材を優先して各シーンの映像を用意し、不足分だけを補完します", 6.0),
    Phase("narration", "音声", "ナレーション音声を合成し、実測の長さでシーンを再調整します", 3.0, skippable=True),
    Phase("audio", "BGM / SFX", "BGMと効果音を用意し、ナレーションを邪魔しない音量に整えます", 2.0, skippable=True),
    Phase("subtitles", "字幕", "シーンの字幕を短く読みやすく整え、タイミングを合わせます", 1.5),
    Phase("assembly", "編集", "素材・音声・字幕をタイムラインに並べます", 1.5),
    Phase("quality_check", "品質チェック", "構成・テンポ・Hook・字幕・音などをAIが点検します", 2.0),
    Phase("improvement", "自動改善", "見つかった問題を自動で修正します", 1.5),
    Phase("recheck", "再チェック", "修正後にもう一度品質を確認します", 1.0),
    Phase("preview", "プレビュー準備", "再生できる状態に整えます", 0.5),
    Phase("render", "書き出し", "FFmpegで実際のMP4を書き出します", 6.0),
    Phase("done", "完成", "動画が完成しました", 0.2),
)

PHASE_IDS: tuple[str, ...] = tuple(p.id for p in PHASES)
PHASE_BY_ID: dict[str, Phase] = {p.id: p for p in PHASES}

_TOTAL_WEIGHT = sum(p.weight for p in PHASES)


def index_of(phase_id: str) -> int:
    try:
        return PHASE_IDS.index(phase_id)
    except ValueError:
        return -1


def label(phase_id: str) -> str:
    phase = PHASE_BY_ID.get(phase_id)
    return phase.label if phase else phase_id


def next_phase(phase_id: str) -> Phase | None:
    i = index_of(phase_id)
    if i < 0 or i + 1 >= len(PHASES):
        return None
    return PHASES[i + 1]


def overall_progress(phase_id: str, within_phase: float = 0.0) -> float:
    """Blend "which phase" and "how far through it" into one 0-100 number.

    `within_phase` is 0.0-1.0. A phase that reports no internal progress
    still moves the bar when it completes, so the bar never sits frozen
    through a long stage.
    """
    i = index_of(phase_id)
    if i < 0:
        return 0.0
    done = sum(p.weight for p in PHASES[:i])
    current = PHASES[i].weight * max(0.0, min(1.0, within_phase))
    return round((done + current) / _TOTAL_WEIGHT * 100, 1)
