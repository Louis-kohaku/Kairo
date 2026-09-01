"""The AI-editing orchestrator (design doc section 4/14): turns one natural
language instruction into a validated EditPlan JSON document via the local
LLM, then executes it by dispatching each operation to the same internal
services the manual UI buttons use (silence detection, subtitle
generation, timeline edits) - the LLM never touches ffmpeg or the
filesystem directly.
"""
from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from app.core.config import LLM_MAX_OPERATIONS
from app.core.db import SessionLocal
from app.core.paths import project_dir
from app.models.job import Job
from app.models.media_asset import MediaAsset
from app.models.project import Project
from app.models.timeline import Track
from app.schemas.edit_plan import EditPlan, GenerateSubtitlesOp, RemoveSilenceOp, SetBgmVolumeOp
from app.services import llm_client, subtitle_service, timeline_service
from app.services.ffmpeg.silence import compute_keep_segments, detect_silence
from app.services.json_extract import JSONExtractionError, parse_json_object

logger = logging.getLogger(__name__)

_OP_LABELS = {
    "remove_silence": "無音カット",
    "generate_subtitles": "字幕生成",
    "set_bgm_volume": "BGM音量調整",
}


class AIEditError(RuntimeError):
    pass


def _update_job(job_id: str, **fields) -> None:
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return
        for key, value in fields.items():
            setattr(job, key, value)
        db.commit()
    finally:
        db.close()


def _build_prompt(instruction: str, media_assets: list[MediaAsset]) -> list[dict]:
    asset_list = [
        {"id": a.id, "filename": a.original_filename, "kind": a.kind}
        for a in media_assets
    ]
    system = (
        "あなたはローカル動画編集ソフトのAI編集アシスタントです。"
        "ユーザーの指示を、次に挙げる操作だけを使ったJSONに変換してください。"
        "他の操作や説明文は一切出力せず、JSONオブジェクトのみを返してください。\n\n"
        "利用可能な操作:\n"
        '- {"op": "remove_silence", "media_asset_id": "<id>", "noise_db": -30, "min_duration": 0.5} '
        "(指定したメディアの無音区間を検出して除去する)\n"
        '- {"op": "generate_subtitles"} (タイムライン全体の字幕をAIで生成する)\n'
        '- {"op": "set_bgm_volume", "volume": 0.25} (BGMトラックの音量を0.0〜2.0で設定する)\n\n'
        f"利用可能なメディア一覧: {json.dumps(asset_list, ensure_ascii=False)}\n\n"
        '出力形式: {"operations": [ ... ]}'
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": instruction},
    ]


def _parse_plan(raw_text: str) -> EditPlan:
    try:
        data = parse_json_object(raw_text)
    except JSONExtractionError as exc:
        raise AIEditError(f"AIの応答をJSONとして解釈できませんでした: {exc}") from exc

    try:
        plan = EditPlan.model_validate(data)
    except ValidationError as exc:
        raise AIEditError(f"AIが生成した編集指示が不正です: {exc}") from exc

    if len(plan.operations) > LLM_MAX_OPERATIONS:
        raise AIEditError(
            f"AIが生成した操作数が上限({LLM_MAX_OPERATIONS})を超えています"
        )
    return plan


def _execute_remove_silence(db, project_id: str, video_track: Track, op: RemoveSilenceOp) -> None:
    asset = db.get(MediaAsset, op.media_asset_id)
    if asset is None or asset.project_id != project_id:
        raise AIEditError(f"指定されたメディア({op.media_asset_id})が見つかりません")

    path = project_dir(project_id) / asset.stored_path
    silences = detect_silence(path, asset.duration, op.noise_db, op.min_duration)
    keep = compute_keep_segments(asset.duration, silences, 0.15, 0.15)
    if not keep:
        raise AIEditError("無音カットの結果、残るクリップがありませんでした")

    existing = [c for c in video_track.clips if c.media_asset_id == op.media_asset_id]
    insert_at = min((c.order_index for c in existing), default=None)
    for clip in existing:
        timeline_service.delete_clip(db, clip.id)

    for i, (start, end) in enumerate(keep):
        index = None if insert_at is None else insert_at + i
        timeline_service.add_clip(db, video_track.id, op.media_asset_id, start, end, 1.0, index)


def _execute_set_bgm_volume(db, project_id: str, op: SetBgmVolumeOp) -> None:
    project = db.get(Project, project_id)
    audio_track = next((t for t in project.tracks if t.type == "audio"), None)
    if audio_track is None or not audio_track.clips:
        raise AIEditError("BGMトラックにクリップがありません")
    for clip in audio_track.clips:
        timeline_service.update_clip(db, clip.id, None, None, op.volume)


def run_ai_edit(project_id: str, job_id: str, instruction: str) -> None:
    db = SessionLocal()
    try:
        project = db.get(Project, project_id)
        if project is None:
            raise AIEditError(f"Project {project_id} not found")

        video_track = next((t for t in project.tracks if t.type == "video"), None)
        if video_track is None:
            raise AIEditError("映像トラックが見つかりません")

        media_assets = (
            db.query(MediaAsset).filter(MediaAsset.project_id == project_id).all()
        )

        _update_job(job_id, status="running", progress=2.0, message="AIに問い合わせ中")
        response_text = llm_client.chat_completion(_build_prompt(instruction, media_assets))
        plan = _parse_plan(response_text)

        if not plan.operations:
            _update_job(
                job_id,
                status="completed",
                progress=100.0,
                message="AIは実行可能な操作を提案しませんでした",
            )
            return

        n = len(plan.operations)
        done_labels: list[str] = []

        for i, op in enumerate(plan.operations):
            label = _OP_LABELS.get(op.op, op.op)
            _update_job(
                job_id,
                progress=round(10 + i / n * 85, 1),
                message=f"実行中: {label} ({i + 1}/{n})",
            )

            if isinstance(op, RemoveSilenceOp):
                _execute_remove_silence(db, project_id, video_track, op)
            elif isinstance(op, GenerateSubtitlesOp):

                def on_progress(pct: float, msg: str, i=i, n=n) -> None:
                    _update_job(job_id, progress=round(10 + (i + pct / 100) / n * 85, 1), message=msg)

                subtitle_service.generate_cues_for_project(project_id, on_progress)
            elif isinstance(op, SetBgmVolumeOp):
                _execute_set_bgm_volume(db, project_id, op)

            done_labels.append(label)

        _update_job(
            job_id,
            status="completed",
            progress=100.0,
            message=f"{n}件の操作を実行しました: {', '.join(done_labels)}",
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the job row for the UI
        logger.exception("AI edit job %s failed", job_id)
        _update_job(job_id, status="failed", error=str(exc), message="AI編集に失敗しました")
    finally:
        db.close()
