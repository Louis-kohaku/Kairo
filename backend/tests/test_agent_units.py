"""Fast, deterministic checks over the agent's decision logic.

No network, no LM Studio, no FFmpeg - these are the rules that must hold
regardless of what the environment can reach: how keywords are classified,
how trend scores age, which assets a licence lets through, how a font is
tagged, where beat-synced cuts land, and when the refinement loop stops.

The end-to-end behaviour is covered separately by `e2e_agent_pipeline.py`,
which does use real media.

Run with:
    backend/.venv/Scripts/python.exe backend/tests/test_agent_units.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.schemas.production_assets import AssetChoice, LicenseRef  # noqa: E402
from app.schemas.review import IterationRecord, ReviewFinding, VideoReview  # noqa: E402
from app.schemas.settings import RefinementSettings  # noqa: E402
from app.services.library import fontfile, fonts, licenses  # noqa: E402
from app.services.studio import creative_director, refinement  # noqa: E402
from app.services.trends import genre, store  # noqa: E402

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


# ------------------------------------------------------- genre taxonomy

def test_genre() -> None:
    cases = [
        ("沖縄旅行のショート動画", "travel"),
        ("子猫のしつけ", "pet"),
        ("ラーメン二郎に行ってきた", "food"),
        ("マイクラ攻略", "game"),
        ("ChatGPT の使い方", "tech"),
        ("投資信託の始め方", "business"),
    ]
    for text, expected in cases:
        check(f"classify: {text}", genre.classify(text) == expected,
              f"got {genre.classify(text)}, want {expected}")

    # The rule that stops a surname being filed as a travel video.
    check("単字キーワードは語全体のときだけ一致する",
          genre.classify("勧修寺玲旺") == "unknown" and genre.classify("猫") == "pet",
          f'勧修寺玲旺 -> {genre.classify("勧修寺玲旺")}, 猫 -> {genre.classify("猫")}')

    check("語彙に無い語はunknownのまま", genre.classify("zzz qqq 12345") == "unknown")

    profile = genre.default_profile("travel")
    check("既定プロファイルはジャンルごとに異なる",
          profile.bgm_mood != genre.default_profile("game").bgm_mood,
          f'travel={profile.bgm_mood} game={genre.default_profile("game").bgm_mood}')
    check("既定プロファイルは定石であることを明記する",
          "実測値ではありません" in (profile.notes or ""), profile.notes)


# --------------------------------------------------------- trend store

def test_store() -> None:
    check("NFKC正規化で全角/半角の同一語をまとめる",
          store.normalize_keyword("ＡＢＣ　テスト") == store.normalize_keyword("abc テスト"),
          f'{store.normalize_keyword("ＡＢＣ　テスト")!r} vs {store.normalize_keyword("abc テスト")!r}')

    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    fresh = store.effective_score(60.0, now, now=now)
    aged = store.effective_score(
        90.0, now - timedelta(hours=store.SCORE_HALF_LIFE_HOURS * 2), now=now
    )
    check("時間減衰: 新しい60点が2半減期前の90点を上回る",
          fresh > aged, f"fresh={fresh} aged={aged}")
    check("半減期でスコアがちょうど半分になる",
          abs(store.effective_score(80.0, now - timedelta(hours=store.SCORE_HALF_LIFE_HOURS),
                                    now=now) - 40.0) < 0.01)
    check("観測時刻が無ければ0点（推測しない）",
          store.effective_score(90.0, None) == 0.0)


# ------------------------------------------------------ licence gating

def test_licenses() -> None:
    check("未知のライセンスIDはunknownに解決する",
          licenses.get("なんらかの謎ライセンス").status == licenses.UNKNOWN)
    check("ライセンス不明は自動制作で使用不可",
          not licenses.is_auto_usable(licenses.UNKNOWN))
    check("商用利用不可は自動制作で使用不可",
          not licenses.is_auto_usable(licenses.NON_COMMERCIAL))
    check("OFLは使用可能", licenses.get("OFL-1.1").status == licenses.USABLE)
    check("CC-BYは帰属表示必要（使用は可）",
          licenses.get("CC-BY-4.0").status == licenses.ATTRIBUTION_REQUIRED
          and licenses.is_auto_usable(licenses.ATTRIBUTION_REQUIRED))
    check("OS同梱フォントは条件付きだが描画には使える",
          licenses.get("system-bundled").status == licenses.CONDITIONAL
          and licenses.is_auto_usable(licenses.CONDITIONAL))
    check("商用限定モードではCC-BY-NCが弾かれる",
          not licenses.is_auto_usable(
              licenses.NON_COMMERCIAL, require_commercial=True, license_id="CC-BY-NC-4.0"))
    check("すべてのライセンスに日本語の説明がある",
          all(entry["summary"] for entry in licenses.catalog()))


# ---------------------------------------------------- font intelligence

def test_fonts() -> None:
    serif = fontfile.FontInfo(family="Times New Roman", panose=(2, 2, 6, 3, 5, 4, 5, 2, 3, 4),
                              weight_class=400, units_per_em=2048, x_height=1062, cap_height=1467)
    sans = fontfile.FontInfo(family="Arial", panose=(2, 11, 6, 4, 2, 2, 2, 2, 2, 4),
                             weight_class=700, units_per_em=2048, x_height=1062, cap_height=1467)
    hand = fontfile.FontInfo(family="Comic Sans MS", panose=(3, 15, 7, 2, 3, 3, 2, 2, 2, 4),
                             weight_class=400, units_per_em=2048, x_height=1062)
    thin = fontfile.FontInfo(family="Thin Face", panose=(2, 11, 2, 4, 2, 2, 2, 2, 2, 4),
                             weight_class=200, units_per_em=1000, x_height=480)

    check("PANOSEからセリフを判定する", "serif" in fonts.style_tags(serif, serif.family))
    check("PANOSEからサンセリフを判定する", "sans" in fonts.style_tags(sans, sans.family))
    check("PANOSEから手書き風を判定する", "handwritten" in fonts.style_tags(hand, hand.family))
    check("ウェイトからboldタグを付ける", "bold" in fonts.style_tags(sans, sans.family))

    sans_score = fonts.readability_score(sans, fonts.style_tags(sans, sans.family))
    thin_score = fonts.readability_score(thin, fonts.style_tags(thin, thin.family))
    hand_score = fonts.readability_score(hand, fonts.style_tags(hand, hand.family))
    check("可読性: 太いサンセリフ > 極細",
          sans_score > thin_score, f"sans={sans_score} thin={thin_score}")
    check("可読性: 太いサンセリフ > 手書き風",
          sans_score > hand_score, f"sans={sans_score} hand={hand_score}")
    check("可読性は0-100に収まる", 0 <= sans_score <= 100 and 0 <= thin_score <= 100)

    check("ジャンル適性はタグから決まる",
          "game" in fonts.genre_fit(["impact", "bold", "sans"]),
          str(fonts.genre_fit(["impact", "bold", "sans"])))
    check("該当タグが無いジャンルには推薦しない",
          fonts.genre_fit(["symbol"]) == [], str(fonts.genre_fit(["symbol"])))

    ja = fontfile.FontInfo(supports_japanese=True, supports_latin=True)
    check("言語判定はcmapの結果を使う",
          fonts.languages(ja) == ["ja", "en"] and fonts.language_dir(ja) == "multi")


# ------------------------------------------------------------ beat sync

class _Scene:
    def __init__(self, duration: float) -> None:
        self.estimated_duration = duration
        self.sfx = ""


def test_beat_sync() -> None:
    music = AssetChoice(kind="music", found=True, name="test", bpm=120.0,
                        source="Kairo内蔵シンセ", license=LicenseRef())
    scenes = [_Scene(d) for d in (2.4, 3.1, 2.9, 3.4)]
    plan = creative_director.plan_beat_sync(scenes, music, target_scene_seconds=3.0)
    check("テンポが分かればビート同期を計画する", plan.applied, plan.reason)
    check("拍の倍数でカット長を決める",
          plan.beats_per_cut in (1, 2, 3, 4, 6, 8), str(plan.beats_per_cut))

    creative_director.apply_beat_sync(scenes, plan)
    grid = (plan.beat_seconds or 0) * plan.beats_per_cut
    residuals = [abs(s.estimated_duration / grid - round(s.estimated_duration / grid)) * grid
                 for s in scenes]
    check("適用後の各カットがグリッド上にある",
          max(residuals) < 0.02, f"max residual {max(residuals) * 1000:.0f}ms")

    no_bpm = AssetChoice(kind="music", found=True, name="ambient", bpm=None,
                         license=LicenseRef())
    plan2 = creative_director.plan_beat_sync([_Scene(3.0)], no_bpm, target_scene_seconds=3.0)
    check("テンポ不明なら同期しない（120と決めつけない）",
          not plan2.applied and plan2.bpm is None, plan2.reason)

    missing = creative_director.plan_beat_sync([_Scene(3.0)], None, target_scene_seconds=3.0)
    check("BGMが無ければ同期しない", not missing.applied, missing.reason)

    # A scene whose length came from measured narration must not be stretched
    # far enough that the audio would run past the cut.
    long_scene = [_Scene(10.0)]
    plan3 = creative_director.plan_beat_sync(long_scene, music, target_scene_seconds=3.0)
    creative_director.apply_beat_sync(long_scene, plan3)
    check("1シーンの移動量は上限内に収まる",
          abs(long_scene[0].estimated_duration - 10.0) <= 10.0 * 0.35 + 0.01,
          f"{long_scene[0].estimated_duration}")


# ----------------------------------------------------------- refinement

def _review(score: float, fixable: int = 1) -> VideoReview:
    return VideoReview(
        performed=True,
        overall_score=score,
        findings=[
            ReviewFinding(axis="pacing", problem="p", fix="set_duration", fix_value=2.0)
            for _ in range(fixable)
        ],
    )


def test_refinement() -> None:
    settings = RefinementSettings(enabled=True, max_iterations=3, target_score=85.0, min_gain=2.0)
    history = [IterationRecord(iteration=0, score=60.0)]

    check("目標未達かつ修正可能なら継続する",
          refinement.should_continue(settings, history, _review(60.0))[0])

    ok, reason = refinement.should_continue(settings, history, _review(90.0))
    check("目標到達で停止する", not ok, reason)

    ok, reason = refinement.should_continue(settings, history, _review(60.0, fixable=0))
    check("修正可能な指摘が無ければ停止する", not ok, reason)

    ok, reason = refinement.should_continue(
        settings, [IterationRecord(iteration=i, score=60.0) for i in range(3)], _review(60.0))
    check("最大反復回数で停止する", not ok, reason)

    ok, reason = refinement.should_continue(
        settings,
        [IterationRecord(iteration=0, score=60.0), IterationRecord(iteration=1, score=60.5)],
        _review(60.5),
    )
    check("改善幅が小さければ停止する", not ok, reason)

    ok, reason = refinement.should_continue(
        RefinementSettings(enabled=False), history, _review(10.0))
    check("設定でOFFなら実行しない", not ok, reason)

    best = refinement.best_iteration([
        IterationRecord(iteration=0, score=88.0),
        IterationRecord(iteration=1, score=79.0),
        IterationRecord(iteration=2, score=85.0),
    ])
    check("最後ではなく最良の版を採用する",
          best is not None and best.iteration == 0 and best.score == 88.0,
          f"iteration={best.iteration if best else None}")

    tie = refinement.best_iteration([
        IterationRecord(iteration=0, score=80.0),
        IterationRecord(iteration=1, score=80.0),
    ])
    check("同点なら変更の少ない先の版を採る",
          tie is not None and tie.iteration == 0)


# ------------------------------------------------------- act structure

def test_act_structure() -> None:
    """Act count follows the video's length.

    A real Full Auto run failed because a 30-second brief was planned as
    five acts, and every act costs one scene-design request to the local
    model. Both the structure and the cost argue for fewer, longer acts on
    a short video.
    """
    from unittest import mock

    from app.schemas.studio import ProductionStrategy
    from app.services.studio import planning_service as ps

    check("15秒はちょうど2幕", ps.act_range(15.0) == (2, 2), str(ps.act_range(15.0)))
    check("30秒は2〜3幕", ps.act_range(30.0) == (2, 3), str(ps.act_range(30.0)))
    check("120秒は3〜5幕", ps.act_range(120.0) == (3, 5), str(ps.act_range(120.0)))
    check(
        "尺が長いほど幕数の上限が増える",
        ps.act_range(15.0)[1] < ps.act_range(60.0)[1] <= ps.act_range(300.0)[1],
    )

    five_acts = {
        "title": "T", "target_audience": "A", "tone": "t",
        "chapters": [
            {"title": f"幕{i}", "summary": f"内容{i}", "seconds": 6} for i in range(1, 6)
        ],
    }

    with mock.patch.object(ps, "_ask_json", return_value=dict(five_acts)):
        short_plan, short_budgets = ps.generate_plan("旅行", ProductionStrategy(), 30.0)
    check(
        "短い動画では余分な幕が上限まで畳まれる",
        len(short_plan.chapters) == 3, f"{len(short_plan.chapters)}幕",
    )
    check(
        "畳まれた幕の内容は捨てずに最終幕へ引き継ぐ（オチを失わない）",
        "内容5" in short_plan.chapters[-1].summary, short_plan.chapters[-1].summary,
    )
    check(
        "畳んだあとも尺の配分が目標尺と一致する",
        abs(sum(short_budgets) - 30.0) < 0.01, f"{sum(short_budgets)}",
    )

    with mock.patch.object(ps, "_ask_json", return_value=dict(five_acts)):
        long_plan, long_budgets = ps.generate_plan("旅行", ProductionStrategy(), 120.0)
    check("長い動画では5幕がそのまま通る", len(long_plan.chapters) == 5,
          f"{len(long_plan.chapters)}幕")
    check("長い動画でも尺の合計が一致する",
          abs(sum(long_budgets) - 120.0) < 0.01, f"{sum(long_budgets)}")


# ------------------------------------------------- web material dedupe

class _Asset:
    def __init__(self, origin_detail: str) -> None:
        self.origin_detail = origin_detail


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return self._rows


class _FakeDb:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *_args):
        return _FakeQuery(self._rows)


def test_web_dedupe() -> None:
    """The web fill must not hand the same photo to several scenes.

    In a real 13-scene run one sunset photo filled scenes 4, 8 and 11 - eight
    downloads for five distinct images - and Kairo's own reviewer reported it
    as repetition.
    """
    from app.services.studio.material_service import _used_web_sources, _web_identity

    class WithPage:
        source_page = "https://www.flickr.com/photos/57085156@N00/6260629007"
        url = "https://live.staticflickr.com/x.jpg"

    class UrlOnly:
        source_page = ""
        url = "https://live.staticflickr.com/y.jpg"

    class Empty:
        source_page = ""
        url = ""

    check("出典ページがあればそれを識別子にする",
          _web_identity(WithPage()) == WithPage.source_page, _web_identity(WithPage()))
    check("出典ページが無ければ画像URLを識別子にする",
          _web_identity(UrlOnly()) == UrlOnly.url, _web_identity(UrlOnly()))
    check("識別子が取れない候補は重複判定に使わない",
          _web_identity(Empty()) == "", repr(_web_identity(Empty())))

    # origin_detail is written as "<attribution> / <source page>".
    rows = [
        _Asset("Photo by A (CC BY 2.0) / https://www.flickr.com/photos/57085156@N00/6260629007"),
        _Asset("Photo by B (CC0) / https://example.org/photos/2"),
        _Asset("https://example.org/photos/3"),  # older rows had no attribution
    ]
    used = _used_web_sources(_FakeDb(rows), "project")
    check("既に使ったWeb素材の出典を抽出できる", len(used) == 3, str(used))
    check("同じ写真は2回目以降スキップされる",
          _web_identity(WithPage()) in used, _web_identity(WithPage()))
    check("まだ使っていない写真はスキップされない",
          _web_identity(UrlOnly()) not in used)
    check("属性が無い古い行も識別子として扱える",
          "https://example.org/photos/3" in used, str(used))


# ------------------------------------------------------ model selection

def test_model_selection() -> None:
    """Text work should not be handed to a vision model unnecessarily.

    On this machine LM Studio had a 7B VLM and a small text-only model
    loaded at once; Kairo picked the VLM for script writing, which then
    timed out at 600s in one run and crashed LM Studio in two more.
    """
    from app.services import llm_client

    both = [
        "qwen_qwen2.5-vl-7b-instruct",
        "text-embedding-nomic-embed-text-v2-moe",
        "google/gemma-4-e2b",
    ]
    chosen = llm_client.resolve_model(both)
    check(
        "テキスト専用モデルがあれば文章生成にはそちらを使う",
        chosen.model_id is not None and not llm_client.is_vision_model(chosen.model_id),
        f"chose {chosen.model_id}",
    )
    check(
        "なぜVisionモデルを避けたかを理由に残す",
        "素材解析用に温存" in (chosen.reason or ""), (chosen.reason or "")[:80],
    )

    only_vision = ["qwen_qwen2.5-vl-7b-instruct", "text-embedding-nomic-embed-text-v2-moe"]
    fallback = llm_client.resolve_model(only_vision)
    check(
        "Visionモデルしか無ければそれを使う（機能を落とさない）",
        fallback.model_id == "qwen_qwen2.5-vl-7b-instruct", str(fallback.model_id),
    )

    check(
        "埋め込みモデルは文章生成に選ばない",
        llm_client.resolve_model(["text-embedding-nomic-embed-text-v2-moe"]).model_id is None,
    )
    check("Visionモデルの判定が効いている",
          llm_client.is_vision_model("qwen2.5-vl-7b")
          and not llm_client.is_vision_model("google/gemma-4-e2b"))


# --------------------------------------------------------------- runner

def main() -> int:
    for suite in (test_genre, test_store, test_licenses, test_fonts,
                  test_beat_sync, test_refinement, test_act_structure,
                  test_web_dedupe, test_model_selection):
        print(f"\n== {suite.__name__} ==")
        suite()

    print("\n" + "=" * 60)
    print(f"{passed}/{passed + len(failures)} passed")
    for failure in failures:
        print(f"  FAILED: {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
