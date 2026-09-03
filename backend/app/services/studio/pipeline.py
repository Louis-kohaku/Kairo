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
from app.models.subtitle import SubtitleCue
from app.schemas.material import ORIGIN_LABELS
from app.schemas.production_assets import AssetDecisions
from app.schemas.review import IterationRecord, VideoReview
from app.schemas.studio import ProductionStrategy, ResearchResult
from app.schemas.trend import TrendContext
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
    creative_director,
    events,
    material_analysis,
    material_plan,
    material_service,
    model_service,
    phases,
    planning_service,
    quality_service,
    refinement,
    report as report_service,
    research_service,
    reviewer,
)
from app.services.studio.control import RunStopped
from app.services.trends import service as trend_service

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
        # What the user gave us, and the decision about where it goes. The
        # plan is restored from the database rather than recomputed, so a
        # resumed run uses the material the user confirmed instead of
        # quietly re-deciding behind their back.
        # Two forms of the same brief. The act-structure prompt asks for
        # 3-5 acts; telling it "aim for ten scenes" in the same breath made
        # it emit ten acts, which is ten LLM calls and a video with no
        # structure. Only the scene writer - the stage that actually
        # decides how many shots there are - is given the count.
        self._material_hint: str = ""
        self._material_brief: str = ""
        self._material_plan = material_plan.from_json(self.run.material_plan_json)
        # 動画制作エージェント state. All restored from the run row rather
        # than recomputed, so a resumed run uses the trend data and the
        # asset choices the earlier phases actually acted on instead of
        # quietly re-deciding behind the user's back.
        self.trend: TrendContext = self._load_model(TrendContext, self.run.trend_json)
        self.decisions: AssetDecisions | None = (
            self._load_optional(AssetDecisions, self.run.assets_json)
        )
        self.review: VideoReview | None = self._load_optional(VideoReview, self.run.review_json)
        self.iterations: list[IterationRecord] = []
        self._subtitle_override = None
        self.completed: set[str] = {
            p for p in (self.run.completed_phases or "").split(",") if p
        }

    # ------------------------------------------------------------ helpers

    def _load_model(self, model_cls, raw: str | None):
        """Restores a stored pydantic payload, or an empty instance.

        Unreadable stored JSON is treated as absent rather than fatal: the
        phase that produced it can run again, and losing a run to a schema
        change would be a worse outcome than redoing one stage.
        """
        if not raw:
            return model_cls()
        try:
            return model_cls.model_validate(json.loads(raw))
        except Exception:
            logger.info("Could not restore %s from run %s", model_cls.__name__, self.run_id)
            return model_cls()

    def _load_optional(self, model_cls, raw: str | None):
        if not raw:
            return None
        try:
            return model_cls.model_validate(json.loads(raw))
        except Exception:
            logger.info("Could not restore %s from run %s", model_cls.__name__, self.run_id)
            return None

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

    def _selected_asset_ids(self) -> list[str]:
        try:
            return list(json.loads(self.run.selected_asset_ids or "[]"))
        except ValueError:
            return []

    def _material_mode(self) -> str:
        return self.run.material_mode or "ai_auto"

    def _build_material_hint(self, analyses: list, *, with_scene_count: bool = True) -> str:
        """The paragraph about the user's material that a writing prompt gets.

        Written as instructions rather than trivia: the writer is told to
        design shots that can actually be got from this material, which is
        what stops a script asking for footage nobody has and turning every
        beat into a shortage.

        `with_scene_count` is off for the act-structure prompt. That prompt
        asks for three to five acts; telling it "aim for ten scenes" in the
        same breath made it emit ten acts - ten LLM calls, and a video with
        no structure. Only the scene writer, the stage that actually decides
        how many shots there are, is given the count.
        """
        if not analyses:
            return (
                "【ユーザー素材】\n"
                "ユーザーは素材をアップロードしていません。映像はKairoが用意するため、"
                "特定の写真に依存しない構成にしてください。"
            )

        # Capped: this paragraph is repeated in every chapter's scene
        # prompt, and a local 7B model on CPU pays for every token of it.
        # Twelve items is enough for the writer to know what kind of
        # material it is designing for.
        lines = []
        for item in analyses[:12]:
            kind = {"image": "写真", "video": "動画"}.get(item.kind, item.kind)
            tags = "・".join(item.tags[:6]) or "内容不明"
            extra = ""
            if item.kind == "video" and item.duration:
                extra = f" / {item.duration:.1f}秒"
            lines.append(f"- {kind}: {tags}{extra}")

        photos = sum(1 for a in analyses if a.kind == "image")
        videos = sum(1 for a in analyses if a.kind == "video")
        count = max(1, photos + videos)

        if not with_scene_count:
            scene_guidance = ""
        elif self._material_mode() == "use_all":
            # "できるだけ全部使う" is a promise about the finished video, and
            # the only stage that can keep it is the one deciding how many
            # scenes there are: asking for fewer scenes than the user has
            # material would leave photos unused however the matching stage
            # behaved.
            scene_guidance = (
                "ユーザーは全ての素材を使うことを希望しています。"
                f"シーン数は必ず{count}以上にしてください。"
            )
        else:
            scene_guidance = f"シーン数はおおよそ{count}前後を目安にしてください。"

        return (
            "【ユーザーが用意した素材】\n"
            f"写真{photos}枚 / 動画{videos}本。内容は次のとおりです。\n"
            + "\n".join(lines)
            + "\n\nこの素材で撮れている画を優先してシーンを設計してください。"
            "visual_prompt は、できるだけ上記の素材で表現できる内容にしてください。"
            + scene_guidance
        )

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

        # The asset library has to exist before the audio phase asks it for
        # a BGM bed. Prepared here rather than there so a first run on a
        # fresh install spends its 30-odd seconds of FFmpeg synthesis in a
        # phase that says what it is doing, instead of appearing to stall
        # halfway through "BGMを選んでいます".
        from app.models.library import LibraryAsset

        needs_library = (
            self.db.query(LibraryAsset)
            .filter(LibraryAsset.kind.in_(("font", "music")))
            .count()
            == 0
        )
        if needs_library:
            self.event(
                "environment",
                task="素材ライブラリを準備しています",
                message="フォントを走査し、Kairo内蔵のBGM・効果音を生成します",
                reason="初回のみ実行されます（30秒ほどかかります）",
                within_phase=0.5,
            )
        try:
            creative_director.ensure_library(self.db)
        except Exception:
            # A missing library costs the run its music, not the run itself.
            logger.exception("Could not prepare the asset library")
            self.event(
                "environment",
                status="info",
                message="素材ライブラリを準備できませんでした。BGMはその場で合成します。",
            )

        counts = {
            kind: self.db.query(LibraryAsset).filter(LibraryAsset.kind == kind).count()
            for kind in ("font", "music", "sfx")
        }
        self.event(
            "environment",
            level="tech",
            status="info",
            message=(
                f"library: fonts={counts['font']} music={counts['music']} sfx={counts['sfx']}"
            ),
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

    def phase_material_analysis(self) -> None:
        """Works out what is in the photos and videos the user supplied.

        Runs before anything is written, because the script has to be able
        to ask for shots the user actually has. A project with no material
        skips this phase and says so: having no material is a supported way
        to use Kairo, not a missing step.
        """
        from app.services import media_service

        assets = media_service.list_user_material(self.db, self.project.id)
        # "選択した素材だけ使う" has to narrow what the *writer* is told as
        # well as what the matcher may use; a script written around ten
        # photos when two were selected is a script of shortages.
        if self._material_mode() == "selected":
            wanted = set(self._selected_asset_ids())
            assets = [a for a in assets if a.id in wanted]
        if not assets:
            self._material_hint = self._build_material_hint([])
            self._material_brief = self._material_hint
            self._skip_phase(
                "material_analysis",
                "ユーザー素材はありません。必要な素材はKairoが用意します。",
            )
            return

        vision = material_analysis.vision_available()
        self.event(
            "material_analysis",
            task="アップロードされた素材を解析しています",
            message="{0}点の素材を解析します".format(len(assets)),
            reason=(
                "写っているものを把握し、台本と素材を対応づけるため"
                if vision
                else "画像解析AIが無いため、解像度・明るさ・向き・ファイル名から把握します"
            ),
            next_task="Webリサーチ",
        )
        if not vision:
            self.event(
                "material_analysis",
                status="info",
                message=(
                    "画像を解析できるAIモデル（Vision対応）がLM Studioにロードされていません。"
                    "写っているものの自動認識は行わず、ファイル名と画像の特徴から推定します。"
                ),
            )

        analyses = []
        failed = 0
        n = len(assets)
        for i, asset in enumerate(assets):
            control.checkpoint(self.run_id)
            self.event(
                "material_analysis",
                task="素材 {0}/{1} を解析しています".format(i + 1, n),
                target=asset.original_filename,
                message=asset.original_filename,
                within_phase=i / max(1, n),
            )
            try:
                result = material_analysis.analyze_asset(self.db, asset)
            except Exception as exc:  # noqa: BLE001 - one bad file is not fatal
                failed += 1
                self.event(
                    "material_analysis",
                    status="failed",
                    target=asset.original_filename,
                    message="「{0}」を解析できませんでした".format(asset.original_filename),
                    reason=str(exc)[:200],
                )
                continue
            analyses.append(result)
            self.event(
                "material_analysis",
                level="tech",
                status="info",
                message="{0}: {1} ({2})".format(
                    asset.original_filename,
                    "・".join(result.tags[:6]) or "タグなし",
                    result.analyzed_by,
                ),
            )

        self._material_hint = self._build_material_hint(analyses)
        self._material_brief = self._build_material_hint(analyses, with_scene_count=False)
        summary = "{0}点の素材を解析しました".format(len(analyses))
        if failed:
            summary += "（{0}点は解析できませんでした）".format(failed)
        self._finish_phase("material_analysis", summary)

    def phase_material_match(self) -> None:
        """Decides which material goes into which scene, and what is missing."""
        self._ensure_scenes()
        mode = self._material_mode()
        mode_label = {
            "ai_auto": "AIにおまかせ",
            "use_all": "できるだけ全部使う",
            "selected": "選択した素材だけ使う",
        }.get(mode, mode)
        self.event(
            "material_match",
            task="どのシーンにどの素材を使うか決めています",
            message="素材の使い方: " + mode_label,
            reason="ユーザー素材を最優先し、足りない分だけを補完するため",
            next_task="素材生成",
        )
        plan = material_plan.build_plan(
            self.db,
            self.project.id,
            self.scenes,
            mode=mode,
            selected_ids=self._selected_asset_ids(),
            orientation=self.run.orientation,
        )
        material_plan.apply_plan(self.db, plan, self.scenes)
        self._material_plan = plan
        self.run.material_plan_json = material_plan.to_json(plan)
        self.db.commit()

        for assignment in plan.assignments:
            if assignment.origin != "user":
                continue
            self.event(
                "material_match",
                status="info",
                scene_id=self.scenes[assignment.scene_index].id,
                message="Scene {0}: {1}".format(assignment.scene_number, assignment.filename),
                reason=assignment.reason,
            )
        for shortage in plan.shortages:
            self.event(
                "material_match",
                status="info",
                scene_id=self.scenes[shortage.scene_index].id,
                message="Scene {0}: 不足素材「{1}」".format(shortage.scene_number, shortage.need),
                reason=shortage.fill_reason,
            )
        for note in plan.notes:
            self.event("material_match", status="info", message=note)

        used = plan.used_photo_count + plan.used_video_count
        self._finish_phase(
            "material_match",
            "ユーザー素材{0}点を{1}シーンに割り当て、不足{2}カットを補完します".format(
                used, len(self.scenes), len(plan.shortages)
            ),
        )

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
        """Two inputs, kept distinct.

        The Web research above is about *this subject* - how videos on this
        topic are usually built. Trend Intelligence is about *right now* -
        what the accumulated signals say people are watching in this genre,
        and what the genre's measured format conventions are. They answer
        different questions, so both are reported and neither is presented
        as the other.
        """
        trends = self.research.trends
        self.event(
            "trends",
            task="調査結果と蓄積トレンドを整理しています",
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

        self.trend = trend_service.build_context(self.db, self.run.instruction)
        self.run.trend_json = json.dumps(self.trend.model_dump(), ensure_ascii=False)
        self.db.commit()

        self.event(
            "trends",
            status="info",
            message=f"ジャンル判定: {self.trend.genre_label}",
            reason=self.trend.reason,
        )
        if self.trend.used:
            for signal in self.trend.signals[:5]:
                self.event(
                    "trends",
                    status="info",
                    message=f"トレンド: {signal.keyword}（{signal.platform} / スコア{signal.effective_score:.0f}）",
                    reason=signal.source,
                )
            profile = self.trend.profile
            if profile is not None:
                label = (
                    "トレンド分析による傾向"
                    if self.trend.profile_source == "llm"
                    else "Kairo組み込みの定石（トレンド実測値ではありません）"
                )
                self.event(
                    "trends",
                    status="info",
                    message=(
                        f"{self.trend.genre_label}の傾向: 尺{profile.duration_seconds or '-'}秒 / "
                        f"1カット{profile.scene_seconds or '-'}秒 / BGM {profile.bgm_mood or '-'}"
                    ),
                    reason=label,
                )
            self._finish_phase(
                "trends", f"{self.trend.genre_label}のトレンド{len(self.trend.signals)}件を反映しました"
            )
        else:
            self._finish_phase("trends", f"ジャンル定石で進めます（{self.trend.reason}）")

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
            material_hint=self._material_brief,
        )
        self._apply_genre_profile()
        self.run.strategy_json = json.dumps(self.strategy.model_dump(), ensure_ascii=False)
        self.db.commit()
        self.event(
            "strategy",
            status="info",
            message=f"Hook: {self.strategy.hook}",
            reason=f"差別化: {self.strategy.differentiation}",
        )
        self._finish_phase("strategy", f"戦略「{self.strategy.title}」を決定しました")

    def _apply_genre_profile(self) -> None:
        """Nudges the strategy towards the genre's measured conventions.

        Deliberately a nudge and not an override. The strategy was written
        for *this* brief; the profile knows what the genre usually does. So
        the cut length is blended rather than replaced, and the BGM mood is
        only taken when the strategy did not express one - a trend profile
        that silently discarded a deliberate creative choice would be worse
        than no profile.
        """
        profile = self.trend.profile if self.trend else None
        if profile is None or not self.trend.used:
            return

        changes: list[str] = []
        if profile.scene_seconds:
            before = self.strategy.scene_seconds_max
            blended = round((before + float(profile.scene_seconds) * 1.35) / 2.0, 2)
            if abs(blended - before) >= 0.2:
                self.strategy.scene_seconds_max = blended
                changes.append(f"1カットの上限 {before:.1f}秒 → {blended:.1f}秒")
        if profile.bgm_mood and not (self.strategy.bgm_mood or "").strip():
            self.strategy.bgm_mood = profile.bgm_mood
            changes.append(f"BGMの雰囲気を「{profile.bgm_mood}」に設定")

        for change in changes:
            self.event(
                "strategy",
                status="info",
                message=change,
                reason=f"{self.trend.genre_label}ジャンルの傾向に合わせたため",
            )

    def phase_planning(self) -> None:
        self.event(
            "planning",
            task="企画と構成を作っています",
            message="タイトル・視聴者・トーンと、幕構成を決めます",
            next_task="脚本",
        )
        plan, budgets = planning_service.generate_plan(
            self.run.instruction,
            self.strategy,
            self._target_seconds(),
            material_hint=self._material_brief,
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
                material_hint=self._material_hint,
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
        """Puts a real picture behind every scene.

        The order is the material priority order: a scene the matching
        stage pinned to the user's own photo or footage is left alone (the
        file itself is used at clip time), and only a scene nothing was
        left for is filled - from the web, from a diffusion model, or from
        Kairo's own composition, whichever is actually available. A scene
        is never given a generated background while the user's material
        sits unused, because the matching stage has already spent it.
        """
        self._ensure_scenes()
        engine_id = self.settings.generation.default_engine_id or "procedural"
        plan = self._material_plan
        sources = (
            plan.available_fill_sources
            if plan is not None
            else material_plan.available_fill_sources()
        )
        shortage_by_index = (
            {s.scene_index: s for s in plan.shortages} if plan is not None else {}
        )
        n = len(self.scenes)
        from_user = 0
        filled: dict[str, int] = {}

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
            pinned = material_service.resolve_pinned_source(self.db, scene, self.project.id)
            if pinned is not None:
                from_user += 1
                if not scene.material_origin:
                    scene.material_origin = "user" if scene.asset_source == "user" else "web"
                    self.db.commit()
                label = "写真" if pinned.kind == "image" else "動画"
                self.event(
                    "assets",
                    status="info",
                    scene_id=scene.id,
                    message=f"ユーザー素材（{label}）「{pinned.filename}」を使用します",
                    reason=scene.material_note or "",
                )
                continue

            shortage = shortage_by_index.get(i)
            keywords = (
                shortage.keywords
                if shortage is not None
                else material_plan.shortage_keywords(scene)
            )
            if plan is not None:
                origin, note = material_service.fill_missing_visual(
                    self.db,
                    self.project,
                    scene,
                    i,
                    self.strategy,
                    keywords=keywords,
                    sources=sources,
                    orientation=self.run.orientation,
                )
            else:
                # No plan (a resumed run from before this existed): keep the
                # original behaviour rather than inventing a new one.
                material_service.render_scene_visual(
                    scene, i, self.project, self.strategy, engine_id=engine_id
                )
                scene.material_origin = "procedural"
                origin, note = "procedural", ""
            filled[origin] = filled.get(origin, 0) + 1
            self.event(
                "assets",
                status="info",
                scene_id=scene.id,
                message=f"不足していた素材を補完しました（{ORIGIN_LABELS.get(origin, origin)}）",
                reason=note,
            )
            scene.status = "generated"
            self.db.commit()

        detail = "・".join(
            f"{ORIGIN_LABELS.get(k, k)}{v}" for k, v in filled.items()
        )
        summary = f"{n}シーン分の映像素材を用意しました（ユーザー素材{from_user}）"
        if detail:
            summary += f" / 補完: {detail}"
        self._finish_phase("assets", summary)

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
        """Choose the music and effects, then cut to the music.

        The order matters: the bed is chosen first because its tempo is what
        the scene lengths get snapped to, and the effects are placed last
        because their timestamps depend on the (possibly adjusted) scene
        boundaries.
        """
        self._ensure_scenes()
        total = sum(s.estimated_duration for s in self.scenes)
        mood = self.strategy.bgm_mood or "gentle"
        self.event(
            "audio",
            task="BGMと効果音を選んでいます",
            message=f"雰囲気「{mood}」に合うBGMをライブラリから選びます",
            reason=self.strategy.audio_policy or "ナレーションを邪魔しない音量で敷きます",
            next_task="字幕",
        )

        profile = self.trend.profile if self.trend and self.trend.used else None
        tempo = (profile.cut_tempo if profile and profile.cut_tempo else "medium")
        decisions = creative_director.build(
            self.db,
            genre=self.trend.genre if self.trend else "unknown",
            genre_label=self.trend.genre_label if self.trend else "",
            profile=profile,
            scenes=self.scenes,
            duration=total,
            mood=mood,
            tempo=tempo,
            subtitle_base=self.settings.subtitle,
            width=self.project.width,
            height=self.project.height,
            require_commercial=self.settings.library.prefer_commercial_safe,
            target_scene_seconds=max(1.2, self.strategy.scene_seconds_max * 0.8),
        )
        self.decisions = decisions
        self._persist_decisions()

        music = decisions.music
        if music is not None and music.found:
            self.event(
                "audio",
                status="info",
                message=(
                    f"BGM: {music.name}"
                    + (f"（{music.bpm:.0f}BPM）" if music.bpm else "")
                ),
                reason=f"{music.reason} / ライセンス: {music.license.status_label}（{music.license.name}）",
            )
            self._bgm_asset = creative_director.import_library_audio(
                self.db, self.project.id, music, origin="kairo_bgm", label="BGM"
            )
        else:
            self.event(
                "audio",
                status="info",
                message="ライブラリから使用できるBGMが選べませんでした。",
                reason=(music.reason if music else "") or "候補がありません",
            )
            self._bgm_asset = None

        # Falling back to synthesis rather than to silence: a generated bed
        # is licence-clean by construction, so there is never a reason for a
        # video to end up with no music because the library was empty.
        if self._bgm_asset is None:
            self._bgm_asset = assembly_service.build_bgm(self.db, self.project, total, mood)
            if self._bgm_asset is not None:
                self.event(
                    "audio",
                    status="info",
                    message="その場でBGMを合成しました。",
                    reason="ライブラリに条件に合う曲がなかったため",
                )

        beat = decisions.beat_sync
        if beat.applied:
            # Assembly re-encodes every scene clip after this phase, so
            # changing the durations here is enough - there is no separate
            # "re-render the touched scenes" step to schedule.
            changed = creative_director.apply_beat_sync(self.scenes, beat)
            if changed:
                planning_service.recompute_start_times(self.scenes)
                self.db.commit()
            self.event(
                "audio",
                status="info",
                message=f"カットを{beat.bpm:.0f}BPMのビートに合わせました",
                reason=beat.reason,
            )
        elif beat.reason:
            self.event("audio", status="info", message="ビート同期なし", reason=beat.reason)

        if decisions.sfx:
            kinds = ", ".join(sorted({p.category for p in decisions.sfx}))
            self.event(
                "audio",
                status="info",
                message=f"効果音{len(decisions.sfx)}箇所を配置しました（{kinds}）",
                reason="場面転換と冒頭・締めだけに絞り、使いすぎないようにしています",
            )

        if self._bgm_asset is None and not decisions.sfx:
            self._skip_phase("audio", "BGM・効果音を用意できませんでした。無音で制作を続けます。")
            return
        self._finish_phase("audio", "BGMと効果音を用意しました")

    def phase_subtitles(self) -> None:
        self._ensure_scenes()
        self.event(
            "subtitles",
            task="字幕を整えています",
            message="書体・1行の文字数・表示タイミングを調整します",
            reason=self.strategy.subtitle_policy or "スマートフォンで一目で読めるようにするため",
            next_task="編集",
        )

        decision = self.decisions.subtitle if self.decisions else None
        font = self.decisions.font if self.decisions else None
        if font is not None and font.found:
            self.event(
                "subtitles",
                status="info",
                message=f"字幕フォント: {font.family or font.name}",
                reason=(
                    f"{font.reason} / ライセンス: {font.license.status_label}"
                    f"（{font.license.name}）"
                ),
            )
        elif font is not None:
            self.event(
                "subtitles",
                status="info",
                message="フォントを自動選択できませんでした。設定のフォントを使用します。",
                reason=font.reason,
            )

        budget = decision.max_chars_per_line if decision and decision.max_chars_per_line else (
            self._caption_budget()
        )
        cues = assembly_service.compose_cues(self.db, self.project.id, self.scenes, budget)
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
        self._sync_plan_times()
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

    def _persist_decisions(self) -> None:
        if self.decisions is None:
            return
        self.run.assets_json = json.dumps(self.decisions.model_dump(), ensure_ascii=False)
        self.db.commit()

    def _subtitle_settings(self):
        """The caption style this run renders with.

        Built from the user's settings plus the agent's font choice, and
        never written back into settings - see render_service.run_render's
        `subtitle_override`.
        """
        if self.decisions is None:
            return None
        resolved, _decision = creative_director.subtitle_settings_for(
            self.settings.subtitle,
            self.decisions.font,
            self.trend.profile if self.trend and self.trend.used else None,
            width=self.project.width,
            height=self.project.height,
        )
        return resolved

    def _sfx_render_list(self):
        if self.decisions is None or not self.decisions.sfx:
            return None
        return creative_director.sfx_render_list(self.db, self.decisions.sfx) or None

    def _cues(self) -> list:
        return (
            self.db.query(SubtitleCue)
            .filter(SubtitleCue.project_id == self.project.id)
            .order_by(SubtitleCue.order_index)
            .all()
        )

    def _render_once(self, *, phase_id: str, message: str) -> str:
        """One full render pass. Returns the job's output path.

        Shared by the first render and every refinement re-render, so a
        re-rendered video goes through exactly the same encode, subtitle
        burn and SFX overlay as the original - a refinement that rendered
        differently would make its own score incomparable.
        """
        burn = self.settings.subtitle.enabled
        job = Job(project_id=self.project.id, type="render", status="pending")
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        self.run.render_job_id = job.id
        self.db.commit()

        self.event(
            phase_id,
            level="tech",
            status="info",
            message=(
                f"render job {job.id} / burn_subtitles={burn} / crf={self._crf()} / {message}"
            ),
        )
        render_service.run_render(
            self.project.id,
            job.id,
            burn,
            self._crf(),
            subtitle_override=self._subtitle_settings(),
            sfx=self._sfx_render_list(),
        )
        self.db.expire_all()
        finished = self.db.get(Job, job.id)
        if finished is None or finished.status != "completed":
            detail = (finished.error if finished else None) or "書き出しに失敗しました"
            raise PipelineError(detail)
        self.run.output_path = finished.output_path
        self.db.commit()
        return finished.output_path or ""

    def _output_file(self):
        from app.core.paths import project_dir

        if not self.run.output_path:
            return None
        return project_dir(self.project.id) / self.run.output_path

    def _run_review(self, iteration: int) -> VideoReview:
        path = self._output_file()
        if path is None:
            return VideoReview(
                performed=False,
                iteration=iteration,
                error="書き出し結果のパスが記録されていません",
                summary="完成動画を解析できませんでした。",
            )
        decision = self.decisions.subtitle if self.decisions else None
        return reviewer.review(
            path,
            self.scenes,
            self._cues(),
            strategy=self.strategy,
            trend=self.trend,
            max_chars_per_line=(
                decision.max_chars_per_line
                if decision and decision.max_chars_per_line
                else self._caption_budget()
            ),
            has_bgm=self.bgm_asset is not None,
            has_narration=any(s.narration_duration for s in self.scenes),
            iteration=iteration,
        )

    def phase_review(self) -> None:
        """Score the file that actually came out of FFmpeg."""
        self._ensure_scenes()
        self.event(
            "review",
            task="完成した動画を解析しています",
            message="尺・輝度・音量・字幕・構成を実測して採点します",
            reason="計画ではなく、実際に書き出されたMP4を評価するため",
            next_task="自動改善ループ",
        )
        review = self._run_review(iteration=0)
        self.review = review
        self.run.review_json = reviewer.to_json(review)
        self.run.best_score = review.overall_score
        self.db.commit()

        if not review.performed:
            self.event(
                "review",
                status="info",
                message="完成動画を解析できませんでした。",
                reason=review.error,
            )
            self._finish_phase("review", "レビューを実行できませんでした")
            return

        for axis in review.axes:
            basis = {"measured": "実測", "planned": "構成から", "ai": "AI判断"}.get(
                axis.basis, axis.basis
            )
            self.event(
                "review",
                status="info",
                message=f"{axis.label}: {axis.score:.0f}点",
                reason=f"{basis} / {axis.detail}",
            )
        for finding in review.findings[:6]:
            self.event(
                "review",
                status="info",
                scene_id=(
                    self.scenes[finding.scene_index].id
                    if finding.scene_index is not None
                    and 0 <= finding.scene_index < len(self.scenes)
                    else None
                ),
                message=finding.problem,
                reason=f"原因: {finding.cause} / 改善案: {finding.suggestion}",
            )
        self.iterations = [
            IterationRecord(
                iteration=0,
                score=review.overall_score,
                output_path=self.run.output_path or "",
                adopted=True,
                note="初回書き出し",
            )
        ]
        self._finish_phase(
            "review",
            f"総合{review.overall_score:.0f}点 / 指摘{len(review.findings)}件（{review.reviewed_by}）",
        )

    def phase_refine(self) -> None:
        """Review -> improve -> re-render, bounded, adopting the best version."""
        self._ensure_scenes()
        settings = self.settings.refinement
        review = self.review
        if review is None or not review.performed:
            self._skip_phase("refine", "レビュー結果がないため自動改善をスキップしました")
            return
        if not self.iterations:
            self.iterations = [
                IterationRecord(
                    iteration=0,
                    score=review.overall_score,
                    output_path=self.run.output_path or "",
                    adopted=True,
                )
            ]

        outputs: dict[int, str] = {0: self.run.output_path or ""}
        while True:
            control.checkpoint(self.run_id)
            proceed, reason = refinement.should_continue(settings, self.iterations, review)
            if not proceed:
                self.event("refine", status="info", message="自動改善を終了します", reason=reason)
                break

            iteration = len(self.iterations)
            self.event(
                "refine",
                task=f"{iteration}回目の自動改善を行っています",
                message=reason,
                within_phase=min(0.9, iteration / max(1, settings.max_iterations)),
                next_task="完成",
            )
            changes, dirty = refinement.apply_findings(
                self.db,
                self.scenes,
                review.findings,
                project_id=self.project.id,
                max_chars_per_line=self._caption_budget(),
                target_seconds=self._target_seconds(),
                scene_seconds_max=self.strategy.scene_seconds_max,
            )
            if not changes:
                self.event(
                    "refine",
                    status="info",
                    message="適用できる修正がありませんでした",
                    reason="指摘は残っていますが、自動で直せるものはありません。",
                )
                break

            for change in changes:
                self.event("refine", status="info", message=change)

            if dirty:
                planning_service.recompute_start_times(self.scenes)
                self.db.commit()
                for i in sorted(dirty):
                    control.checkpoint(self.run_id)
                    self.event(
                        "refine",
                        task=f"Scene {i + 1}を作り直しています",
                        scene_id=self.scenes[i].id,
                        message=f"変更後の{self.scenes[i].estimated_duration:.1f}秒で再生成します",
                    )
                    self._build_clip(self.scenes[i], i)

            cues = assembly_service.compose_cues(
                self.db, self.project.id, self.scenes, self._caption_budget()
            )
            assembly_service.write_srt(self.project.id, cues)
            if dirty:
                assembly_service.assemble(self.db, self.project, self.scenes, self.bgm_asset)
                self._sync_plan_times()

            self._render_once(phase_id="refine", message=f"refine iteration {iteration}")
            review = self._run_review(iteration=iteration)
            self.review = review
            self.run.review_json = reviewer.to_json(review)
            self.run.iteration = iteration
            self.db.commit()

            outputs[iteration] = self.run.output_path or ""
            previous = self.iterations[-1].score
            self.iterations.append(
                IterationRecord(
                    iteration=iteration,
                    score=review.overall_score,
                    changes=changes,
                    output_path=self.run.output_path or "",
                )
            )
            self.event(
                "refine",
                status="info",
                message=f"{iteration}回目のスコア: {review.overall_score:.0f}点",
                reason=f"前回比 {review.overall_score - previous:+.1f}点",
            )

        best = refinement.best_iteration(self.iterations)
        if best is not None:
            for record in self.iterations:
                record.adopted = record.iteration == best.iteration
            self.run.best_score = best.score
            # The best render is adopted by pointing the run at its file.
            # Every iteration's MP4 stays on disk under its own job id, so a
            # version that was not adopted is still there if the user wants
            # it.
            if outputs.get(best.iteration):
                self.run.output_path = outputs[best.iteration]
            self.db.commit()
            if best.iteration != self.iterations[-1].iteration:
                self.event(
                    "refine",
                    status="info",
                    message=f"{best.iteration}回目({best.score:.0f}点)を最終版として採用しました",
                    reason="最後の版より高いスコアだったため",
                )

        self._finish_phase(
            "refine",
            f"{len(self.iterations) - 1}回改善 / 最終{(best.score if best else 0):.0f}点",
        )

    def phase_render(self) -> None:
        burn = self.settings.subtitle.enabled
        sfx = self._sfx_render_list()
        self.event(
            "render",
            task="FFmpegでMP4を書き出しています",
            message=(
                "シーンを連結し、BGM・字幕"
                + (f"・効果音{len(sfx)}箇所" if sfx else "")
                + "を合成します"
            ),
            reason="最終的なMP4ファイルを作成するため",
            next_task="完成動画レビュー",
        )
        self._render_once(phase_id="render", message="initial render")
        self._finish_phase("render", "MP4の書き出しが完了しました")

    def phase_done(self) -> None:
        duration = sum(s.estimated_duration for s in self.scenes) if self.scenes else 0.0
        self._write_production_record(duration)
        score = self.review.overall_score if self.review and self.review.performed else None
        self.event(
            "done",
            status="done",
            task="完成",
            message=(
                f"動画が完成しました（約{duration:.0f}秒"
                + (f" / 総合{score:.0f}点" if score is not None else "")
                + "）"
            ),
            within_phase=1.0,
        )
        self.completed.add("done")
        self.run.completed_phases = ",".join(p for p in phases.PHASE_IDS if p in self.completed)
        self.run.status = "completed"
        self.run.progress = 100.0
        self.db.commit()

    def _write_production_record(self, duration: float) -> None:
        """The licence audit trail and the production report.

        Written at the end of the run from the decisions the pipeline
        actually acted on, never re-derived: a report that re-queried the
        library or the trend store could describe a different video than
        the one that was made.
        """
        from app.services.studio import material_usage

        try:
            usage = material_usage.build_report(self.db, self.project.id)
            payload = report_service.build_assets_used(
                self.project.id, self.decisions, material_origins=usage.counts
            )
            assets_path = report_service.write_assets_used(self.project.id, payload)

            transcription = "faster-whisper (ローカル)"
            tts_engine = (
                "Windows SAPI5 (ローカル)"
                if self.has_narration
                else "未使用（この環境では音声合成が使えないか、設定でOFFです）"
            )
            report = report_service.build_report(
                project=self.project,
                run=self.run,
                decisions=self.decisions,
                trend=self.trend,
                review=self.review,
                iterations=self.iterations,
                strategy=self.strategy,
                model_id=self.model_id,
                duration=duration,
                transcription_engine=transcription,
                tts_engine=tts_engine,
                assets_used_path=str(assets_path),
            )
            self.run.report_json = report_service.to_json(report)
            self.db.commit()
            report_service.write_report(self.project.id, report)

            attribution = self.decisions.attribution_lines() if self.decisions else []
            if attribution:
                self.event(
                    "done",
                    status="info",
                    message="クレジット表記が必要な素材があります",
                    reason=" / ".join(attribution[:3]),
                )
            self.event(
                "done",
                level="tech",
                status="info",
                message=f"assets-used.json written to {assets_path}",
            )
        except Exception:  # noqa: BLE001 - the video exists; the record is secondary
            logger.exception("Could not write the production record for run %s", self.run_id)
            self.event(
                "done",
                status="info",
                message="制作レポートの書き出しに失敗しました（動画自体は完成しています）。",
            )

    # ------------------------------------------------------------ support

    def _sync_plan_times(self) -> None:
        """Re-times the stored material plan against the assembled cut.

        The plan is made before narration is synthesised, and measured
        speech lengthens scenes. Leaving the plan on its original numbers
        would make the 素材プラン and the 使用素材 list disagree about when
        the same shot appears, and the one on screen would be the wrong
        one.
        """
        plan = self._material_plan
        if plan is None:
            return
        cursor = 0.0
        for i, scene in enumerate(self.scenes):
            duration = float(scene.estimated_duration or 0.0)
            for assignment in plan.assignments:
                if assignment.scene_index == i:
                    assignment.start_time = round(cursor, 2)
                    assignment.duration = round(duration, 2)
            cursor += duration
        self.run.material_plan_json = material_plan.to_json(plan)
        self.db.commit()

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
        ("material_analysis", "phase_material_analysis"),
        ("research", "phase_research"),
        ("trends", "phase_trends"),
        ("strategy", "phase_strategy"),
        ("planning", "phase_planning"),
        ("script", "phase_script"),
        ("scenes", "phase_scenes"),
        ("material_match", "phase_material_match"),
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
        ("review", "phase_review"),
        ("refine", "phase_refine"),
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
