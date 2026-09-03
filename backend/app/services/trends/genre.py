"""Kairo's video-genre taxonomy, keyword classification, and genre profiles.

Trend data is only useful to a video planner if it is organised the way
videos are organised. A flat "今流行っている語" list tells the planner
nothing about how long the video should be or where the captions go; a
genre does.

Classification is deliberately lexical and conservative. A keyword that
matches no genre's vocabulary is filed as "unknown" rather than pushed into
the nearest one - a mis-filed trend is worse than an unfiled one, because
the planner would then build the wrong kind of video from it.

Profiles come in two grades and always say which they are:

* ``derived_from="defaults"`` - Kairo's built-in short-form conventions.
  Format knowledge, not a finding, and labelled that way everywhere.
* ``derived_from="llm"`` - the local model's analysis of the trend signals
  actually collected for that genre, with ``sample_size`` recording how
  many signals it saw.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from app.schemas.trend import GenreProfileData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Genre:
    id: str
    label: str
    # Match vocabulary. Matched as substrings against the case-folded
    # keyword, so Japanese (no word boundaries) works the same as English.
    keywords: tuple[str, ...] = field(default_factory=tuple)


GENRES: tuple[Genre, ...] = (
    Genre(
        "travel",
        "旅行",
        (
            "旅行", "旅先", "観光", "絶景", "神社", "お寺", "ホテル", "旅館",
            "沖縄", "北海道", "京都", "海外", "空港", "ビーチ", "温泉", "travel",
            "trip", "tourism", "vacation", "resort", "国内旅行",
        ),
    ),
    Genre(
        "pet",
        "動物・ペット",
        ("猫", "ねこ", "ネコ", "犬", "いぬ", "イヌ", "子猫", "子犬", "ペット", "動物",
         "うさぎ", "ハムスター", "cat", "dog", "puppy", "kitten", "pet", "animal"),
    ),
    Genre(
        "food",
        "料理・グルメ",
        ("料理", "レシピ", "グルメ", "食べ", "ラーメン", "カフェ", "スイーツ", "弁当",
         "居酒屋", "寿司", "菓子パン", "お菓子", "cooking", "recipe", "food", "cafe",
         "restaurant", "dessert"),
    ),
    Genre(
        "game",
        "ゲーム",
        ("ゲーム", "実況", "攻略", "eスポーツ", "スイッチ", "ps5", "steam", "マイクラ",
         "フォートナイト", "アプデ", "game", "gaming", "esports", "gameplay", "rpg"),
    ),
    Genre(
        "vlog",
        "Vlog・日常",
        ("vlog", "日常", "ルーティン", "routine", "一人暮らし",
         "暮らし", "生活", "daily", "lifestyle", "同棲", "休日"),
    ),
    Genre(
        "beauty",
        "美容・ファッション",
        ("美容", "コスメ", "メイク", "スキンケア", "ヘア", "ファッション", "コーデ",
         "ネイル", "ダイエット", "beauty", "makeup", "cosmetic", "skincare",
         "fashion", "outfit", "hair"),
    ),
    Genre(
        "education",
        "教育・解説",
        ("解説", "勉強", "学習", "講座", "入門", "使い方", "コツ", "資格", "英語",
         "教育", "howto", "how to", "tutorial", "explained", "study", "learn",
         "初心者"),
    ),
    Genre(
        "entertainment",
        "エンタメ",
        ("芸能", "ドラマ", "映画", "アニメ", "音楽", "ライブ", "アイドル", "お笑い",
         "声優", "movie", "anime", "drama", "music", "idol", "comedy", "live",
         "紅白", "デビュー"),
    ),
    Genre(
        "sports",
        "スポーツ",
        ("野球", "サッカー", "スポーツ", "オリンピック", "ワールドカップ",
         "バスケ", "テニス", "ゴルフ", "格闘", "相撲", "マラソン", "sports",
         "soccer", "football", "baseball", "nba", "mlb"),
    ),
    Genre(
        "tech",
        "テクノロジー",
        ("ai", "iphone", "android", "ガジェット", "アプリ", "テック", "chatgpt",
         "スマホ", "パソコン", "tech", "gadget", "software", "programming", "開発"),
    ),
    Genre(
        "news",
        "ニュース・時事",
        ("速報", "ニュース", "地震", "台風", "選挙", "政府", "株価", "為替", "事件",
         "会見", "news", "breaking", "weather", "警報"),
    ),
    Genre(
        "business",
        "ビジネス・お金",
        ("投資", "副業", "節約", "転職", "仕事", "営業", "起業", "nisa", "税金",
         "business", "money", "invest", "career", "finance"),
    ),
)

GENRE_BY_ID: dict[str, Genre] = {g.id: g for g in GENRES}
UNKNOWN = Genre("unknown", "分類なし")


def label(genre_id: str) -> str:
    return GENRE_BY_ID[genre_id].label if genre_id in GENRE_BY_ID else UNKNOWN.label


def classify(text: str, *, hint: str = "") -> str:
    """Files a keyword under a genre, or "unknown".

    ``hint`` is a provider-supplied category (YouTube's category name, for
    example); it is folded into the same match because a platform's own
    classification is evidence too. The longest matching term wins, so a
    specific word beats an incidental one.

    Single-character terms only count when they *are* the whole keyword.
    Japanese has no word boundaries, so a bare "寺" matches the surname
    勧修寺 and a bare "猫" matches 猫田 - substring matching at that length
    files people's names under 旅行 and 動物・ペット, which is worse than
    leaving them unclassified.
    """
    haystack = f"{hint} {text}".casefold()
    if not haystack.strip():
        return "unknown"
    whole = text.strip().casefold()

    best_id = "unknown"
    best_len = 0
    for genre in GENRES:
        for kw in genre.keywords:
            if len(kw) < 2 and kw != whole:
                continue
            if kw in haystack and len(kw) > best_len:
                best_id, best_len = genre.id, len(kw)
    return best_id


def classify_instruction(instruction: str) -> str:
    """The genre of a production brief. Same vocabulary as `classify`, so an
    instruction and a trend keyword land in the same bucket."""
    return classify(instruction)


# ------------------------------------------------------- default profiles

# Built-in short-form conventions, used when no trend evidence exists for a
# genre. These are format knowledge (what the vertical short format
# rewards), not claims about what is currently trending, and every consumer
# labels them as such.
_BASE_DEFAULT = GenreProfileData(
    duration_seconds=45.0,
    scene_seconds=3.0,
    hook_seconds=2.5,
    hook_patterns=["結論や見どころを最初に出す", "動きのある瞬間から始める"],
    opening_patterns=["被写体と状況を2秒以内に提示する"],
    cut_tempo="medium",
    subtitle_density="medium",
    subtitle_position="bottom",
    subtitle_style="outline",
    font_style=["gothic", "clean"],
    bgm_mood="gentle",
    bgm_bpm_range=[90.0, 120.0],
    sfx_usage=["場面転換にwhoosh", "字幕の出現にpop"],
    transitions=["cut"],
    title_patterns=["主題と数字", "問いかけ"],
    cta_patterns=["最後に一言の余韻"],
    notes="Kairo組み込みのショート動画の定石です（トレンド実測値ではありません）。",
)

_GENRE_DEFAULTS: dict[str, dict] = {
    "travel": {
        "duration_seconds": 40.0, "scene_seconds": 2.6, "cut_tempo": "medium",
        "bgm_mood": "bright", "bgm_bpm_range": [100.0, 125.0],
        "font_style": ["modern", "clean", "rounded"],
        "hook_patterns": ["一番の絶景を冒頭に置く", "行き先を最初に言い切る"],
        "sfx_usage": ["場面転換にwhoosh", "水辺のシーンにambience"],
        "subtitle_density": "low",
    },
    "pet": {
        "duration_seconds": 25.0, "scene_seconds": 2.2, "cut_tempo": "fast",
        "bgm_mood": "playful", "bgm_bpm_range": [110.0, 140.0],
        "font_style": ["rounded", "friendly"],
        "hook_patterns": ["いちばん可愛い瞬間から始める"],
        "sfx_usage": ["動きの決めにpop", "驚きにhit"],
        "subtitle_density": "medium",
    },
    "food": {
        "duration_seconds": 35.0, "scene_seconds": 2.4, "cut_tempo": "fast",
        "bgm_mood": "warm", "bgm_bpm_range": [95.0, 120.0],
        "font_style": ["rounded", "bold"],
        "hook_patterns": ["完成カットを冒頭に出す"],
        "sfx_usage": ["調理音を強調", "盛り付けにpop"],
        "subtitle_density": "high",
    },
    "game": {
        "duration_seconds": 45.0, "scene_seconds": 2.0, "cut_tempo": "fast",
        "bgm_mood": "energetic", "bgm_bpm_range": [125.0, 160.0],
        "font_style": ["bold", "impact"],
        "hook_patterns": ["決定的な場面を先に見せる"],
        "sfx_usage": ["ヒット音", "場面転換にwhoosh"],
        "subtitle_density": "high",
    },
    "vlog": {
        "duration_seconds": 50.0, "scene_seconds": 3.2, "cut_tempo": "medium",
        "bgm_mood": "gentle", "bgm_bpm_range": [85.0, 110.0],
        "font_style": ["clean", "light"],
        "subtitle_density": "medium",
    },
    "beauty": {
        "duration_seconds": 35.0, "scene_seconds": 2.4, "cut_tempo": "fast",
        "bgm_mood": "bright", "bgm_bpm_range": [105.0, 130.0],
        "font_style": ["modern", "elegant"],
        "hook_patterns": ["ビフォーアフターを冒頭に並べる"],
        "subtitle_density": "high",
    },
    "education": {
        "duration_seconds": 55.0, "scene_seconds": 3.5, "cut_tempo": "slow",
        "bgm_mood": "calm", "bgm_bpm_range": [80.0, 105.0],
        "font_style": ["gothic", "bold", "readable"],
        "hook_patterns": ["結論を先に言う", "よくある間違いを提示する"],
        "subtitle_density": "high",
        "cta_patterns": ["要点を1枚でまとめる"],
    },
    "entertainment": {
        "duration_seconds": 40.0, "scene_seconds": 2.2, "cut_tempo": "fast",
        "bgm_mood": "energetic", "bgm_bpm_range": [115.0, 145.0],
        "font_style": ["bold", "impact"],
        "subtitle_density": "high",
    },
    "sports": {
        "duration_seconds": 40.0, "scene_seconds": 2.0, "cut_tempo": "fast",
        "bgm_mood": "energetic", "bgm_bpm_range": [120.0, 150.0],
        "font_style": ["bold", "impact"],
        "hook_patterns": ["決定的なプレーから始める"],
    },
    "tech": {
        "duration_seconds": 50.0, "scene_seconds": 3.0, "cut_tempo": "medium",
        "bgm_mood": "modern", "bgm_bpm_range": [100.0, 125.0],
        "font_style": ["modern", "clean"],
        "subtitle_density": "high",
    },
    "news": {
        "duration_seconds": 45.0, "scene_seconds": 3.0, "cut_tempo": "medium",
        "bgm_mood": "neutral", "bgm_bpm_range": [90.0, 110.0],
        "font_style": ["gothic", "bold", "readable"],
        "subtitle_density": "high",
    },
    "business": {
        "duration_seconds": 55.0, "scene_seconds": 3.4, "cut_tempo": "slow",
        "bgm_mood": "calm", "bgm_bpm_range": [85.0, 110.0],
        "font_style": ["gothic", "clean", "readable"],
        "hook_patterns": ["損得を最初に提示する"],
        "subtitle_density": "high",
    },
}


def default_profile(genre_id: str) -> GenreProfileData:
    data = _BASE_DEFAULT.model_dump()
    data.update(_GENRE_DEFAULTS.get(genre_id, {}))
    data["genre"] = genre_id
    data["label"] = label(genre_id)
    return GenreProfileData.model_validate(data)


# ------------------------------------------------------------ LLM pass


def _analysis_prompt(genre_id: str, keywords: list[str]) -> list[dict]:
    system = (
        "あなたはショート動画のフォーマット分析官です。"
        f"「{label(genre_id)}」ジャンルの動画が実際にどう作られているかを、"
        "与えられた最新トレンドキーワードを踏まえて構造化してください。\n\n"
        "重要な制約:\n"
        "- 分からない項目は null または空配列にすること。推測で埋めないこと。\n"
        "- 数値は日本の縦型ショート動画(9:16)を前提にすること。\n"
        "- JSONオブジェクトのみを出力すること。\n\n"
        "出力形式:\n"
        '{"duration_seconds": 40, "scene_seconds": 2.5, "hook_seconds": 2.5, '
        '"hook_patterns": [], "opening_patterns": [], '
        '"cut_tempo": "fast", "subtitle_density": "high", '
        '"subtitle_position": "bottom", "subtitle_style": "outline", '
        '"font_style": [], "bgm_mood": "", "bgm_bpm_range": [100, 125], '
        '"sfx_usage": [], "transitions": [], "title_patterns": [], '
        '"cta_patterns": [], "hashtags": [], "notes": ""}\n\n'
        "cut_tempo は fast / medium / slow、subtitle_density は high / medium / low、"
        "subtitle_position は top / middle / bottom、subtitle_style は outline / box / plain。"
    )
    user = (
        f"ジャンル: {label(genre_id)}\n"
        f"直近のトレンドキーワード: {', '.join(keywords[:25]) or '(なし)'}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def analyze(genre_id: str, keywords: list[str]) -> tuple[GenreProfileData, str]:
    """Asks the local model to profile a genre from its trend keywords.

    Returns ``(profile, derived_from)``. Falls back to the built-in defaults
    - labelled as defaults - whenever the model is unavailable or returns
    something unusable. Fields the model omits keep the default value, so a
    partial answer improves the profile instead of hollowing it out.
    """
    from app.services import llm_client
    from app.services.json_extract import JSONExtractionError, parse_json_object

    base = default_profile(genre_id)
    if not keywords:
        return base, "defaults"

    try:
        raw = llm_client.chat_completion(_analysis_prompt(genre_id, keywords), temperature=0.2)
        data = parse_json_object(raw)
    except (
        JSONExtractionError,
        llm_client.LLMUnavailableError,
        llm_client.LLMTimeoutError,
        llm_client.LLMResponseError,
        llm_client.LLMNotReadyError,
    ) as exc:
        logger.info("Genre profile analysis unavailable for %s: %s", genre_id, exc)
        return base, "defaults"
    except Exception:
        logger.exception("Genre profile analysis failed for %s", genre_id)
        return base, "defaults"

    merged = base.model_dump()
    for key, value in data.items():
        if key not in merged:
            continue
        if value in (None, "", [], {}):
            continue
        merged[key] = value
    merged["genre"] = genre_id
    merged["label"] = label(genre_id)
    merged["evidence"] = keywords[:25]
    merged["notes"] = str(data.get("notes") or "")[:400] or (
        f"直近の{label(genre_id)}トレンド{len(keywords)}件からローカルLLMが分析しました。"
    )
    try:
        return GenreProfileData.model_validate(merged), "llm"
    except Exception:
        logger.exception("Genre profile validation failed for %s", genre_id)
        return base, "defaults"


def profile_to_json(profile: GenreProfileData) -> str:
    return json.dumps(profile.model_dump(), ensure_ascii=False)
