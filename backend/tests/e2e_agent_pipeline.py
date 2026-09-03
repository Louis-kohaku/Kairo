"""End-to-end exercise of the 動画制作エージェント additions, on real media.

Not a unit test and deliberately not mocked. It builds a real project from
real JPEG/MP4 files, runs the new stages against them - creative direction,
beat sync, SFX placement, the render with the agent's own font, the AI Video
Reviewer over the resulting MP4, one refinement pass, and the production
report - and then asserts on the artefacts that actually landed on disk.

The planning stages (strategy/script/scene design) are the one thing it does
not run: they need LM Studio and take minutes per call on a CPU-only
machine, and they are unchanged by this work. Scenes are written directly
instead, which is exactly what those stages would have produced.

Run it with:
    backend/.venv/Scripts/python.exe backend/tests/e2e_agent_pipeline.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from fastapi import UploadFile  # noqa: E402

from app.core.db import SessionLocal, init_db  # noqa: E402
from app.core.paths import project_dir  # noqa: E402
from app.models.production import Chapter, Scene  # noqa: E402
from app.models.studio import ProductionRun  # noqa: E402
from app.schemas.review import IterationRecord  # noqa: E402
from app.schemas.studio import ProductionStrategy  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.services import (  # noqa: E402
    media_service,
    project_service,
    render_service,
    settings_service,
)
from app.services.studio import (  # noqa: E402
    assembly_service,
    creative_director,
    material_service,
    planning_service,
    refinement,
    report as report_service,
    reviewer,
)
from app.services.trends import genre as genre_module  # noqa: E402
from app.services.trends import service as trend_service  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((PASS if ok else FAIL, name, detail))
    print(f"[{PASS if ok else FAIL}] {name}" + (f" - {detail}" if detail else ""))
    return ok


# A photograph has tens of thousands of distinct colours; the stills Kairo
# generates procedurally have a couple of hundred. Anything below this is
# Kairo's own output, and feeding it back in as "the user's material" would
# make this test validate the system against itself.
MIN_PHOTO_COLOURS = 5_000


def _colour_count(path: Path) -> int:
    """Distinct colours in a downsampled copy. 0 if unreadable."""
    try:
        from PIL import Image

        with Image.open(path) as image:
            return len(set(image.convert("RGB").resize((160, 160)).getdata()))
    except Exception:  # noqa: BLE001 - an unreadable file is simply not a candidate
        return 0


def find_source_media() -> tuple[list[Path], list[Path]]:
    """Genuinely photographic files from this install's data directory.

    Ranked most-photographic first so the test uses real pictures even as
    the data directory fills up with Kairo's own renders.
    """
    root = BACKEND.parent / "data" / "projects"
    scored: list[tuple[int, Path]] = []
    for candidate in root.rglob("*.jpg"):
        # Kairo's own scene stills and thumbnails are not user material.
        if candidate.name.startswith(("scene_", "clip_")) or "thumbnails" in candidate.parts:
            continue
        colours = _colour_count(candidate)
        if colours >= MIN_PHOTO_COLOURS:
            scored.append((colours, candidate))
    scored.sort(key=lambda item: item[0], reverse=True)

    # Deduplicate by size: the same Openverse image is downloaded into
    # several projects, and six copies of one photo is not six photos.
    images: list[Path] = []
    seen_sizes: set[int] = set()
    for _colours, candidate in scored:
        size = candidate.stat().st_size
        if size in seen_sizes:
            continue
        seen_sizes.add(size)
        images.append(candidate)
        if len(images) >= 6:
            break

    videos = [
        p
        for p in sorted(root.rglob("*.mp4"))
        if not p.name.startswith("scene_") and "renders" not in p.parts
    ][:2]
    return images, videos


SCRIPT = [
    ("沖縄に着いた瞬間の空気", "沖縄、着いた。", "hook", 2.4),
    ("海の色が本土と違う", "この海の色。", "wonder", 3.0),
    ("街を歩く", "歩くだけで楽しい。", "calm", 3.2),
    ("food のカット", "食べたら忘れられない。", "joy", 3.0),
    ("夕暮れ", "そして日が暮れる。", "calm", 3.4),
    ("締め", "また来る。", "warm", 2.6),
]


def main() -> int:
    init_db()
    db = SessionLocal()
    started = time.time()

    images, videos = find_source_media()
    colours = [_colour_count(p) for p in images]
    if not check(
        "実写素材が見つかる（Kairo生成画像ではない）",
        len(images) >= 3 and min(colours or [0]) >= MIN_PHOTO_COLOURS,
        f"画像{len(images)}枚 / 動画{len(videos)}本 / 色数 {colours}",
    ):
        print("  実写と判定できる画像が足りません。data/projects に写真を取り込んでください。")
        return 1

    # ---------------------------------------------------------- project
    project = project_service.create_project(
        db, f"E2E 動画制作エージェント {int(time.time())}", 30.0, 1080, 1920
    )
    print(f"\n== project {project.id} ==")

    imported = []
    for src in images + videos:
        try:
            # import_media takes a Starlette UploadFile, which is what the
            # HTTP route hands it; constructing one here means this test
            # goes through the identical import path a real upload does,
            # including the probe and the decompression-bomb guard.
            with src.open("rb") as handle:
                upload = UploadFile(filename=src.name, file=handle)
                asset = media_service.import_media(db, project.id, upload)
            imported.append(asset)
        except Exception as exc:  # noqa: BLE001
            print(f"  skip {src.name}: {exc}")
    check("実素材を取り込める", len(imported) >= 4, f"{len(imported)}件")

    # ---------------------------------------------------------- trends
    instruction = "沖縄旅行のショート動画を作って"
    trend = trend_service.build_context(db, instruction)
    check(
        "トレンド文脈を構築できる",
        trend.genre == "travel",
        f"genre={trend.genre} used={trend.used} profile={trend.profile_source} "
        f"signals={len(trend.signals)}",
    )
    profile = trend.profile or genre_module.default_profile("travel")

    strategy = ProductionStrategy(
        title="沖縄3日間",
        concept="沖縄の色と空気を短く見せる",
        hook="海の色を最初に出す",
        ending="また来る、で締める",
        differentiation="観光名所の羅列にしない",
        scene_seconds_min=2.0,
        scene_seconds_max=3.6,
        bgm_mood=profile.bgm_mood or "bright",
        subtitle_policy="1行10文字前後",
        audio_policy="BGMは控えめ",
    )

    # ---------------------------------------------------------- scenes
    chapter = Chapter(project_id=project.id, order_index=0, title="本編", summary="")
    db.add(chapter)
    db.flush()
    scenes: list[Scene] = []
    for i, (visual, caption, emotion, seconds) in enumerate(SCRIPT):
        scene = Scene(
            chapter_id=chapter.id,
            project_id=project.id,
            order_index=i,
            narration=caption,
            subtitle_text=caption,
            visual_prompt=visual,
            emotion=emotion,
            estimated_duration=seconds,
            is_hook=(i == 0),
            purpose="掴み" if i == 0 else ("締め・余韻" if i == len(SCRIPT) - 1 else "展開"),
            status="pending",
        )
        db.add(scene)
        scenes.append(scene)
    db.commit()
    # Pin the user's real files to the scenes, which is what the material
    # matching stage would have done - the point of this run is that the
    # finished MP4 contains the user's own photographs, not stand-ins.
    for i, scene in enumerate(scenes):
        if i < len(imported):
            asset = imported[i]
            scene.asset_source = "user"
            scene.user_asset_id = asset.id
            scene.material_origin = "user"
            scene.material_note = "E2E検証: ユーザー素材を直接割り当て"
    db.commit()
    planning_service.recompute_start_times(scenes)
    db.commit()
    check("シーンを作成できる", len(scenes) == len(SCRIPT), f"{len(scenes)}シーン")

    # --------------------------------------------- creative direction
    settings = settings_service.get_settings()
    total = sum(s.estimated_duration for s in scenes)
    decisions = creative_director.build(
        db,
        genre=trend.genre,
        genre_label=trend.genre_label,
        profile=profile,
        scenes=scenes,
        duration=total,
        mood=strategy.bgm_mood,
        tempo=profile.cut_tempo or "medium",
        subtitle_base=settings.subtitle,
        width=project.width,
        height=project.height,
        require_commercial=settings.library.prefer_commercial_safe,
        target_scene_seconds=strategy.scene_seconds_max * 0.8,
    )
    check(
        "フォントを選定できる",
        bool(decisions.font and decisions.font.found),
        f"{decisions.font.family if decisions.font else '-'} / "
        f"{decisions.font.license.status_label if decisions.font else '-'} / "
        f"理由: {decisions.font.reason if decisions.font else '-'}",
    )
    check(
        "BGMを選定できる",
        bool(decisions.music and decisions.music.found),
        f"{decisions.music.name if decisions.music else '-'} "
        f"{decisions.music.bpm if decisions.music else '-'}BPM / "
        f"{decisions.music.license.status_label if decisions.music else '-'}",
    )
    check(
        "選定素材がライセンス条件を満たす",
        all(
            c.license.status in ("usable", "attribution_required", "conditional")
            for c in [decisions.font, decisions.music]
            if c and c.found
        ),
        ", ".join(
            f"{c.kind}={c.license.status}" for c in [decisions.font, decisions.music] if c and c.found
        ),
    )
    check(
        "効果音を配置できる",
        len(decisions.sfx) >= 2,
        f"{len(decisions.sfx)}箇所: "
        + ", ".join(f"{p.category}@{p.at:.1f}s" for p in decisions.sfx[:4]),
    )

    beat = decisions.beat_sync
    before = [s.estimated_duration for s in scenes]
    if beat.applied:
        creative_director.apply_beat_sync(scenes, beat)
        planning_service.recompute_start_times(scenes)
        db.commit()
    after = [s.estimated_duration for s in scenes]
    check(
        "ビート同期を計算・適用できる",
        beat.bpm is not None,
        f"bpm={beat.bpm} {beat.beats_per_cut}拍刻み applied={beat.applied} "
        f"{[round(b, 2) for b in before]} -> {[round(a, 2) for a in after]}",
    )
    if beat.applied and beat.beat_seconds:
        grid = beat.beat_seconds * beat.beats_per_cut
        residuals = [abs(d / grid - round(d / grid)) * grid for d in after]
        check(
            "各カットがビートグリッド上にある",
            max(residuals) < 0.05,
            f"最大ずれ {max(residuals) * 1000:.0f}ms (grid={grid:.3f}s)",
        )

    # ------------------------------------------------------- BGM import
    bgm = creative_director.import_library_audio(
        db, project.id, decisions.music, origin="kairo_bgm", label="BGM"
    )
    check("BGMをプロジェクトに取り込める", bgm is not None, bgm.original_filename if bgm else "-")

    # ------------------------------------------------------ build clips
    print("\n== building clips ==")
    for i, scene in enumerate(scenes):
        material_service.rebuild_scene(
            db,
            project,
            scene,
            i,
            strategy,
            engine_id="procedural",
            crf=23,
            use_narration=False,
            is_last=(i == len(scenes) - 1),
        )
    db.commit()
    built = sum(1 for s in scenes if s.media_asset_id)
    check("各シーンの映像クリップを生成できる", built == len(scenes), f"{built}/{len(scenes)}")

    budget = decisions.subtitle.max_chars_per_line if decisions.subtitle else 14
    cues = assembly_service.compose_cues(db, project.id, scenes, budget)
    assembly_service.write_srt(project.id, cues)
    assembled = assembly_service.assemble(db, project, scenes, bgm)
    check("タイムラインを組める", assembled > 0, f"{assembled:.1f}秒 / 字幕{len(cues)}件")

    # ----------------------------------------------------------- render
    run = ProductionRun(
        project_id=project.id,
        mode="full_auto",
        status="running",
        instruction=instruction,
        target_duration_seconds=total,
        orientation="vertical",
    )
    run.strategy_json = json.dumps(strategy.model_dump(), ensure_ascii=False)
    run.trend_json = json.dumps(trend.model_dump(), ensure_ascii=False)
    run.assets_json = json.dumps(decisions.model_dump(), ensure_ascii=False)
    db.add(run)
    db.commit()

    subtitle_override, _ = creative_director.subtitle_settings_for(
        settings.subtitle, decisions.font, profile, width=project.width, height=project.height
    )
    sfx_list = creative_director.sfx_render_list(db, decisions.sfx)
    check("効果音ファイルが実在する", len(sfx_list) == len(decisions.sfx),
          f"{len(sfx_list)}/{len(decisions.sfx)}")

    print("\n== rendering (FFmpeg) ==")
    job = Job(project_id=project.id, type="render", status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)
    render_started = time.time()
    render_service.run_render(
        project.id, job.id, True, 23, subtitle_override=subtitle_override, sfx=sfx_list
    )
    db.expire_all()
    job = db.get(Job, job.id)
    ok = job.status == "completed"
    check(
        "実MP4を書き出せる",
        ok,
        f"{job.output_path} ({time.time() - render_started:.0f}s)" if ok else str(job.error),
    )
    if not ok:
        db.close()
        return 1

    run.output_path = job.output_path
    run.render_job_id = job.id
    db.commit()
    output = project_dir(project.id) / job.output_path
    check("MP4が実在し中身がある", output.exists() and output.stat().st_size > 100_000,
          f"{output.stat().st_size / 1e6:.1f}MB")

    # ----------------------------------------------------------- review
    print("\n== reviewing rendered MP4 ==")
    review = reviewer.review(
        output,
        scenes,
        cues,
        strategy=strategy,
        trend=trend,
        max_chars_per_line=budget,
        has_bgm=bgm is not None,
        has_narration=False,
        iteration=0,
        use_ai=False,
    )
    check("完成動画をレビューできる", review.performed, review.summary)
    check("7軸すべてを採点する", len(review.axes) == 7,
          " / ".join(f"{a.label}:{a.score:.0f}({a.basis})" for a in review.axes))
    measured = review.measured
    check(
        "実測値が本物のファイルから取れている",
        bool(measured.get("duration")) and bool(measured.get("frames", {}).get("available")),
        f"尺{measured.get('duration')}秒 {measured.get('width')}x{measured.get('height')} "
        f"音声={measured.get('has_audio')} {measured.get('loudness_lufs')}LUFS "
        f"輝度{measured.get('frames', {}).get('mean_luma')}",
    )
    check("音声トラックが存在する（BGM+効果音が乗っている）", bool(measured.get("has_audio")),
          f"codec={measured.get('audio_codec')}")

    # ------------------------------------------------------- refinement
    print("\n== refinement ==")
    history = [
        IterationRecord(
            iteration=0, score=review.overall_score, output_path=job.output_path or "", adopted=True
        )
    ]
    proceed, reason = refinement.should_continue(settings.refinement, history, review)
    check("反復継続の判断ができる", isinstance(proceed, bool), f"continue={proceed} 理由={reason}")

    # Force one complete iteration regardless of whether the run's own
    # settings would have taken it. The loop - apply, re-encode, re-render,
    # re-review - is the thing being verified, and a test that only runs it
    # when the first render happens to score badly verifies nothing.
    forced = settings.refinement.model_copy(update={"target_score": 100.0, "max_iterations": 3})
    proceed2, reason2 = refinement.should_continue(forced, history, review)
    check("目標未達なら反復を継続すると判断する", proceed2, reason2)

    changes, dirty = refinement.apply_findings(
        db,
        scenes,
        review.findings,
        project_id=project.id,
        max_chars_per_line=budget,
        target_seconds=total,
        scene_seconds_max=strategy.scene_seconds_max,
    )
    check("レビュー指摘を実際に適用できる", bool(changes), f"{len(changes)}件: {changes[:3]}")

    if changes:
        print("\n== re-render after refinement ==")
        if dirty:
            planning_service.recompute_start_times(scenes)
            db.commit()
            for i in sorted(dirty):
                material_service.rebuild_scene(
                    db, project, scenes[i], i, strategy,
                    engine_id="procedural", crf=23, use_narration=False,
                    is_last=(i == len(scenes) - 1),
                )
            db.commit()
        cues = assembly_service.compose_cues(db, project.id, scenes, budget)
        assembly_service.write_srt(project.id, cues)
        if dirty:
            assembly_service.assemble(db, project, scenes, bgm)

        job2 = Job(project_id=project.id, type="render", status="pending")
        db.add(job2)
        db.commit()
        db.refresh(job2)
        render_service.run_render(
            project.id, job2.id, True, 23,
            subtitle_override=subtitle_override,
            sfx=creative_director.sfx_render_list(db, decisions.sfx),
        )
        db.expire_all()
        job2 = db.get(Job, job2.id)
        check("改善後に再レンダリングできる", job2.status == "completed",
              str(job2.output_path or job2.error))

        if job2.status == "completed":
            output2 = project_dir(project.id) / job2.output_path
            review2 = reviewer.review(
                output2, scenes, cues, strategy=strategy, trend=trend,
                max_chars_per_line=budget, has_bgm=bgm is not None,
                has_narration=False, iteration=1, use_ai=False,
            )
            check("改善版を再レビューできる", review2.performed,
                  f"{review.overall_score:.1f} -> {review2.overall_score:.1f}")
            before_lufs = review.measured.get("loudness_lufs")
            after_lufs = review2.measured.get("loudness_lufs")
            raised = any("BGM音量" in c for c in changes)
            check(
                "音量の指摘が実際の出力を変える（改善が書き出しに届く）",
                (not raised)
                or (
                    before_lufs is not None
                    and after_lufs is not None
                    and after_lufs > before_lufs + 1.0
                ),
                f"{before_lufs} LUFS -> {after_lufs} LUFS (BGM音量変更={raised})",
            )
            history.append(
                IterationRecord(
                    iteration=1, score=review2.overall_score, changes=changes,
                    output_path=job2.output_path or "",
                )
            )
            best = refinement.best_iteration(history)
            check(
                "最良版を採用できる",
                best is not None
                and best.score == max(r.score for r in history),
                f"採用 iteration={best.iteration} ({best.score:.1f}点) / "
                f"候補 {[f'{r.iteration}:{r.score:.1f}' for r in history]}",
            )
            if best is not None and best.output_path:
                run.output_path = best.output_path
                db.commit()
            review = review2 if best and best.iteration == 1 else review

    # Stopping rules must hold whatever the score was.
    capped = refinement.should_continue(
        settings.refinement,
        [history[0]] * (settings.refinement.max_iterations + 1),
        review,
    )
    check("最大反復回数で必ず停止する", capped[0] is False, capped[1])

    # ----------------------------------------------------------- report
    print("\n== report ==")
    from app.services.studio import material_usage

    usage = material_usage.build_report(db, project.id)
    check(
        "完成動画がユーザー素材で構成されている",
        usage.counts.get("user", 0) >= min(len(imported), len(scenes)),
        f"origin別: {usage.counts}",
    )
    payload = report_service.build_assets_used(
        project.id, decisions, material_origins=usage.counts
    )
    assets_path = report_service.write_assets_used(project.id, payload)
    check(
        "assets-used.json を出力できる",
        assets_path.exists() and len(payload["assets"]) >= 2,
        f"{len(payload['assets'])}件の素材を記録: "
        + ", ".join(f"{a['kind']}:{a['license']['id']}" for a in payload["assets"][:4]),
    )

    report = report_service.build_report(
        project=project,
        run=run,
        decisions=decisions,
        trend=trend,
        review=review,
        iterations=history,
        strategy=strategy,
        model_id="(この検証ではLLMを使用していません)",
        duration=assembled,
        transcription_engine="faster-whisper (ローカル)",
        tts_engine="未使用",
        assets_used_path=str(assets_path),
    )
    report_path = report_service.write_report(project.id, report)
    check(
        "制作レポートを出力できる",
        report_path.exists() and report.final_score > 0,
        f"score={report.final_score:.0f} font={report.font} music={report.music} "
        f"genre={report.genre_label}",
    )

    print("\n" + "=" * 72)
    print(f"完成MP4: {output}")
    print(f"レポート: {report_path}")
    print(f"素材台帳: {assets_path}")
    print(f"総合スコア: {review.overall_score:.1f}")
    for axis in review.axes:
        print(f"  {axis.label:12s} {axis.score:5.1f} [{axis.basis}] {axis.detail}")
    print(f"\n指摘 {len(review.findings)}件")
    for finding in review.findings[:6]:
        print(f"  - [{finding.axis}/{finding.severity}] {finding.problem}")
        print(f"      原因: {finding.cause}")
        print(f"      改善: {finding.suggestion} (fix={finding.fix})")

    failed = [r for r in results if r[0] == FAIL]
    print("\n" + "=" * 72)
    print(f"{len(results) - len(failed)}/{len(results)} passed in {time.time() - started:.0f}s")
    for _status, name, detail in failed:
        print(f"  FAILED: {name} - {detail}")

    db.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
