"""The Full Auto orchestrator (design doc sections 1/46).

One instruction in, one playable MP4 out, with every step reported as it
happens. The pipeline is a straight sequence of the phases in `phases.py`;
each one is a small method that emits what it is doing, does it, records
itself as complete, and hands over.

Three properties are worth calling out, because they are what the design
asks for and they shaped the code:

**It does not ask questions.** Every decision that could have been a prompt
- research on or off, which voice, which visual engine, how long a scene
should be - has a resolved default from settings or the strategy. A user
who walks away comes back to a finished video.

**It can be interrupted safely.** `control.checkpoint()` is called between
scenes and between phases, so Pause parks the run and Stop unwinds it
without a half-written encode. Nothing is thrown away: completed phases are
recorded on the run row and per-scene material is written to deterministic
paths, so Resume re-enters at the first unfinished phase and skips scenes
whose files already exist. That is what makes "Scene 4の素材生成から再開し
ます" literally true.

**A failure keeps the work.** An exception is turned into a `Diagnosis` by
the existing `ai_diagnostics` module and stored on the run, while every
scene, asset, cue and timeline row produced so far stays exactly where it
is (section 36).
"""
from __future__ import annotations

import json
import logging
import time

from app.core.config import LLM_BASE_URL
from app.core.db import SessionLocal
from app.models.job import Job
from app.models.media_asset import MediaAsset
from app.models.production import Chapter
from app.models.project import Project
from app.models.studio import ProductionRun
from app.schemas.studio import ProductionStrategy, ResearchResult
from app.services import (
    ai_diagnostics,
    llm_client,
    llm_preflight,
    render_service,
    settings_service,
    tts_service,
)
from app.services.ffmpeg.util import require_binary
from app.services.studio import (
    assembly_service,
    control,
    events,
    material_service,
    model_service,
    phases,
    planning_service,
    quality_service,
    research_service,
)
from app.services.studio.control import RunStopped

logger = logging.getLogger(__name__)

# CRF per quality preset, mirroring the editor's own mapping so a studio
# render and a manual render of the same project produce the same file.
_CRF_BY_PRESET = {"fast": 26, "standard": 21, "high": 18, "ultra": 15, "custom": 21}


class PipelineError(RuntimeError):
    pass


class Pipeline:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.db = SessionLocal()
        self.run: ProductionRun = self.db.get(ProductionRun, run_id)
        if self.run is None:
            raise PipelineError(f"Production run {run_id} not found")
        self.project: Project = self.db.get(Project, self.run.project_id)
        if self.project is None:
            raise PipelineError(f"Project {self.run.project_id} not found")

        self.settings = settings_service.get_settings()
        self.model_id: str = ""
        self.strategy: ProductionStrategy = planning_service.strategy_from_json(
            self.run.strategy_json
        )
        self.research: ResearchResult = self._load_research()
        self.scenes: list = []
        # Resolved lazily rather than in phase_environment: a resumed run
        # skips that phase, and every later phase still needs to know
        # whether narration is possible.
        self._narration_available: bool | None = None
        self._bgm_asset: MediaAsset | None = None
        self.completed: set[str] = {
            p for p in (self.run.completed_phases or "").split(",") if p
        }

    # ------------------------------------------------------------ helpers

    def _load_research(self) -> ResearchResult:
        if not self.run.research_json:
            return ResearchResult()
        try:
            return ResearchResult.model_validate(json.loads(self.run.research_json))
        except Exception:
            return ResearchResult()

    def event(
        self,
        phase: str,
        *,
        task: str = "",
        status: str = "running",
        level: str = "user",
        message: str = "",
        reason: str = "",
        next_task: str = "",
        target: str = "",
        scene_id: str | None = None,
        within_phase: float = 0.0,
        error: dict | None = None,
    ) -> None:
        events.emit(
            self.run_id,
            self.project.id,
            phase=phase,
            task=task,
            status=status,
            level=level,
            message=message,
            reason=reason,
            next_task=next_task,
            target=target,
            scene_id=scene_id,
            within_phase=within_phase,
            model=self.model_id,
            error=error,
        )

    def _finish_phase(self, phase_id: str, message: str = "") -> None:
        self.completed.add(phase_id)
        self.run.completed_phases = ",".join(
            p for p in phases.PHASE_IDS if p in self.completed
        )
        self.db.commit()
        nxt = phases.next_phase(phase_id)
        self.event(
            phase_id,
            status="done",
            message=message or f"{phases.label(phase_id)}が完了しました",
            next_task=nxt.label if nxt else "",
            within_phase=1.0,
        )

    def _skip_phase(self, phase_id: str, reason: str) -> None:
        self.completed.add(phase_id)
        self.run.completed_phases = ",".join(
            p for p in phases.PHASE_IDS if p in self.completed
        )
        self.db.commit()
        self.event(phase_id, status="skipped", message=reason, within_phase=1.0)

    @property
    def has_narration(self) -> bool:
        if self._narration_available is None:
            if self.settings.tts.mode == "off" or not tts_service.is_supported_platform():
                self._narration_available = False
            else:
                self._narration_available = bool(tts_service.list_voices())
        return self._narration_available

    @property
    def bgm_asset(self) -> MediaAsset | None:
        """The BGM this run produced.

        Re-read from the database when it isn't in memory, because a
        resumed run skips the audio phase and `assemble()` would otherwise
        clear a music track it was told nothing about.
        """
        if self._bgm_asset is None:
            self._bgm_asset = (
                self.db.query(MediaAsset)
                .filter(
                    MediaAsset.project_id == self.project.id,
                    MediaAsset.kind == "audio",
                    MediaAsset.original_filename.like("AI生成BGM%"),
                )
                .order_by(MediaAsset.imported_at.desc())
                .first()
            )
        return self._bgm_asset

    def _caption_budget(self) -> int:
        return assembly_service.caption_budget(self.project, self.settings)

    def _target_seconds(self) -> float:
        return max(5.0, float(self.run.target_duration_seconds))

    def _crf(self) -> int:
        return _CRF_BY_PRESET.get(self.settings.video.quality_preset, 21)

    # ------------------------------------------------------------- phases

    def phase_environment(self) -> None:
        self.event(
            "environment",
            task="制作環境を確認しています",
            message="FFmpeg・保存先・音声合成の状態を確認します",
            next_task="AIモデル確認",
        )
        try:
            require_binary("ffmpeg")
        except Exception as exc:
            raise PipelineError(
                f"FFmpegが見つかりません。動画を書き出せないため制作を開始できません。({exc})"
            ) from exc
        self.event("environment", level="tech", message="ffmpeg: available", status="info")

        voices = tts_service.list_voices() if tts_service.is_supported_platform() else []
        self.event(
            "environment",
            level="tech",
            status="info",
            message=f"TTS voices: {len(voices)} / narration={'on' if self.has_narration else 'off'}",
        )
        self._finish_phase("environment", "制作環境の確認が完了しました")

    def phase_models(self) -> None:
        self.event(
            "models",
            task="使用するAIモデルを確認しています",
            message="LM Studioの状態と、今回使うモデルを確認します",
            next_task="Webリサーチ",
        )
        log_lines: list[str] = []
        status = llm_preflight.run_check(log_lines)
        for line in log_lines:
            self.event("models", level="tech", status="info", message=line)

        if not status.ready:
            raise llm_client.LLMNotReadyError(status)

        self.model_id = status.configured_model or ""
        plan = model_service.build_plan(
            want_narration=self.has_narration,
            want_research=True,
        )
        self.run.model_plan_json = json.dumps(plan.to_dict(), ensure_ascii=False)
        self.db.commit()

        for warning in plan.warnings:
            self.event("models", status="info", message=warning)

        self._finish_phase("models", f"使用モデル: {self.model_id}")

    def phase_research(self) -> None:
        self.event(
            "research",
            task="Webで同じテーマの動画の作り方を調べています",
            message="検索クエリを作成しています",
            reason="よくある構成とテンポを把握し、そこから差別化するため",
            next_task="トレンド分析",
        )

        def on_progress(msg: str) -> None:
            self.event("research", task="Webリサーチ", message=msg, within_phase=0.5)

        self.research = research_service.run_research(
            self.run.instruction, enabled=True, on_progress=on_progress
        )
        self.run.research_json = research_service.to_json(self.research)
        self.db.commit()

        if not self.research.performed:
            self._skip_phase(
                "research",
                f"Webリサーチは実行できませんでした（{self.research.skipped_reason}）。"
                "一般的なショート動画の定石で制作を続けます。",
            )
            return
        self._finish_phase(
            "research",
            f"{len(self.research.sources)}件を参照しました",
        )

    def phase_trends(self) -> None:
        trends = self.research.trends
        self.event(
            "trends",
            task="調査結果を共通トレンドと差別化点に整理しています",
            message=(
                f"共通トレンド{len(trends.common_patterns)}件 / "
                f"差別化の余地{len(trends.differentiation)}件を抽出しました"
            ),
            reason="真似ではなく、傾向を踏まえた上で独自性を出すため",
            next_task="制作戦略",
        )
        for pattern in trends.common_patterns[:5]:
            self.event("trends", status="info", message=f"共通: {pattern}")
        for diff in trends.differentiation[:4]:
            self.event("trends", status="info", message=f"差別化: {diff}")
        self._finish_phase("trends")

    def phase_strategy(self) -> None:
        self.event(
            "strategy",
            task="制作戦略を決めています",
            message="Hook・テンポ・字幕・音・終わり方の方針を決定します",
            next_task="企画",
        )
        self.strategy = planning_service.generate_strategy(
            self.run.instruction,
            self._target_seconds(),
            self.research,
            self.run.orientation,
        )
        self.run.strategy_json = json.dumps(self.strategy.model_dump(), ensure_ascii=False)
        self.db.commit()
        self.event(
            "strategy",
            status="info",
            message=f"Hook: {self.strategy.hook}",
            reason=f"差別化: {self.strategy.differentiation}",
        )
        self._finish_phase("strategy", f"戦略「{self.strategy.title}」を決定しました")

    def phase_planning(self) -> None:
        self.event(
            "planning",
            task="企画と構成を作っています",
            message="タイトル・視聴者・トーンと、幕構成を決めます",
            next_task="脚本",
        )
        plan, budgets = planning_service.generate_plan(
            self.run.instruction, self.strategy, self._target_seconds()
        )
        self._plan = plan
        self._budgets = budgets

        planning_service.clear_previous_plan(self.db, self.project.id)
        self._chapters: list[Chapter] = []
        for i, chapter in enumerate(plan.chapters):
            row = Chapter(
                project_id=self.project.id,
                order_index=i,
                title=chapter.title,
                summary=chapter.summary,
            )
            self.db.add(row)
            self._chapters.append(row)
        self.db.commit()
        for row in self._chapters:
            self.db.refresh(row)

        self.event(
            "planning",
            status="info",
            message=f"「{plan.title}」/ {len(plan.chapters)}幕構成",
            reason=f"対象: {plan.target_audience} / トーン: {plan.tone}",
        )
        self._finish_phase("planning")

    def _restore_plan(self) -> None:
        """Rebuilds the planning phase's in-memory output from the database.

        Needed when a run resumes at the script phase: the plan and its
        chapter rows were committed by the previous process, but this one
        never executed `phase_planning` to hold them.
        """
        from app.models.production import ProductionSpec
        from app.schemas.production import ChapterOutline, PlanOutline

        chapters = (
            self.db.query(Chapter)
            .filter(Chapter.project_id == self.project.id)
            .order_by(Chapter.order_index)
            .all()
        )
        if not chapters:
            raise PipelineError("企画データが見つかりません。企画からやり直してください。")

        spec = self.db.get(ProductionSpec, self.project.id)
        self._chapters = chapters
        self._plan = PlanOutline(
            title=(spec.title if spec else self.strategy.title) or "無題",
            target_audience=(spec.target_audience if spec else "") or "一般視聴者",
            tone=(spec.tone if spec else "") or "標準",
            chapters=[ChapterOutline(title=c.title, summary=c.summary) for c in chapters],
        )
        # Budgets are an intermediate that was never persisted, so they are
        # re-derived by the same rule the planning phase falls back to.
        n = len(chapters)
        target = self._target_seconds()
        hook = min(5.0, target * 0.12)
        rest = (target - hook) / max(1, n - 1) if n > 1 else target
        self._budgets = [hook] + [rest] * (n - 1)

    def phase_script(self) -> None:
        if getattr(self, "_plan", None) is None or not getattr(self, "_chapters", None):
            self._restore_plan()
        plan = self._plan
        chapters = self._chapters
        budgets = self._budgets

        chapter_scenes = []
        previous_tail = ""
        used_visuals: list[str] = []
        n = len(chapters)
        for i, chapter in enumerate(chapters):
            control.checkpoint(self.run_id)
            self.event(
                "script",
                task=f"第{i + 1}幕の脚本を書いています",
                target=chapter.title,
                message=f"「{chapter.title}」のナレーションと字幕を作成しています",
                reason=chapter.summary[:100],
                next_task="Scene設計" if i == n - 1 else f"第{i + 2}幕",
                within_phase=i / n,
            )
            designs = planning_service.generate_scenes(
                plan,
                self.strategy,
                chapter.title,
                chapter.summary,
                budgets[i] if budgets and i < len(budgets) else self._target_seconds() / n,
                is_first_chapter=(i == 0),
                is_last_chapter=(i == n - 1),
                previous_tail=previous_tail,
                used_visuals=used_visuals,
            )
            chapter_scenes.append((chapter, designs))
            used_visuals.extend(d.visual_prompt for d in designs if d.visual_prompt)
            if designs:
                previous_tail = designs[-1].continuity or designs[-1].narration

        self.scenes = planning_service.persist_plan(
            self.db,
            self.project.id,
            self.run.instruction,
            self._target_seconds(),
            plan,
            self.strategy,
            chapter_scenes,
        )
        total = sum(s.estimated_duration for s in self.scenes)
        self._finish_phase(
            "script", f"{len(self.scenes)}シーンの脚本ができました（推定{total:.0f}秒）"
        )

    def phase_scenes(self) -> None:
        self._ensure_scenes()
        self.event(
            "scenes",
            task="シーンの尺と流れを整えています",
            message="目標尺に合わせてシーンの長さを調整します",
            next_task="素材生成",
        )
        planning_service.retime_scenes(self.scenes, self._target_seconds(), self.strategy)
        self.db.commit()
        total = sum(s.estimated_duration for s in self.scenes)
        self.event(
            "scenes",
            status="info",
            message=f"{len(self.scenes)}シーン / 合計{total:.1f}秒に調整しました",
            reason=f"1シーン{self.strategy.scene_seconds_min:.1f}〜{self.strategy.scene_seconds_max:.1f}秒を基準",
        )
        self._finish_phase("scenes")

    def phase_assets(self) -> None:
        self._ensure_scenes()
        engine_id = self.settings.generation.default_engine_id or "procedural"
        n = len(self.scenes)
        for i, scene in enumerate(self.scenes):
            control.checkpoint(self.run_id)
            nxt = f"Scene {i + 2}" if i + 1 < n else "音声"
            self.event(
                "assets",
                task=f"Scene {i + 1}の映像を作成しています",
                target=f"Scene {i + 1}「{(scene.subtitle_text or scene.visual_prompt or '')[:24]}」",
                message=(scene.visual_prompt or "")[:80],
                reason=scene.purpose or "",
                next_task=nxt,
                scene_id=scene.id,
                within_phase=i / max(1, n),
            )
            user_source = material_service.resolve_user_source(self.db, scene, self.project.id)
            if user_source is not None:
                self.event(
                    "assets",
                    status="info",
                    scene_id=scene.id,
                    message="ユーザーが指定した素材を使用します",
                )
                continue
            material_service.render_scene_visual(
                scene, i, self.project, self.strategy, engine_id=engine_id
            )
            scene.status = "generated"
            self.db.commit()
        self._finish_phase("assets", f"{n}シーン分の映像素材を用意しました")

    def phase_narration(self) -> None:
        self._ensure_scenes()
        if not self.has_narration:
            self._skip_phase(
                "narration",
                "この環境では音声合成が使えないため、ナレーション無しで制作します。",
            )
            return

        voice_id = self.settings.tts.selected_voice
        n = len(self.scenes)
        spoken = 0
        for i, scene in enumerate(self.scenes):
            control.checkpoint(self.run_id)
            self.event(
                "narration",
                task=f"Scene {i + 1}のナレーションを合成しています",
                target=f"Scene {i + 1}",
                message=(scene.narration or "")[:60],
                next_task=f"Scene {i + 2}" if i + 1 < n else "BGM / SFX",
                scene_id=scene.id,
                within_phase=i / max(1, n),
            )
            path, seconds = material_service.synthesize_narration(
                scene, i, self.project.id, voice_id
            )
            if path is None:
                continue
            spoken += 1
            scene.narration_duration = seconds
            if material_service.retime_from_narration(
                scene, seconds, self.strategy.scene_seconds_max + 3.0
            ):
                self.event(
                    "narration",
                    status="info",
                    scene_id=scene.id,
                    message=f"Scene {i + 1}の尺を{scene.estimated_duration:.1f}秒に調整しました",
                    reason="ナレーションが途中で切れないようにするため",
                )
            self.db.commit()

        planning_service.recompute_start_times(self.scenes)
        self.db.commit()
        self._finish_phase("narration", f"{spoken}シーン分のナレーションを合成しました")

    def phase_audio(self) -> None:
        self._ensure_scenes()
        total = sum(s.estimated_duration for s in self.scenes)
        mood = self.strategy.bgm_mood or "gentle"
        self.event(
            "audio",
            task="BGMを用意しています",
            message=f"雰囲気「{mood}」のBGMを{total:.0f}秒分生成します",
            reason=self.strategy.audio_policy or "ナレーションを邪魔しない音量で敷きます",
            next_task="字幕",
        )
        self._bgm_asset = assembly_service.build_bgm(self.db, self.project, total, mood)
        if self._bgm_asset is None:
            self._skip_phase("audio", "BGMを生成できませんでした。無音で制作を続けます。")
            return
        self._finish_phase("audio", "BGMと効果音を用意しました")

    def phase_subtitles(self) -> None:
        self._ensure_scenes()
        self.event(
            "subtitles",
            task="字幕を整えています",
            message="1行の文字数と表示タイミングを調整します",
            reason=self.strategy.subtitle_policy or "スマートフォンで一目で読めるようにするため",
            next_task="編集",
        )
        cues = assembly_service.compose_cues(
            self.db, self.project.id, self.scenes, self._caption_budget()
        )
        assembly_service.write_srt(self.project.id, cues)
        self._finish_phase("subtitles", f"{len(cues)}件の字幕を作成しました")

    def phase_assembly(self) -> None:
        self._ensure_scenes()
        n = len(self.scenes)
        for i, scene in enumerate(self.scenes):
            control.checkpoint(self.run_id)
            self.event(
                "assembly",
                task=f"Scene {i + 1}を映像クリップに書き出しています",
                target=f"Scene {i + 1}",
                message=f"{scene.estimated_duration:.1f}秒のクリップを作成します",
                next_task=f"Scene {i + 2}" if i + 1 < n else "品質チェック",
                scene_id=scene.id,
                within_phase=i / max(1, n),
            )
            self._build_clip(scene, i)

        self.db.commit()
        duration = assembly_service.assemble(self.db, self.project, self.scenes, self.bgm_asset)
        self._finish_phase("assembly", f"タイムラインに{n}シーン（{duration:.0f}秒）を並べました")

    def phase_quality_check(self) -> None:
        self._ensure_scenes()
        self.event(
            "quality_check",
            task="完成した構成を点検しています",
            message="構成・テンポ・Hook・字幕・音をチェックします",
            next_task="自動改善",
        )
        report = quality_service.check(
            self.scenes,
            self.strategy,
            target_seconds=self._target_seconds(),
            has_narration=self.has_narration,
            has_bgm=self.bgm_asset is not None,
        )
        self.run.quality_json = quality_service.report_to_json(report)
        self.db.commit()
        self._report = report

        for issue in report.issues[:6]:
            self.event(
                "quality_check",
                status="info",
                scene_id=(
                    self.scenes[issue.scene_index].id
                    if issue.scene_index is not None and 0 <= issue.scene_index < len(self.scenes)
                    else None
                ),
                message=issue.detail,
                reason=issue.suggestion,
            )
        self._finish_phase(
            "quality_check", f"品質スコア {report.score:.0f}点 / 指摘{len(report.issues)}件"
        )

    def phase_improvement(self) -> None:
        self._ensure_scenes()
        report = getattr(self, "_report", None)
        if report is None:
            self._skip_phase("improvement", "品質チェック結果がないため改善をスキップしました")
            return

        self.event(
            "improvement",
            task="見つかった問題を自動修正しています",
            message=f"{len(report.issues)}件の指摘を確認しています",
            next_task="再チェック",
        )
        improvement, dirty = quality_service.improve(
            self.db, self.scenes, report, self.strategy, target_seconds=self._target_seconds()
        )

        for change in improvement.applied:
            self.event(
                "improvement",
                status="info",
                message=f"{change.what}: {change.before} → {change.after}",
                reason=change.reason,
            )

        if dirty:
            # Duration changes invalidate the encoded clips, so the touched
            # scenes are re-rendered and the timeline rebuilt - otherwise
            # the "改善しました" message would be about numbers that the
            # actual video never reflected.
            planning_service.recompute_start_times(self.scenes)
            self.db.commit()
            for i in sorted(dirty):
                control.checkpoint(self.run_id)
                scene = self.scenes[i]
                self.event(
                    "improvement",
                    task=f"Scene {i + 1}を作り直しています",
                    scene_id=scene.id,
                    message=f"変更後の{scene.estimated_duration:.1f}秒で再生成します",
                )
                self._build_clip(scene, i)
            cues = assembly_service.compose_cues(
                self.db, self.project.id, self.scenes, self._caption_budget()
            )
            assembly_service.write_srt(self.project.id, cues)
            assembly_service.assemble(self.db, self.project, self.scenes, self.bgm_asset)

        self.run.improvement_json = json.dumps(improvement.model_dump(), ensure_ascii=False)
        self.db.commit()
        self._improvement = improvement
        self._finish_phase(
            "improvement",
            f"{len(improvement.applied)}件を自動修正しました"
            if improvement.applied
            else "自動修正が必要な問題はありませんでした",
        )

    def phase_recheck(self) -> None:
        self._ensure_scenes()
        self.event(
            "recheck",
            task="修正後の品質を再確認しています",
            message="もう一度チェックします",
            next_task="プレビュー準備",
        )
        report = quality_service.check(
            self.scenes,
            self.strategy,
            target_seconds=self._target_seconds(),
            has_narration=self.has_narration,
            has_bgm=self.bgm_asset is not None,
            use_ai=False,
        )
        self.run.quality_json = quality_service.report_to_json(report)
        improvement = getattr(self, "_improvement", None)
        if improvement is not None:
            improvement.score_after = report.score
            self.run.improvement_json = json.dumps(improvement.model_dump(), ensure_ascii=False)
        self.db.commit()
        self._finish_phase("recheck", f"再チェック完了: {report.score:.0f}点")

    def phase_preview(self) -> None:
        self.event(
            "preview",
            task="プレビューを準備しています",
            message="タイムラインと字幕を確認できる状態にします",
            next_task="書き出し",
        )
        self._finish_phase("preview", "プレビューできます")

    def phase_render(self) -> None:
        burn = self.settings.subtitle.enabled
        job = Job(project_id=self.project.id, type="render", status="pending")
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        self.run.render_job_id = job.id
        self.db.commit()

        self.event(
            "render",
            task="FFmpegでMP4を書き出しています",
            message="シーンを連結し、BGMと字幕を合成します",
            reason="最終的なMP4ファイルを作成するため",
            next_task="完成",
        )
        self.event(
            "render",
            level="tech",
            status="info",
            message=f"render job {job.id} / burn_subtitles={burn} / crf={self._crf()}",
        )

        render_service.run_render(self.project.id, job.id, burn, self._crf())

        self.db.expire_all()
        finished = self.db.get(Job, job.id)
        if finished is None or finished.status != "completed":
            detail = (finished.error if finished else None) or "書き出しに失敗しました"
            raise PipelineError(detail)

        self.run.output_path = finished.output_path
        self.db.commit()
        self._finish_phase("render", "MP4の書き出しが完了しました")

    def phase_done(self) -> None:
        duration = sum(s.estimated_duration for s in self.scenes) if self.scenes else 0.0
        self.event(
            "done",
            status="done",
            task="完成",
            message=f"動画が完成しました（約{duration:.0f}秒）",
            within_phase=1.0,
        )
        self.completed.add("done")
        self.run.completed_phases = ",".join(p for p in phases.PHASE_IDS if p in self.completed)
        self.run.status = "completed"
        self.run.progress = 100.0
        self.db.commit()

    # ------------------------------------------------------------ support

    def _ensure_scenes(self) -> None:
        """Loads the project's scenes if this process didn't create them.

        Resume enters the pipeline partway through, so anything after the
        script phase has to be able to pick the scenes back up from the
        database rather than assuming an in-memory list.
        """
        if not self.scenes:
            self.scenes = planning_service.ordered_scenes(self.db, self.project.id)
        if not self.scenes:
            raise PipelineError("シーンが存在しません。企画からやり直してください。")

    def _build_clip(self, scene, index: int) -> None:
        """Renders one scene's clip and registers it.

        Delegates to the shared rebuild path so a pipeline-produced clip
        and a co-creation-produced clip are byte-for-byte the same
        operation; existing stills and narration on disk are reused, which
        is what makes resume and single-scene edits cheap.
        """
        material_service.rebuild_scene(
            self.db,
            self.project,
            scene,
            index,
            self.strategy,
            engine_id=self.settings.generation.default_engine_id or "procedural",
            crf=self._crf(),
            use_narration=self.has_narration,
            voice_id=self.settings.tts.selected_voice,
            is_last=(index == len(self.scenes) - 1),
        )

    # --------------------------------------------------------------- run

    _ORDER = (
        ("environment", "phase_environment"),
        ("models", "phase_models"),
        ("research", "phase_research"),
        ("trends", "phase_trends"),
        ("strategy", "phase_strategy"),
        ("planning", "phase_planning"),
        ("script", "phase_script"),
        ("scenes", "phase_scenes"),
        ("assets", "phase_assets"),
        ("narration", "phase_narration"),
        ("audio", "phase_audio"),
        ("subtitles", "phase_subtitles"),
        ("assembly", "phase_assembly"),
        ("quality_check", "phase_quality_check"),
        ("improvement", "phase_improvement"),
        ("recheck", "phase_recheck"),
        ("preview", "phase_preview"),
        ("render", "phase_render"),
        ("done", "phase_done"),
    )

    def execute(self) -> None:
        started = time.time()
        current = "environment"
        try:
            self.run.status = "running"
            self.run.error = None
            self.run.error_detail = None
            self.db.commit()

            for phase_id, method_name in self._ORDER:
                current = phase_id
                if phase_id in self.completed and phase_id != "done":
                    self.event(
                        phase_id,
                        status="done",
                        message=f"{phases.label(phase_id)}は完了済みのためスキップします",
                        within_phase=1.0,
                    )
                    continue
                control.checkpoint(self.run_id)
                getattr(self, method_name)()

            self.event(
                "done",
                level="tech",
                status="info",
                message=f"total elapsed {time.time() - started:.1f}s",
            )
        except RunStopped as exc:
            self.run.status = "stopped"
            self.run.resume_phase = current
            self.db.commit()
            self.event(current, status="paused", message=str(exc))
        except Exception as exc:  # noqa: BLE001 - surfaced to the run row
            logger.exception("Production run %s failed in phase %s", self.run_id, current)
            self.db.rollback()
            diagnosis = self._diagnose(exc, current)
            self.run.status = "failed"
            self.run.resume_phase = current
            self.run.error = diagnosis.summary
            self.run.error_detail = json.dumps(diagnosis.to_dict(), ensure_ascii=False)
            self.db.commit()
            self.event(
                current,
                status="failed",
                message=diagnosis.summary,
                reason=diagnosis.cause,
                error=diagnosis.to_dict(),
            )
        finally:
            control.clear(self.run_id)
            self.db.close()

    def _diagnose(self, exc: Exception, phase_id: str):
        status = (
            exc.status
            if isinstance(exc, llm_client.LLMNotReadyError)
            else llm_client.get_status()
        )
        context = ai_diagnostics.AIContext(
            provider="LM Studio",
            model=status.configured_model or "(未解決)",
            task=phases.label(phase_id),
            operation="Chat Completion",
            endpoint=f"{LLM_BASE_URL}/chat/completions",
            model_status=(
                "loaded"
                if status.can_generate
                else ("not_loaded" if status.api_ok else "unreachable")
            ),
            requested_model=status.configured_model or "",
            model_source=status.model_source,
            models_loaded=status.models_loaded,
            connection_status="OK" if status.server_reachable else "NG",
            error_code=status.error_code,
        )
        return ai_diagnostics.diagnose(exc, context=context, step=phase_id)


def run(run_id: str) -> None:
    """Entry point used by the job runner."""
    Pipeline(run_id).execute()
