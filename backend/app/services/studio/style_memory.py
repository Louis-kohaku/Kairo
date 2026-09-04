"""Kairo Style Memory: what this user tends to choose (requirement 16).

Two jobs, and they pull in opposite directions, so both are handled here
explicitly rather than left to whichever caller happens to read the file:

* **Preference.** When the user changes something by hand - the caption
  size, the position, the BGM volume, the colour - that is a standing
  signal about how they like their videos, and the next production should
  start from it. An explicit change always wins over anything remembered,
  because the newest explicit choice *is* the preference.
* **Variety.** What Kairo itself chose last time is the opposite kind of
  memory: it exists so the next video does not look identical. The font
  ranking reads `recent_fonts` to penalise repetition.

Stored as one JSON file under DATA_ROOT, next to settings.json. Local only,
never sent anywhere, and safe to delete - a missing file means "no history",
which every reader already handles.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from app.core.config import DATA_ROOT

logger = logging.getLogger(__name__)

MEMORY_PATH = DATA_ROOT / "style_memory.json"

# How many past productions are remembered per axis.
HISTORY_LIMIT = 12
# The variety window the font ranking uses.
RECENT_FONT_WINDOW = 6

_lock = threading.Lock()

_EMPTY: dict[str, Any] = {
    "version": 1,
    # What Kairo chose, newest first. Used for variety, not for preference.
    "recent_fonts": [],
    "recent_music": [],
    "recent_grades": [],
    "recent_styles": [],
    # What the user changed by hand, newest wins. Used as a starting point.
    "preferences": {},
    # Every recorded production, newest first, for the "好みの傾向" view.
    "history": [],
    "updated_at": None,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load() -> dict:
    """The stored memory, or an empty one.

    Unreadable JSON is treated as absent rather than fatal: style memory is
    a convenience, and losing a production to a corrupt preferences file
    would be a far worse outcome than starting from defaults.
    """
    if not MEMORY_PATH.exists():
        return json.loads(json.dumps(_EMPTY))
    try:
        data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.info("Style memory unreadable; starting from empty")
        return json.loads(json.dumps(_EMPTY))
    if not isinstance(data, dict):
        return json.loads(json.dumps(_EMPTY))
    merged = json.loads(json.dumps(_EMPTY))
    merged.update(data)
    return merged


def _save(data: dict) -> None:
    data["updated_at"] = _now()
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = MEMORY_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(MEMORY_PATH)


def _push(items: list, value, limit: int = HISTORY_LIMIT) -> list:
    """Newest first, deduplicated, capped."""
    if value in (None, ""):
        return items
    out = [value] + [i for i in items if i != value]
    return out[:limit]


# ------------------------------------------------------------ variety


def recent_fonts(window: int = RECENT_FONT_WINDOW) -> list[str]:
    """Font families recent productions used, newest first."""
    return [str(f) for f in load().get("recent_fonts", [])][:window]


def recent_music(window: int = RECENT_FONT_WINDOW) -> list[str]:
    return [str(m) for m in load().get("recent_music", [])][:window]


# --------------------------------------------------------- preferences


# The axes the user can change by hand, and what each means. Only these are
# remembered: a preference store that absorbed every field would start
# overriding decisions the user never made.
PREFERENCE_KEYS: tuple[str, ...] = (
    "subtitle_size",
    "subtitle_position",
    "subtitle_style",
    "subtitle_color",
    "bgm_volume",
    "color_grade",
    "transition_appetite",
    "caption_density",
    "tempo",
    "font_family",
)

PREFERENCE_LABELS: dict[str, str] = {
    "subtitle_size": "字幕サイズ",
    "subtitle_position": "字幕位置",
    "subtitle_style": "字幕の縁取り",
    "subtitle_color": "字幕の色",
    "bgm_volume": "BGM音量",
    "color_grade": "色味",
    "transition_appetite": "画面切り替えの量",
    "caption_density": "テロップ量",
    "tempo": "動画テンポ",
    "font_family": "フォント",
}


def remember_preference(key: str, value, *, source: str = "user") -> None:
    """Records an explicit user choice. The newest one always wins.

    `source` is kept so the UI can distinguish "you chose this" from
    "Kairo inferred this", which matters: the brief says an explicit change
    must take priority, and that is only enforceable if the two are told
    apart.
    """
    if key not in PREFERENCE_KEYS or value in (None, ""):
        return
    with _lock:
        data = load()
        prefs = data.setdefault("preferences", {})
        prefs[key] = {"value": value, "source": source, "at": _now()}
        _save(data)


def preference(key: str, default=None):
    entry = load().get("preferences", {}).get(key)
    if not isinstance(entry, dict):
        return default
    return entry.get("value", default)


def preferences() -> dict:
    """Every remembered preference, as {key: {value, source, at, label}}."""
    out = {}
    for key, entry in (load().get("preferences") or {}).items():
        if key not in PREFERENCE_KEYS or not isinstance(entry, dict):
            continue
        out[key] = {**entry, "label": PREFERENCE_LABELS.get(key, key)}
    return out


def apply_to_directive(directive) -> list[str]:
    """Starts a directive from what the user has previously preferred.

    Applied *before* the material and AI layers, so a remembered preference
    is a starting point the director can still overrule with evidence - and
    so the AI's own reasoning is never silently discarded by a stale
    preference. Returns the notes describing what was applied.

    A preference is not applied when it would break the format: a
    remembered 16:9 caption size on a 9:16 short, for instance, is a number
    from a different frame.
    """
    prefs = preferences()
    if not prefs:
        return []
    notes: list[str] = []

    position = prefs.get("subtitle_position", {}).get("value")
    if position in ("top", "middle", "bottom"):
        directive.subtitle.position = position
        notes.append(f"字幕位置は前回の設定「{position}」を引き継ぎました")

    style = prefs.get("subtitle_style", {}).get("value")
    if style in ("outline", "box", "plain"):
        directive.subtitle.style = style
        notes.append(f"字幕の縁取りは前回の設定「{style}」を引き継ぎました")

    density = prefs.get("caption_density", {}).get("value")
    if density in ("minimal", "low", "medium", "high"):
        directive.subtitle.density = density
        directive.subtitle.coverage = {
            "minimal": 0.3, "low": 0.5, "medium": 0.72, "high": 0.92
        }[density]
        notes.append(f"テロップ量は前回の設定「{density}」を引き継ぎました")

    appetite = prefs.get("transition_appetite", {}).get("value")
    if isinstance(appetite, (int, float)):
        directive.transitions.max_ratio = round(
            max(0.0, min(directive.transitions.max_ratio, float(appetite))), 2
        )
        notes.append("画面切り替えの量は前回の設定を引き継ぎました")

    volume = prefs.get("bgm_volume", {}).get("value")
    if isinstance(volume, (int, float)) and 0.0 <= float(volume) <= 2.0:
        directive.audio.bgm_volume = float(volume)
        notes.append(f"BGM音量は前回の設定（x{float(volume):.2f}）を引き継ぎました")

    return notes


# ------------------------------------------------------------ recording


def record_production(
    *,
    font_family: str = "",
    music_name: str = "",
    color_grade: str = "",
    edit_style: str = "",
    subtitle_size: int | None = None,
    subtitle_position: str = "",
    transition_ratio: float | None = None,
    title: str = "",
    score: float | None = None,
) -> None:
    """Files one finished production into the memory.

    Called from the pipeline's completion, after the review has settled,
    so what is remembered is what the user actually ended up with rather
    than an intermediate iteration.

    Note what this does *not* do: it never writes into `preferences`. What
    Kairo chose is variety data; only what the user changed is a
    preference. Conflating the two is how an automatic system starts
    reinforcing its own habits.
    """
    with _lock:
        data = load()
        data["recent_fonts"] = _push(data.get("recent_fonts", []), font_family)
        data["recent_music"] = _push(data.get("recent_music", []), music_name)
        data["recent_grades"] = _push(data.get("recent_grades", []), color_grade)
        data["recent_styles"] = _push(data.get("recent_styles", []), edit_style)
        entry = {
            "at": _now(),
            "title": title,
            "edit_style": edit_style,
            "font": font_family,
            "music": music_name,
            "color_grade": color_grade,
            "subtitle_size": subtitle_size,
            "subtitle_position": subtitle_position,
            "transition_ratio": transition_ratio,
            "score": score,
        }
        history = [entry] + list(data.get("history", []))
        data["history"] = history[:HISTORY_LIMIT * 3]
        _save(data)


def summary() -> dict:
    """What the memory holds, for the Settings screen.

    Includes the counts a user needs to judge whether the memory is worth
    keeping, and the tendencies it has actually observed - stated as
    frequencies, never as "your favourite", because a count of three is not
    a preference.
    """
    data = load()
    history = list(data.get("history") or [])

    def tally(field: str) -> list[dict]:
        counts: dict[str, int] = {}
        for row in history:
            value = row.get(field)
            if value:
                counts[str(value)] = counts.get(str(value), 0) + 1
        return [
            {"value": k, "count": v}
            for k, v in sorted(counts.items(), key=lambda kv: -kv[1])
        ][:5]

    return {
        "enabled": True,
        "path": str(MEMORY_PATH),
        "exists": MEMORY_PATH.exists(),
        "production_count": len(history),
        "updated_at": data.get("updated_at"),
        "preferences": preferences(),
        "recent_fonts": list(data.get("recent_fonts") or [])[:RECENT_FONT_WINDOW],
        "tendencies": {
            "font": tally("font"),
            "edit_style": tally("edit_style"),
            "color_grade": tally("color_grade"),
            "music": tally("music"),
        },
    }


def clear() -> None:
    with _lock:
        if MEMORY_PATH.exists():
            MEMORY_PATH.unlink()
