"""A/B/C variants: several takes on the same material, scored against each other.

Deliberately *not* part of the default Full Auto flow. Each variant is a full
re-encode and a full review, so producing three of them costs three times the
render - a price worth paying when someone asks for it, and not worth
imposing on every run.

A variant varies how the same plan is *executed*, not what it says. The
scenes, script and captions are the ones the planner already wrote; what
changes is cut length, music, and caption emphasis. That is what makes the
comparison meaningful: three videos of the same idea, rather than three
different ideas that cannot be ranked against each other.

Every variant is rendered to its own file and every file is kept, so "B was
best" is a claim the user can check by watching A and C.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from app.core.paths import project_dir
from app.models.job import Job
from app.models.studio import ProductionRun
from app.schemas.review import VariantRecord
from app.services import render_service, settings_service
from app.services.studio import (
    assembly_service,
    creative_director,
    material_service,
    planning_service,
    reviewer,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VariantSpec:
    id: str
    label: str
    note: str
    # Multiplier on every scene's planned duration. <1 is a faster cut.
    tempo_scale: float = 1.0
    # Overrides the strategy's BGM mood when set.
    mood: str | None = None
    # Overrides the tempo band used when choosing music.
    music_tempo: str = "medium"
    # Multiplier on the caption character budget. <1 forces shorter captions.
    caption_scale: float = 1.0


SPECS: tuple[VariantSpec, ...] = (
    VariantSpec(
        "A",
        "Emotional",
        "カットを長めにとり、落ち着いたBGMで余韻を残す構成",
        tempo_scale=1.18,
        mood="emotional",
        music_tempo="slow",
        caption_scale=1.0,
    ),
    VariantSpec(
        "B",
        "Fast Pace",
        "カットを詰めてテンポを上げ、字幕も短く切る構成",
        tempo_scale=0.78,
        mood="energetic",
        music_tempo="fast",
        caption_scale=0.75,
    ),
    VariantSpec(
        "C",
        "Trend-oriented",
        "ジャンルのトレンド傾向（尺・カット長・BGM）に寄せた構成",
        tempo_scale=1.0,
        mood=None,
        music_tempo="medium",
        caption_scale=1.0,
    ),
)

SPEC_BY_ID = {s.id: s for s in SPECS}


@dataclass
class VariantOutcome:
    records: list[VariantRecord] = field(default_factory=list)
    best_id: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "variants": [r.model_dump() for r in self.records],
            "best_id": self.best_id,
            "error": self.error,
        }


class VariantError(RuntimeError):
    pass


def _apply_spec(scenes: list, spec: VariantSpec, baseline: list[float], profile) -> None:
    """Re-times the scenes for this variant, from the baseline durations.

    Always applied to the *baseline*, never to the previous variant's
    result - otherwise B would be a variation of A rather than of the plan,
    and the three would not be comparable.
    """
    scale = spec.tempo_scale
    if spec.id == "C" and profile is not None and profile.scene_seconds:
        # The trend-oriented variant takes its cut length from the genre
        # profile rather than from a fixed multiplier.
        mean = sum(baseline) / max(1, len(baseline))
        if mean > 0:
            scale = float(profile.scene_seconds) / mean
    scale = max(0.5, min(scale, 2.0))
    for scene, base in zip(scenes, baseline):
        scene.estimated_duration = round(max(0.8, base * scale), 2)


def produce(
    db,
    project,
    run: ProductionRun,
    *,
    strategy,
    trend,
    variant_ids: list[str] | None = None,
    on_progress=None,
) -> VariantOutcome:
    """Renders and scores each requested variant. Returns them ranked."""
    scenes = planning_service.ordered_scenes(db, project.id)
    if not scenes:
        raise VariantError("バリエーションを作るためのシーンがありません。先に制作を実行してください。")

    settings = settings_service.get_settings()
    profile = trend.profile if trend is not None and trend.used else None
    specs = [SPEC_BY_ID[v] for v in (variant_ids or ["A", "B", "C"]) if v in SPEC_BY_ID]
    if not specs:
        raise VariantError("有効なバリエーションIDが指定されていません。")

    baseline = [float(s.estimated_duration or 0.0) for s in scenes]
    original_output = run.output_path
    outcome = VariantOutcome()
    # Per-variant BGM and caption budget. Kept because the winner is not
    # necessarily the variant that ran last, and rebuilding the adopted cut
    # with the last variant's music would be silently wrong.
    chosen_bgm: dict[str, object] = {}
    chosen_budget: dict[str, int] = {}

    def report(message: str) -> None:
        if on_progress:
            on_progress(message)

    for spec in specs:
        report(f"バリエーション {spec.id} ({spec.label}) を作成しています")
        _apply_spec(scenes, spec, baseline, profile)
        planning_service.recompute_start_times(scenes)
        db.commit()

        total = sum(float(s.estimated_duration or 0.0) for s in scenes)
        decisions = creative_director.build(
            db,
            genre=trend.genre if trend else "unknown",
            genre_label=trend.genre_label if trend else "",
            profile=profile,
            scenes=scenes,
            duration=total,
            mood=spec.mood or strategy.bgm_mood or "gentle",
            tempo=spec.music_tempo,
            subtitle_base=settings.subtitle,
            width=project.width,
            height=project.height,
            require_commercial=settings.library.prefer_commercial_safe,
            target_scene_seconds=max(1.0, total / max(1, len(scenes))),
        )

        bgm = creative_director.import_library_audio(
            db, project.id, decisions.music, origin="kairo_bgm", label=f"BGM_{spec.id}"
        )
        if bgm is None:
            bgm = assembly_service.build_bgm(
                db, project, total, spec.mood or strategy.bgm_mood or "gentle"
            )

        for i, scene in enumerate(scenes):
            material_service.rebuild_scene(
                db,
                project,
                scene,
                i,
                strategy,
                engine_id=settings.generation.default_engine_id or "procedural",
                crf=23,
                use_narration=False,
                is_last=(i == len(scenes) - 1),
            )
        db.commit()

        budget = max(
            6,
            int(
                (decisions.subtitle.max_chars_per_line if decisions.subtitle else 14)
                * spec.caption_scale
            ),
        )
        chosen_bgm[spec.id] = bgm
        chosen_budget[spec.id] = budget
        cues = assembly_service.compose_cues(db, project.id, scenes, budget)
        assembly_service.write_srt(project.id, cues)
        assembly_service.assemble(db, project, scenes, bgm)

        subtitle_override, _ = creative_director.subtitle_settings_for(
            settings.subtitle, decisions.font, profile, width=project.width, height=project.height
        )
        job = Job(project_id=project.id, type="render", status="pending")
        db.add(job)
        db.commit()
        db.refresh(job)
        render_service.run_render(
            project.id,
            job.id,
            settings.subtitle.enabled,
            23,
            subtitle_override=subtitle_override,
            sfx=creative_director.sfx_render_list(db, decisions.sfx) or None,
        )
        db.expire_all()
        job = db.get(Job, job.id)
        if job is None or job.status != "completed":
            message = (job.error if job else None) or "書き出しに失敗しました"
            logger.info("Variant %s failed to render: %s", spec.id, message)
            outcome.records.append(
                VariantRecord(
                    id=spec.id,
                    label=spec.label,
                    strategy_note=f"{spec.note}（書き出し失敗: {message}）",
                    score=0.0,
                )
            )
            continue

        review = reviewer.review(
            project_dir(project.id) / (job.output_path or ""),
            scenes,
            cues,
            strategy=strategy,
            trend=trend,
            max_chars_per_line=budget,
            has_bgm=bgm is not None,
            has_narration=False,
            use_ai=False,
        )
        outcome.records.append(
            VariantRecord(
                id=spec.id,
                label=spec.label,
                strategy_note=(
                    f"{spec.note} / 尺{total:.0f}秒 / 1カット{total / max(1, len(scenes)):.1f}秒"
                    + (
                        f" / BGM {decisions.music.name}"
                        if decisions.music and decisions.music.found
                        else ""
                    )
                ),
                score=review.overall_score,
                output_path=job.output_path or "",
            )
        )
        report(f"バリエーション {spec.id}: {review.overall_score:.0f}点")

    scored = [r for r in outcome.records if r.output_path]
    if not scored:
        outcome.error = "書き出せたバリエーションがありませんでした。"
        run.output_path = original_output
        # Nothing was adopted, so put the plan back exactly as it was.
        for scene, base in zip(scenes, baseline):
            scene.estimated_duration = base
        planning_service.recompute_start_times(scenes)
        db.commit()
        return outcome

    best = max(scored, key=lambda r: r.score)
    best.best = True
    outcome.best_id = best.id
    run.output_path = best.output_path
    db.commit()

    # Leave the project *as the winning variant*, not as the baseline and not
    # as whichever variant happened to run last. Both of those would leave the
    # editor showing a cut that is not the MP4 the user was just told to
    # watch: the scene rows would say one set of durations while the encoded
    # clips on disk held another.
    winner = SPEC_BY_ID[best.id]
    report(f"バリエーション {best.id} を最終版としてプロジェクトに反映しています")
    _apply_spec(scenes, winner, baseline, profile)
    planning_service.recompute_start_times(scenes)
    db.commit()

    if best.id != specs[-1].id:
        # The last variant rendered was not the winner, so the clips on disk
        # belong to the wrong cut and have to be rebuilt.
        for i, scene in enumerate(scenes):
            material_service.rebuild_scene(
                db,
                project,
                scene,
                i,
                strategy,
                engine_id=settings.generation.default_engine_id or "procedural",
                crf=23,
                use_narration=False,
                is_last=(i == len(scenes) - 1),
            )
        db.commit()
        cues = assembly_service.compose_cues(
            db, project.id, scenes, chosen_budget.get(best.id, 14)
        )
        assembly_service.write_srt(project.id, cues)
        assembly_service.assemble(db, project, scenes, chosen_bgm.get(best.id))

    return outcome


def to_json(outcome: VariantOutcome) -> str:
    return json.dumps(outcome.to_dict(), ensure_ascii=False)


def spec_list() -> list[dict]:
    return [
        {"id": s.id, "label": s.label, "note": s.note, "tempo_scale": s.tempo_scale}
        for s in SPECS
    ]
