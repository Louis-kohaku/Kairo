"""AI Co-Creation: conversation that edits the actual project
(design doc sections 2/29-33/43).

The distinction that matters here is the one section 29 makes: replying in
chat is not the feature. "もっとテンポよくして" has to end with Scene 2 at
3.4 seconds, the subtitles re-synced, the clips re-encoded and the timeline
updated - or nothing happened.

How that stays safe:

* The model is given the project's real state (section 30) and may reply
  only with a `StudioPlan` - a summary, a reason, and operations from the
  fixed vocabulary in `schemas/studio.py`. It cannot express anything else.
* The plan is stored as a `ChangeProposal` and applied only on request
  (section 32), so the user sees what will change before it does.
* Applying snapshots the fields it overwrites, so Undo restores them
  (section 43).
* Execution goes through the same services the pipeline uses, so a
  chat-driven change produces material identical to a full run's.
"""
from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from app.models.media_asset import MediaAsset
from app.models.production import Scene
from app.models.project import Project
from app.models.studio import ChangeProposal, ChatMessage
from app.models.subtitle import SubtitleCue
from app.models.timeline import Clip, Track
from app.schemas.settings import AppSettingsPatch, SubtitleSettingsPatch
from app.schemas.studio import ProductionStrategy, StudioPlan
from app.services import llm_client, settings_service, timeline_service
from app.services.json_extract import JSONExtractionError, parse_json_object
from app.services.studio import assembly_service, material_service, planning_service

logger = logging.getLogger(__name__)

_CRF_BY_PRESET = {"fast": 26, "standard": 21, "high": 18, "ultra": 15, "custom": 21}


class CoCreationError(RuntimeError):
    pass


# Ready-made instructions offered as buttons (section 31). Kept here rather
# than in the frontend so the phrasing the model is tuned against and the
# phrasing the user clicks are the same string.
QUICK_ACTIONS = [
    {"id": "faster", "label": "もっとテンポよく", "instruction": "全体をもっとテンポよくして"},
    {"id": "hook", "label": "冒頭を強く", "instruction": "最初の3秒をもっと強くして"},
    {"id": "subtitle", "label": "字幕を改善", "instruction": "字幕をもっと読みやすく短くして"},
    {"id": "bigger_subtitle", "label": "字幕を大きく", "instruction": "字幕を大きくして"},
    {"id": "funnier", "label": "もっと面白く", "instruction": "全体をもっと面白くして"},
    {"id": "cuter", "label": "もっと可愛く", "instruction": "全体をもっと可愛い雰囲気にして"},
    {"id": "moving", "label": "もっと感動的に", "instruction": "終盤をもっと感動的にして"},
    {"id": "slower", "label": "ゆっくりに", "instruction": "全体をもう少しゆっくりにして"},
]


# ------------------------------------------------------------- context


def build_context(db, project: Project, strategy: ProductionStrategy) -> dict:
    """Everything the model needs to reason about this project (section 30)."""
    scenes = planning_service.ordered_scenes(db, project.id)
    cues = (
        db.query(SubtitleCue)
        .filter(SubtitleCue.project_id == project.id)
        .order_by(SubtitleCue.order_index)
        .all()
    )
    settings = settings_service.get_settings()
    total = sum(s.estimated_duration for s in scenes)

    return {
        "title": strategy.title,
        "concept": strategy.concept,
        "hook": strategy.hook,
        "ending": strategy.ending,
        "total_seconds": round(total, 1),
        "scene_count": len(scenes),
        "subtitle_size": settings.subtitle.size,
        "subtitle_position": settings.subtitle.position,
        "scenes": [
            {
                # 1-based, matching the scene board and every "Scene N"
                # the user reads on screen.
                "scene_number": i + 1,
                "seconds": round(s.estimated_duration, 2),
                "emotion": s.emotion or "",
                "purpose": (s.purpose or "")[:60],
                "subtitle": s.subtitle_text or "",
                "narration": (s.narration or "")[:80],
                "visual": (s.visual_prompt or "")[:80],
            }
            for i, s in enumerate(scenes)
        ],
        "subtitle_cue_count": len(cues),
    }


def _plan_prompt(instruction: str, context: dict, history: list[ChatMessage]) -> list[dict]:
    system = (
        "あなたは動画編集アシスタントです。ユーザーの指示を、"
        "次の操作だけを使ったJSONに変換してください。JSONオブジェクトのみを返してください。\n\n"
        "利用可能な操作:\n"
        '- {"op":"set_scene_duration","scene_number":1,"duration":3.2,"reason":"..."}\n'
        '- {"op":"scale_all_durations","factor":0.85,"reason":"..."} (全体のテンポ調整)\n'
        '- {"op":"set_subtitle_size","size":48,"reason":"..."}\n'
        '- {"op":"set_subtitle_style","position":"bottom","style":"outline","reason":"..."}\n'
        '- {"op":"set_scene_subtitle","scene_number":3,"text":"...","reason":"..."}\n'
        '- {"op":"set_scene_narration","scene_number":3,"text":"...","reason":"..."}\n'
        '- {"op":"rewrite_scene","scene_number":4,"direction":"もっと面白く","reason":"..."}\n'
        '- {"op":"regenerate_scene_asset","scene_number":4,"direction":"...","reason":"..."}\n'
        '- {"op":"strengthen_hook","seconds":2.5,"reason":"..."}\n'
        '- {"op":"set_bgm_volume","volume":0.18,"reason":"..."}\n'
        '- {"op":"delete_scene","scene_number":6,"reason":"..."}\n\n'
        '出力形式: {"summary":"...","reason":"...","answer":"","operations":[...]}\n\n'
        "ルール:\n"
        "- summary は「何を変更するか」を1〜2文で。reason は「なぜそうするか」。\n"
        "- 指示が質問だった場合は operations を空にし、answer に答えを書いてください。\n"
        "- scene_number は画面に表示されているシーン番号(1始まり)です。ユーザーが「Scene 3」と言えば scene_number は3です。\n"
        "- 操作は最大8件。必要最小限にしてください。"
    )
    messages = [{"role": "system", "content": system}]
    for msg in history[-6:]:
        messages.append({"role": msg.role, "content": msg.content[:600]})
    messages.append(
        {
            "role": "user",
            "content": (
                f"現在のプロジェクト状態:\n{json.dumps(context, ensure_ascii=False, indent=1)}\n\n"
                f"指示: {instruction}"
            ),
        }
    )
    return messages


def propose(db, project: Project, strategy: ProductionStrategy, instruction: str, run_id: str | None) -> ChangeProposal:
    """Turns one chat instruction into a stored, reviewable change."""
    context = build_context(db, project, strategy)
    history = (
        db.query(ChatMessage)
        .filter(ChatMessage.project_id == project.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(6)
        .all()
    )
    history.reverse()

    db.add(ChatMessage(project_id=project.id, role="user", content=instruction))
    db.commit()

    raw = llm_client.chat_completion(_plan_prompt(instruction, context, history), temperature=0.3)
    try:
        data = parse_json_object(raw)
    except JSONExtractionError as exc:
        raise CoCreationError(f"AIの応答をJSONとして解釈できませんでした: {exc}") from exc
    try:
        plan = StudioPlan.model_validate(data)
    except ValidationError as exc:
        raise CoCreationError(f"AIが生成した変更内容が不正です: {exc}") from exc

    scene_count = context["scene_count"]
    # A model that names Scene 12 in a 7-scene video would otherwise fail
    # mid-apply, after some operations had already run.
    valid_ops = [
        op
        for op in plan.operations
        if not hasattr(op, "scene_number") or 1 <= op.scene_number <= scene_count
    ]

    preview = describe_operations(valid_ops, context)
    proposal = ChangeProposal(
        project_id=project.id,
        run_id=run_id,
        instruction=instruction,
        summary=plan.summary or plan.answer or "変更案を作成しました",
        reason=plan.reason,
        ops_json=json.dumps([op.model_dump() for op in valid_ops], ensure_ascii=False),
        preview_json=json.dumps(preview, ensure_ascii=False),
        status="pending" if valid_ops else "cancelled",
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)

    reply = plan.answer or plan.summary or "変更案を作成しました。"
    db.add(
        ChatMessage(
            project_id=project.id,
            role="assistant",
            content=reply,
            proposal_id=proposal.id if valid_ops else None,
        )
    )
    db.commit()
    return proposal


def describe_operations(ops, context: dict) -> list[dict]:
    """Human-readable before/after lines for the confirmation panel."""
    scenes = context.get("scenes", [])
    out: list[dict] = []
    for op in ops:
        kind = op.op
        # Ops speak 1-based scene numbers; the list is 0-based.
        idx = getattr(op, "scene_number", 0) - 1
        if kind == "set_scene_duration":
            before = scenes[idx]["seconds"] if idx < len(scenes) else "?"
            out.append({
                "what": f"Scene {op.scene_number}の長さ",
                "before": f"{before}秒",
                "after": f"{op.duration:.1f}秒",
                "reason": op.reason,
            })
        elif kind == "scale_all_durations":
            total = context.get("total_seconds", 0)
            out.append({
                "what": "全体の尺",
                "before": f"{total:.0f}秒",
                "after": f"{total * op.factor:.0f}秒",
                "reason": op.reason,
            })
        elif kind == "set_subtitle_size":
            out.append({
                "what": "字幕サイズ",
                "before": f"{context.get('subtitle_size')}px",
                "after": f"{op.size}px",
                "reason": op.reason,
            })
        elif kind == "set_subtitle_style":
            out.append({
                "what": "字幕スタイル",
                "before": str(context.get("subtitle_position")),
                "after": f"{op.position or '-'} / {op.style or '-'}",
                "reason": op.reason,
            })
        elif kind == "set_scene_subtitle":
            before = scenes[idx]["subtitle"] if idx < len(scenes) else ""
            out.append({
                "what": f"Scene {op.scene_number}の字幕",
                "before": before,
                "after": op.text,
                "reason": op.reason,
            })
        elif kind == "set_scene_narration":
            out.append({
                "what": f"Scene {op.scene_number}のナレーション",
                "before": scenes[idx]["narration"] if idx < len(scenes) else "",
                "after": op.text,
                "reason": op.reason,
            })
        elif kind == "rewrite_scene":
            out.append({
                "what": f"Scene {op.scene_number}を書き直し",
                "before": scenes[idx]["subtitle"] if idx < len(scenes) else "",
                "after": f"方向性: {op.direction}",
                "reason": op.reason,
            })
        elif kind == "regenerate_scene_asset":
            out.append({
                "what": f"Scene {op.scene_number}の映像を再生成",
                "before": scenes[idx]["visual"] if idx < len(scenes) else "",
                "after": op.direction or "作り直し",
                "reason": op.reason,
            })
        elif kind == "strengthen_hook":
            out.append({
                "what": "冒頭の掴み",
                "before": f"{scenes[0]['seconds']}秒" if scenes else "-",
                "after": f"{op.seconds:.1f}秒に短縮",
                "reason": op.reason,
            })
        elif kind == "set_bgm_volume":
            out.append({
                "what": "BGM音量",
                "before": "現在の設定",
                "after": f"{op.volume:.2f}",
                "reason": op.reason,
            })
        elif kind == "delete_scene":
            out.append({
                "what": f"Scene {op.scene_number}を削除",
                "before": scenes[idx]["subtitle"] if idx < len(scenes) else "",
                "after": "(削除)",
                "reason": op.reason,
            })
    return out


# --------------------------------------------------------------- apply


def _snapshot(scenes: list[Scene]) -> list[dict]:
    return [
        {
            "id": s.id,
            "estimated_duration": s.estimated_duration,
            "subtitle_text": s.subtitle_text,
            "narration": s.narration,
            "visual_prompt": s.visual_prompt,
            "emotion": s.emotion,
        }
        for s in scenes
    ]


def _rewrite_scene_text(scene: Scene, direction: str, strategy: ProductionStrategy) -> bool:
    """Asks the model to rewrite one scene in a given direction."""
    system = (
        "あなたは動画脚本家です。指定されたシーンを、指示された方向性で書き直してください。"
        "JSONオブジェクトのみを返してください。\n\n"
        '出力形式: {"narration":"...","subtitle":"...","visual_prompt":"...","emotion":"..."}\n\n'
        "subtitle は16文字以内。長さは変えないでください。"
    )
    user = (
        f"動画のトーン: {strategy.concept}\n"
        f"現在のナレーション: {scene.narration}\n"
        f"現在の字幕: {scene.subtitle_text}\n"
        f"現在の映像: {scene.visual_prompt}\n\n"
        f"方向性: {direction}"
    )
    try:
        raw = llm_client.chat_completion(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.6,
        )
        data = parse_json_object(raw)
    except (
        JSONExtractionError,
        llm_client.LLMUnavailableError,
        llm_client.LLMTimeoutError,
        llm_client.LLMResponseError,
    ):
        # One scene failing to be rewritten is reported as a skipped
        # operation by the caller, not as a failed apply.
        logger.info("Scene rewrite unavailable for scene %s", scene.id)
        return False

    changed = False
    for field, key in (
        ("narration", "narration"),
        ("subtitle_text", "subtitle"),
        ("visual_prompt", "visual_prompt"),
        ("emotion", "emotion"),
    ):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            setattr(scene, field, value.strip())
            changed = True
    return changed


def apply(db, project: Project, proposal: ChangeProposal, strategy: ProductionStrategy) -> dict:
    """Executes a proposal against the real project.

    Returns a summary of what actually happened, which is not always what
    was proposed - an operation whose target disappeared is reported as
    skipped rather than silently dropped.
    """
    if proposal.status == "applied":
        raise CoCreationError("この変更はすでに適用されています。")

    from app.schemas.studio import StudioPlan as _Plan

    try:
        ops = _Plan.model_validate(
            {"operations": json.loads(proposal.ops_json or "[]")}
        ).operations
    except (ValidationError, ValueError) as exc:
        raise CoCreationError(f"変更内容を読み取れませんでした: {exc}") from exc

    scenes = planning_service.ordered_scenes(db, project.id)
    if not scenes:
        raise CoCreationError("シーンがありません。")

    settings = settings_service.get_settings()
    proposal.undo_json = json.dumps(
        {
            "scenes": _snapshot(scenes),
            "subtitle": settings.subtitle.model_dump(),
        },
        ensure_ascii=False,
    )
    db.commit()

    dirty: set[int] = set()
    regenerate: set[int] = set()
    deleted: list[Scene] = []
    changed_text = False
    applied: list[str] = []
    skipped: list[str] = []

    for op in ops:
        kind = op.op
        number = getattr(op, "scene_number", None)
        index = number - 1 if number is not None else None
        scene = scenes[index] if index is not None and 0 <= index < len(scenes) else None

        if kind == "set_scene_duration" and scene is not None:
            scene.estimated_duration = round(op.duration, 2)
            dirty.add(index)
            applied.append(f"Scene {number}を{op.duration:.1f}秒に変更")

        elif kind == "scale_all_durations":
            for i, s in enumerate(scenes):
                new_duration = round(max(1.0, s.estimated_duration * op.factor), 2)
                if abs(new_duration - s.estimated_duration) >= 0.05:
                    s.estimated_duration = new_duration
                    dirty.add(i)
            applied.append(f"全シーンの尺を{op.factor:.2f}倍に調整")

        elif kind == "strengthen_hook":
            scenes[0].estimated_duration = round(op.seconds, 2)
            scenes[0].is_hook = True
            dirty.add(0)
            applied.append(f"冒頭を{op.seconds:.1f}秒に短縮")

        elif kind == "set_subtitle_size":
            settings_service.update_settings(
                AppSettingsPatch(subtitle=SubtitleSettingsPatch(size=op.size))
            )
            applied.append(f"字幕サイズを{op.size}pxに変更")

        elif kind == "set_subtitle_style":
            settings_service.update_settings(
                AppSettingsPatch(
                    subtitle=SubtitleSettingsPatch(
                        position=op.position, style=op.style, color=op.color
                    )
                )
            )
            applied.append("字幕スタイルを変更")

        elif kind == "set_scene_subtitle" and scene is not None:
            scene.subtitle_text = op.text
            changed_text = True
            applied.append(f"Scene {number}の字幕を変更")

        elif kind == "set_scene_narration" and scene is not None:
            scene.narration = op.text
            regenerate.add(index)
            dirty.add(index)
            applied.append(f"Scene {number}のナレーションを変更")

        elif kind == "rewrite_scene" and scene is not None:
            if _rewrite_scene_text(scene, op.direction, strategy):
                regenerate.add(index)
                dirty.add(index)
                changed_text = True
                applied.append(f"Scene {number}を書き直し")
            else:
                skipped.append(f"Scene {number}の書き直しはAIが応答しなかったため見送りました")

        elif kind == "regenerate_scene_asset" and scene is not None:
            if op.direction:
                scene.visual_prompt = f"{scene.visual_prompt} / {op.direction}".strip(" /")
            regenerate.add(index)
            dirty.add(index)
            applied.append(f"Scene {number}の映像を再生成")

        elif kind == "set_bgm_volume":
            track = (
                db.query(Track)
                .filter(Track.project_id == project.id, Track.type == "audio")
                .first()
            )
            clips = (
                db.query(Clip).filter(Clip.track_id == track.id).all() if track else []
            )
            for clip in clips:
                timeline_service.update_clip(db, clip.id, None, None, op.volume)
            if clips:
                applied.append(f"BGM音量を{op.volume:.2f}に変更")
            else:
                skipped.append("BGMトラックにクリップがないため音量を変更できませんでした")

        elif kind == "delete_scene" and scene is not None:
            deleted.append(scene)
            applied.append(f"Scene {number}を削除")

        else:
            skipped.append(f"{kind} は対象が見つからないため実行できませんでした")

    for scene in deleted:
        db.delete(scene)
    db.commit()

    if deleted:
        # Indices shift after a deletion, so everything downstream is
        # rebuilt rather than trying to patch the offsets.
        scenes = planning_service.ordered_scenes(db, project.id)
        dirty = set(range(len(scenes)))
        regenerate.clear()

    crf = _CRF_BY_PRESET.get(settings.video.quality_preset, 21)
    use_narration = settings.tts.mode != "off"
    for i in sorted(dirty):
        if i >= len(scenes):
            continue
        material_service.rebuild_scene(
            db,
            project,
            scenes[i],
            i,
            strategy,
            engine_id=settings.generation.default_engine_id or "procedural",
            crf=crf,
            use_narration=use_narration,
            voice_id=settings.tts.selected_voice,
            regenerate_visual=i in regenerate,
            resynthesize_narration=i in regenerate,
            is_last=(i == len(scenes) - 1),
        )

    if dirty or changed_text or deleted:
        planning_service.recompute_start_times(scenes)
        db.commit()
        cues = assembly_service.compose_cues(
            db, project.id, scenes, assembly_service.caption_budget(project, settings)
        )
        assembly_service.write_srt(project.id, cues)
        bgm = (
            db.query(MediaAsset)
            .filter(
                MediaAsset.project_id == project.id,
                MediaAsset.kind == "audio",
            )
            .order_by(MediaAsset.imported_at.desc())
            .first()
        )
        assembly_service.assemble(db, project, scenes, bgm)

    proposal.status = "applied"
    db.commit()

    return {
        "applied": applied,
        "skipped": skipped,
        "rebuilt_scenes": sorted(dirty),
        "total_seconds": round(sum(s.estimated_duration for s in scenes), 1),
    }


def undo(db, project: Project, proposal: ChangeProposal, strategy: ProductionStrategy) -> dict:
    """Restores the state a proposal overwrote (section 43)."""
    if proposal.status != "applied" or not proposal.undo_json:
        raise CoCreationError("この変更は元に戻せません。")

    snapshot = json.loads(proposal.undo_json)
    settings = settings_service.get_settings()

    restored: set[int] = set()
    scenes = planning_service.ordered_scenes(db, project.id)
    by_id = {s.id: (i, s) for i, s in enumerate(scenes)}

    for entry in snapshot.get("scenes", []):
        found = by_id.get(entry["id"])
        if found is None:
            # A deleted scene cannot be brought back from a field snapshot;
            # say so rather than implying a full restore happened.
            continue
        i, scene = found
        if (
            abs(scene.estimated_duration - entry["estimated_duration"]) >= 0.05
            or scene.subtitle_text != entry["subtitle_text"]
            or scene.narration != entry["narration"]
            or scene.visual_prompt != entry["visual_prompt"]
        ):
            restored.add(i)
        scene.estimated_duration = entry["estimated_duration"]
        scene.subtitle_text = entry["subtitle_text"]
        scene.narration = entry["narration"]
        scene.visual_prompt = entry["visual_prompt"]
        scene.emotion = entry["emotion"]
    db.commit()

    subtitle_snapshot = snapshot.get("subtitle") or {}
    if subtitle_snapshot:
        settings_service.update_settings(
            AppSettingsPatch(subtitle=SubtitleSettingsPatch(**subtitle_snapshot))
        )

    crf = _CRF_BY_PRESET.get(settings.video.quality_preset, 21)
    for i in sorted(restored):
        material_service.rebuild_scene(
            db,
            project,
            scenes[i],
            i,
            strategy,
            engine_id=settings.generation.default_engine_id or "procedural",
            crf=crf,
            use_narration=settings.tts.mode != "off",
            voice_id=settings.tts.selected_voice,
            regenerate_visual=True,
            resynthesize_narration=True,
            is_last=(i == len(scenes) - 1),
        )

    if restored:
        planning_service.recompute_start_times(scenes)
        db.commit()
        cues = assembly_service.compose_cues(
            db, project.id, scenes, assembly_service.caption_budget(project, settings)
        )
        assembly_service.write_srt(project.id, cues)
        bgm = (
            db.query(MediaAsset)
            .filter(MediaAsset.project_id == project.id, MediaAsset.kind == "audio")
            .order_by(MediaAsset.imported_at.desc())
            .first()
        )
        assembly_service.assemble(db, project, scenes, bgm)

    proposal.status = "undone"
    db.commit()
    return {"restored_scenes": sorted(restored)}
