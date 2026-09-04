"""Deterministic checks over the編集ディレクター and the craft stages.

Same contract as `test_agent_units.py`: no network, no LM Studio, no
FFmpeg. What is checked here is the decision logic added for the
autonomous-editing work - the edit directive, the font ranking, the
transition planner and its render-side budget, the caption design, the
subject-aware photo move, and the frame-quality measures.

These exist because two of the bugs found while building this were not
type errors and not caught by importing the modules: a `FontRanking` that
was never imported (so the audio phase died halfway through a run), and a
generator that referenced an unbound name. Both are the kind of thing that
only shows up when the function is actually called with real arguments.

Run with:
    backend/.venv/Scripts/python.exe backend/tests/test_director_units.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.schemas.edit_style import (  # noqa: E402
    EditDirective,
    TransitionChoice,
    TransitionPlan,
)
from app.schemas.material import MaterialAnalysis, UsableRange  # noqa: E402
from app.schemas.settings import SubtitleSettings  # noqa: E402
from app.services import subtitle_style  # noqa: E402
from app.services.library import font_profile  # noqa: E402
from app.services.studio import (  # noqa: E402
    edit_director,
    edit_styles,
    hook_optimizer,
    photo_motion,
    platform_presets,
    scene_budget,
    subtitle_design,
    transition_planner,
)

failures: list[str] = []
passed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed
    if condition:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failures.append(f"{name} - {detail}")
        print(f"[FAIL] {name} - {detail}")


def directive(style: str = "shorts", **overrides) -> EditDirective:
    d = edit_director.decide(
        overrides.pop("instruction", "テスト用の動画"),
        duration_seconds=overrides.pop("duration_seconds", 45.0),
        orientation=overrides.pop("orientation", "vertical"),
        width=overrides.pop("width", 1080),
        height=overrides.pop("height", 1920),
        style_override=style,
        platform=overrides.pop("platform", "youtube_shorts"),
        use_ai=False,
    )
    for key, value in overrides.items():
        setattr(d, key, value)
    return d


def scene(**kwargs) -> SimpleNamespace:
    base = dict(
        purpose="",
        emotion="",
        camera="",
        subtitle_text="",
        narration="",
        visual_prompt="",
        transition="cut",
        continuity="",
        estimated_duration=3.0,
        order_index=0,
        is_hook=False,
        user_asset_id=None,
        chapter_id="c1",
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


# ------------------------------------------------------- edit directive


def test_directive() -> None:
    every = set()
    for style in edit_styles.STYLE_BY_ID:
        d = directive(style)
        every.add((d.style, d.color.id, d.subtitle.density, d.audio.bgm_mood))
        check(
            f"{style}: 方針が生成される",
            bool(d.style_label) and d.scene_seconds > 0,
            f"style_label={d.style_label!r} scene_seconds={d.scene_seconds}",
        )
        check(
            f"{style}: カット長が下限と上限の内側",
            d.scene_seconds_min <= d.scene_seconds <= d.scene_seconds_max,
            f"{d.scene_seconds_min} <= {d.scene_seconds} <= {d.scene_seconds_max}",
        )
        check(
            f"{style}: 切り替えは既定でカット",
            d.transitions.default == "cut",
            d.transitions.default,
        )
        check(
            f"{style}: 切り替え比率に上限がある",
            0.0 <= d.transitions.max_ratio <= 0.5,
            str(d.transitions.max_ratio),
        )
        check(
            f"{style}: 構成が2段階以上",
            len(d.story) >= 2,
            str(len(d.story)),
        )

    # The whole point of having ten styles is that they are not the same
    # style ten times.
    check(
        "10スタイルが実際に違う方針になる",
        len(every) >= 7,
        f"{len(every)} distinct (style, color, density, bgm) combinations",
    )

    # Cinematic must be slower than shorts, or "cinematic" is a label with
    # nothing behind it.
    slow = directive("cinematic")
    fast = directive("shorts")
    check(
        "Cinematicのカットはショートより長い",
        slow.scene_seconds > fast.scene_seconds,
        f"{slow.scene_seconds} vs {fast.scene_seconds}",
    )
    check(
        "Luxuryは字幕を絞る",
        directive("luxury").subtitle.coverage < directive("tutorial").subtitle.coverage,
    )


def test_directive_material_adaptation() -> None:
    """The material has to change the plan, not just be reported."""
    few = [
        MaterialAnalysis(asset_id=f"a{i}", kind="image", brightness=0.5)
        for i in range(3)
    ]
    many = [
        MaterialAnalysis(asset_id=f"b{i}", kind="image", brightness=0.5)
        for i in range(30)
    ]
    with_few = edit_director.decide(
        "テスト", duration_seconds=60, orientation="vertical",
        width=1080, height=1920, style_override="shorts",
        analyses=few, use_ai=False,
    )
    with_many = edit_director.decide(
        "テスト", duration_seconds=60, orientation="vertical",
        width=1080, height=1920, style_override="shorts",
        analyses=many, use_ai=False,
    )
    check(
        "素材が少ないとカットを長くする",
        with_few.scene_seconds > with_many.scene_seconds,
        f"few={with_few.scene_seconds} many={with_many.scene_seconds}",
    )
    check(
        "素材が少ないと構成を簡略化する",
        len(with_few.story) <= len(with_many.story),
        f"few={len(with_few.story)} many={len(with_many.story)}",
    )
    check(
        "判断の根拠が記録される",
        any("素材" in n for n in with_few.notes),
        str(with_few.notes),
    )

    # Dark material must not be graded darker.
    dark = [
        MaterialAnalysis(asset_id=f"d{i}", kind="image", brightness=0.15)
        for i in range(8)
    ]
    moody = edit_director.decide(
        "テスト", duration_seconds=45, orientation="vertical",
        width=1080, height=1920, style_override="documentary",
        analyses=dark, use_ai=False,
    )
    check(
        "暗い素材を更に暗くしない",
        moody.color.brightness >= 0.0,
        f"brightness={moody.color.brightness}",
    )


def test_platform() -> None:
    cases = [
        ("TikTokでバズる動画", "vertical", "tiktok"),
        ("YouTube Shortsを作って", "vertical", "youtube_shorts"),
        ("インスタのリール", "vertical", "instagram_reels"),
        ("YouTubeの解説動画", "horizontal", "youtube_landscape"),
        ("動画を作って", "vertical", "youtube_shorts"),
        ("動画を作って", "horizontal", "youtube_landscape"),
    ]
    for text, orientation, expected in cases:
        got = platform_presets.detect(text, orientation)
        check(f"配信先判定: {text} ({orientation})", got == expected, f"got {got}")

    # "YouTubeでショート" must not resolve to the landscape preset.
    check(
        "YouTubeショートは横型と誤判定しない",
        platform_presets.detect("YouTubeのショート動画", "vertical") == "youtube_shorts",
    )

    # A 16:9 delivery needs smaller captions than a 9:16 one.
    wide = directive("tutorial", platform="youtube_landscape")
    tall = directive("tutorial", platform="youtube_shorts")
    check(
        "横型は字幕を小さくする",
        wide.subtitle.size_scale < tall.subtitle.size_scale,
        f"{wide.subtitle.size_scale} vs {tall.subtitle.size_scale}",
    )
    check(
        "Shortsは字幕をUIから逃がす",
        tall.subtitle.position == "middle",
        tall.subtitle.position,
    )


# ------------------------------------------------------ transitions


def test_transition_planner() -> None:
    d = directive("travel")
    scenes = [
        scene(visual_prompt="空港に到着した", purpose="到着", emotion="期待"),
        scene(visual_prompt="空港のロビーを歩く", purpose="移動", emotion="期待"),
        scene(visual_prompt="ホテルの部屋に入る", purpose="到着", emotion="安心"),
        scene(visual_prompt="ホテルの窓から海が見える", purpose="景色", emotion="安心"),
        scene(visual_prompt="翌日 ビーチで泳ぐ", purpose="体験", emotion="高揚"),
        scene(visual_prompt="ビーチで貝殻を拾う", purpose="体験", emotion="高揚"),
        scene(visual_prompt="夕日を眺めて帰る", purpose="締め", emotion="余韻"),
    ]
    plan = transition_planner.plan(scenes, d, act_boundaries={4})
    non_cut = [c for c in plan.choices if c.transition != "cut"]

    check(
        "境界の数はシーン数-1",
        plan.boundary_count == len(scenes) - 1,
        f"{plan.boundary_count}",
    )
    check(
        "切り替えは上限を超えない",
        len(non_cut) <= max(1, int(plan.boundary_count * d.transitions.max_ratio)),
        f"{len(non_cut)} of {plan.boundary_count}, cap={d.transitions.max_ratio}",
    )
    check(
        "切り替えには必ず理由がつく",
        all(c.reason != "none" and c.detail for c in non_cut),
        str([(c.index, c.reason) for c in non_cut]),
    )
    check(
        "スタイルが許可した種類しか使わない",
        all(c.transition in d.transitions.allowed for c in non_cut),
        str([c.transition for c in non_cut]),
    )
    check(
        "幕の変わり目が最優先で残る",
        any(c.index == 4 for c in non_cut) or len(non_cut) == 0,
        str([c.index for c in non_cut]),
    )

    # A style that allows only cuts must produce only cuts.
    only_cut = directive("vlog")
    only_cut.transitions.allowed = ["cut"]
    only_cut.transitions.max_ratio = 0.0
    plan2 = transition_planner.plan(scenes, only_cut)
    check(
        "切り替えを許さない方針では全てカット",
        all(c.transition == "cut" for c in plan2.choices),
    )

    # A two-scene video has one boundary and must not crash.
    plan3 = transition_planner.plan(scenes[:1], d)
    check("シーン1つでは境界なし", plan3.boundary_count == 0 and not plan3.choices)


def test_transition_budget() -> None:
    """The render-side budget: a transition must never eat a whole shot."""
    from app.services.render_service import _transition_budget

    plan = TransitionPlan(
        choices=[
            TransitionChoice(index=1, transition="dissolve", duration=0.5),
            TransitionChoice(index=2, transition="dissolve", duration=0.5),
            TransitionChoice(index=3, transition="dip_to_black", duration=0.5),
        ],
        boundary_count=3,
    )
    durations = [3.0, 3.0, 0.6, 3.0]
    budget = _transition_budget(plan, durations, len(durations))

    check(
        "短すぎるカットには切り替えを置かない",
        all(
            budget.get(i, 0.0) <= min(durations[i - 1], durations[i]) * 0.4 + 1e-6
            for i in budget
        ),
        str(budget),
    )
    for index, seconds in budget.items():
        check(
            f"境界{index}: 前後のカットが0.4秒以上残る",
            durations[index - 1] - seconds >= 0.4 - 1e-6
            and durations[index] - seconds >= 0.4 - 1e-6,
            f"{seconds} from {durations[index - 1]}/{durations[index]}",
        )
    total_consumed = sum(budget.values())
    check(
        "消費される尺は要求より少ない",
        total_consumed <= 1.5 + 1e-6,
        f"{total_consumed}",
    )


# --------------------------------------------------------- captions


def test_subtitle_design() -> None:
    cues = [
        SimpleNamespace(text=t, start=float(i), end=float(i) + 1.0, design_json=None)
        for i, t in enumerate(
            [
                "沖縄に着いた",
                "そして",
                "海が最高だった",
                "3日間で5か所",
                "また来たい",
            ]
        )
    ]

    heavy = subtitle_design.design(cues, directive("tutorial"))
    light = subtitle_design.design(cues, directive("luxury"))
    check(
        "字幕量の方針が表示件数を変える",
        len(heavy.cues) > len(light.cues),
        f"tutorial={len(heavy.cues)} luxury={len(light.cues)}",
    )
    check(
        "落とした字幕を数える",
        light.dropped == len(cues) - len(light.cues),
        f"{light.dropped}",
    )
    check(
        "最初と最後の字幕は残す",
        {0, len(cues) - 1} <= {c.index for c in heavy.cues},
        str([c.index for c in heavy.cues]),
    )

    emphasised = {c.index: c.emphasis for c in heavy.cues if c.emphasis}
    check(
        "数字が強調語として拾われる",
        any("3" in e or "5" in e for e in emphasised.values()),
        str(emphasised),
    )
    check(
        "「最高」が強調語として拾われる",
        any("最高" in e for e in emphasised.values()),
        str(emphasised),
    )
    check(
        "全ての字幕に理由がつく",
        all(c.reason for c in heavy.cues),
    )

    # The ASS the design produces must be valid enough to carry the tags.
    settings = SubtitleSettings(font="Yu Gothic", size=64)
    ass = subtitle_style.build_ass(
        cues, settings, 1080, 1920, designs={c.index: c for c in heavy.cues}
    )
    check("ASSにスタイル定義がある", "[V4+ Styles]" in ass and "Style: Kairo," in ass)
    check("ASSに強調タグが入る", "\\fscx" in ass, ass[:200])
    check(
        "ASSの行数が表示件数と一致",
        ass.count("Dialogue: ") == len(heavy.cues),
        f"{ass.count('Dialogue: ')} vs {len(heavy.cues)}",
    )
    check("波括弧はスタイルタグ以外で使わない", ass.count("{") == ass.count("}"))

    # A cue with no design must render exactly as it always did.
    plain = subtitle_style.build_ass(cues, settings, 1080, 1920)
    check(
        "デザインなしの字幕は従来どおり",
        "\\fscx" not in plain and plain.count("Dialogue: ") == len(cues),
    )


# ------------------------------------------------------ photo motion


def test_photo_motion() -> None:
    d = directive("travel")
    # A subject on the far left of a landscape photo taken into a 9:16 frame.
    for subject in [(0.15, 0.5), (0.5, 0.5), (0.85, 0.3), None]:
        for camera in ("pan_right", "pan_left", "zoom_in", "zoom_out", ""):
            move = photo_motion.plan_move(
                camera=camera,
                index=0,
                directive=d,
                subject=subject,
                source_size=(1600, 1200),
                target_size=(1080, 1920),
            )
            for label, (cx, cy, zoom) in (
                ("start", (move.x_start, move.y_start, move.zoom_start)),
                ("end", (move.x_end, move.y_end, move.zoom_end)),
            ):
                half = 0.5 / max(1.0, zoom)
                check(
                    f"窓が画面外に出ない ({subject}, {camera or 'auto'}, {label})",
                    half - 1e-6 <= cx <= 1.0 - half + 1e-6
                    and half - 1e-6 <= cy <= 1.0 - half + 1e-6,
                    f"center=({cx},{cy}) zoom={zoom}",
                )
                if move.subject_known and move.subject_visible:
                    check(
                        f"被写体が窓の中に残る ({subject}, {camera or 'auto'}, {label})",
                        cx - half <= move.subject_x <= cx + half
                        and cy - half <= move.subject_y <= cy + half,
                        f"subject=({move.subject_x},{move.subject_y}) center=({cx},{cy}) zoom={zoom}",
                    )
            check(
                f"ズームが上限内 ({subject}, {camera or 'auto'})",
                photo_motion.MIN_ZOOM <= move.zoom_start <= photo_motion.MAX_ZOOM
                and photo_motion.MIN_ZOOM <= move.zoom_end <= photo_motion.MAX_ZOOM,
                f"{move.zoom_start}..{move.zoom_end}",
            )

    # Aspect-ratio mapping: a subject at the right edge of a 4:3 photo is
    # still on the right after a centre crop to 9:16.
    x, _y, known, _v = photo_motion.map_subject_to_frame(
        (0.65, 0.5), (1600, 1200), (1080, 1920)
    )
    check("横長→縦型のクロップで被写体位置が右寄りのまま", known and x > 0.5, f"x={x}")
    x2, _y2, _k2, _v2 = photo_motion.map_subject_to_frame(
        (0.35, 0.5), (1600, 1200), (1080, 1920)
    )
    check("同様に左寄りは左寄りのまま", x2 < 0.5, f"x={x2}")

    # A subject the aspect-ratio crop removes entirely is reported as such
    # rather than pretended to be at the frame edge.
    _x3, _y3, k3, v3 = photo_motion.map_subject_to_frame(
        (0.05, 0.5), (1600, 1200), (1080, 1920)
    )
    check("クロップで消えた被写体は「画面外」と報告される", k3 and not v3, f"known={k3} visible={v3}")

    # Style intensity has to reach the actual move.
    calm = photo_motion.plan_move(
        camera="zoom_in", index=0, directive=directive("cinematic"),
        subject=(0.5, 0.5), source_size=(1600, 1200), target_size=(1080, 1920),
    )
    lively = photo_motion.plan_move(
        camera="zoom_in", index=0, directive=directive("entertainment"),
        subject=(0.5, 0.5), source_size=(1600, 1200), target_size=(1080, 1920),
    )
    check(
        "スタイルの強さが動きの大きさに反映される",
        (lively.zoom_end - lively.zoom_start) > (calm.zoom_end - calm.zoom_start),
        f"entertainment={lively.zoom_end - lively.zoom_start:.3f} "
        f"cinematic={calm.zoom_end - calm.zoom_start:.3f}",
    )

    # A photo montage must not push in fourteen times.
    d_photo = directive("travel")
    kinds = {
        photo_motion.plan_move(
            camera="", index=i, directive=d_photo,
            subject=(0.5, 0.5), source_size=(1600, 1200), target_size=(1080, 1920),
        ).kind
        for i in range(6)
    }
    check("連続する写真で動きが変わる", len(kinds) >= 2, str(kinds))


# --------------------------------------------------------- font weight


def test_font_weight_measurement() -> None:
    """A declared weight is a claim; the measurement must override it."""
    info = SimpleNamespace(weight_class=400, units_per_em=1000, x_height=540, cap_height=726)
    check(
        "測定なしなら宣言値を使う",
        font_profile.perceived_weight(info, None) == 400,
    )
    check(
        "薄い文字は宣言値のまま（差が小さい）",
        font_profile.perceived_weight(info, 0.24) == 400,
        str(font_profile.perceived_weight(info, 0.24)),
    )
    check(
        "極太の見出し書体は再評価される",
        font_profile.perceived_weight(info, 0.72) >= 800,
        str(font_profile.perceived_weight(info, 0.72)),
    )
    heavy = SimpleNamespace(weight_class=700, units_per_em=1000, x_height=540, cap_height=726)
    check(
        "正しく宣言されたBoldはそのまま",
        font_profile.perceived_weight(heavy, 0.465) == 700,
        str(font_profile.perceived_weight(heavy, 0.465)),
    )


# ------------------------------------------------------ hook optimizer


class _FakeDB:
    def commit(self) -> None:
        pass


def test_hook_optimizer() -> None:
    d = directive("shorts", platform="youtube_shorts")
    scenes = [
        scene(subtitle_text="", estimated_duration=6.0, user_asset_id="weak"),
        scene(subtitle_text="海がきれい", estimated_duration=3.0, user_asset_id="strong"),
        scene(subtitle_text="また来たい", estimated_duration=3.0, user_asset_id="mid"),
        scene(subtitle_text="おわり", estimated_duration=3.0, user_asset_id="mid2"),
    ]
    analyses = {
        "weak": MaterialAnalysis(asset_id="weak", kind="image", brightness=0.12, quality_score=30),
        "strong": MaterialAnalysis(
            asset_id="strong", kind="video", brightness=0.6, motion=0.3,
            quality_score=92, sharpness=0.5,
        ),
        "mid": MaterialAnalysis(asset_id="mid", kind="image", brightness=0.5, quality_score=60),
        "mid2": MaterialAnalysis(asset_id="mid2", kind="image", brightness=0.5, quality_score=60),
    }
    report = hook_optimizer.optimize(_FakeDB(), scenes, d, analyses_by_asset=analyses)

    check("Shortsでは冒頭最適化が動く", report.applicable, report.skipped_reason)
    check(
        "一番強い画が冒頭に来る",
        scenes[0].user_asset_id == "strong",
        f"got {scenes[0].user_asset_id}",
    )
    check("移動元が記録される", report.moved_from == 1, str(report.moved_from))
    check(
        "長すぎる冒頭が短くなる",
        scenes[0].estimated_duration <= d.hook_seconds + 0.1,
        f"{scenes[0].estimated_duration} vs {d.hook_seconds}",
    )
    check("変更内容が説明される", bool(report.changes), str(report.changes))

    # A 16:9 explainer is not judged by the same rules.
    wide = directive("tutorial", platform="youtube_landscape")
    skipped = hook_optimizer.optimize(
        _FakeDB(),
        [scene(estimated_duration=4.0) for _ in range(4)],
        wide,
    )
    check("横型では冒頭最適化をスキップする", not skipped.applicable, skipped.skipped_reason)
    check("スキップ理由を必ず述べる", bool(skipped.skipped_reason))

    # A caption is written from the scene's own words, never invented.
    d2 = directive("shorts")
    only = [
        scene(subtitle_text="", narration="今日は沖縄の海に来ました。とてもきれいです。",
              estimated_duration=2.0, user_asset_id="mid"),
        scene(subtitle_text="a", estimated_duration=2.0),
        scene(subtitle_text="b", estimated_duration=2.0),
    ]
    report2 = hook_optimizer.optimize(_FakeDB(), only, d2, analyses_by_asset=analyses)
    check(
        "字幕のない冒頭にナレーションから字幕を作る",
        bool((only[0].subtitle_text or "").strip()),
        f"got {only[0].subtitle_text!r}",
    )
    check(
        "作った字幕はナレーションに含まれる語だけ",
        (only[0].subtitle_text or "") in "今日は沖縄の海に来ました。とてもきれいです。",
        f"got {only[0].subtitle_text!r}",
    )
    check("最適化の結果が報告される", bool(report2.findings or report2.changes))


# ------------------------------------------------------- scene budget


def test_scene_budget() -> None:
    """Requirement 8: do not design more shots than the material can cover.

    The case this exists for, measured on a real run of this repository:
    8 photos and a 30-second Shorts target produced 15 scenes, and 8 of
    them were filled from a web image search that returned a nebula, an
    Akihabara billboard and an 18th-century sculpture.
    """
    photos = [
        MaterialAnalysis(asset_id=f"p{i}", kind="image", brightness=0.5)
        for i in range(8)
    ]
    d = edit_director.decide(
        "沖縄ショート",
        duration_seconds=30,
        orientation="vertical",
        width=1080,
        height=1920,
        style_override="shorts",
        platform="youtube_shorts",
        analyses=photos,
        use_ai=False,
    )
    limit = scene_budget.budget(photos, d.scene_seconds)
    check(
        "写真8枚の上限は15シーンより少ない",
        0 < limit < 15,
        f"limit={limit}",
    )
    check(
        "上限は素材数を下回らない",
        limit >= len(photos),
        f"limit={limit} material={len(photos)}",
    )
    check(
        "素材が少ないとカットが伸びる",
        d.scene_seconds > 2.4,
        f"scene_seconds={d.scene_seconds}",
    )
    check(
        "素材が足りないことが記録される",
        any("素材" in n for n in d.notes),
        str(d.notes),
    )

    # No material at all means no bound: filling is the whole point there.
    check("素材なしなら上限を掛けない", scene_budget.budget([], 3.0) == 0)

    # "use all" must never cut below what the user supplied.
    check(
        "「全部使う」なら素材数を下回らない",
        scene_budget.budget(photos, 3.0, use_all=True) >= len(photos),
    )

    # A long clip is worth several shots; a photo is worth one.
    long_clip = [
        MaterialAnalysis(
            asset_id="v",
            kind="video",
            duration=30.0,
            usable=UsableRange(start=0.0, end=30.0),
        )
    ]
    check(
        "長い動画は複数カット分と数える",
        scene_budget.supportable_shots(long_clip, 3.0) >= 8,
        str(scene_budget.supportable_shots(long_clip, 3.0)),
    )
    check(
        "写真1枚は1カット",
        scene_budget.supportable_shots(photos, 3.0) == 8,
        str(scene_budget.supportable_shots(photos, 3.0)),
    )


def test_scene_trim() -> None:
    """Which scenes are dropped when the design is longer than the budget."""
    scenes = [
        scene(visual_prompt="海のカット", subtitle_text="開始", estimated_duration=3.0),
        scene(visual_prompt="同じ海のカット", subtitle_text="", narration="", estimated_duration=2.0),
        scene(visual_prompt="同じ海のカット", subtitle_text="海", estimated_duration=3.0),
        scene(visual_prompt="食事のカット", subtitle_text="", narration="", estimated_duration=1.5),
        scene(visual_prompt="街のカット", subtitle_text="街", estimated_duration=3.0),
        scene(visual_prompt="夕日のカット", subtitle_text="終わり", estimated_duration=3.0),
    ]
    kept, notes = scene_budget.trim_to_budget(scenes, 4)
    check("上限まで削られる", len(kept) == 4, str(len(kept)))
    check("先頭は残る", kept[0] is scenes[0])
    check("末尾は残る", kept[-1] is scenes[-1])
    check(
        "重複した無言のカットが最初に落ちる",
        scenes[1] not in kept,
        "scene 1 (duplicate visual, no words) survived",
    )
    check("削った理由が記録される", bool(notes), str(notes))

    # Already within budget: nothing is touched.
    same, no_notes = scene_budget.trim_to_budget(scenes, 10)
    check("上限内なら何も削らない", same is scenes and not no_notes)


# --------------------------------------------------------------- runner


def main() -> int:
    for suite in (
        test_directive,
        test_directive_material_adaptation,
        test_platform,
        test_transition_planner,
        test_transition_budget,
        test_subtitle_design,
        test_photo_motion,
        test_font_weight_measurement,
        test_hook_optimizer,
        test_scene_budget,
        test_scene_trim,
    ):
        print(f"\n== {suite.__name__} ==")
        suite()

    print("\n" + "=" * 60)
    print(f"{passed}/{passed + len(failures)} passed")
    for failure in failures:
        print(f"  FAILED: {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
