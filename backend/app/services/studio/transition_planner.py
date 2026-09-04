"""Deciding where the picture changes, and where it just cuts.

Requirement 5 states the rule this module implements: a cut is the default,
a transition is used only where something in the video actually changes -
place, time, feeling, act, or a break in the music - and "more effects" is
never the same as "better".

So this is a planner, not a renderer. It reads the scene design and the
edit directive and produces one `TransitionChoice` per boundary, each with
the reason it exists. The renderer (`ffmpeg/engine.build_transition`) only
executes what this decided, and the review can score whether the decisions
were sensible because they are recorded.

How a boundary is judged, in order:

1. **Explicit.** The scene writer asked for one (`Scene.transition`). An
   explicit request is honoured if the style allows that transition.
2. **Meaningful change.** The location, the time of day, the emotion or the
   act changed between the two scenes. Detected from the scene's own
   fields, not guessed - the writer already records purpose, emotion,
   continuity and visual prompt.
3. **Musical.** The boundary lands on a section break in the beat grid.
4. **Otherwise: a cut.**

Then the budget is applied. The directive caps what share of boundaries may
be non-cut, and when more boundaries qualify than the budget allows, the
weakest reasons are dropped first - so an act change keeps its transition
and an incidental location change loses one.
"""
from __future__ import annotations

import logging
import re

from app.schemas.edit_style import (
    TRANSITION_LABELS,
    TRANSITION_REASON_LABELS,
    EditDirective,
    TransitionChoice,
    TransitionPlan,
)

logger = logging.getLogger(__name__)

# How much a reason is worth when the budget forces a choice. An act change
# is a structural break the viewer should feel; a location change often is
# not, because two shots of the same trip in different places is just a
# holiday video.
_REASON_PRIORITY: dict[str, int] = {
    "ending": 90,
    "act_change": 80,
    "time_jump": 70,
    "location_change": 55,
    "emotion_change": 45,
    "music_section": 40,
    "match_subject": 35,
    "opening": 20,
    "none": 0,
}

# Which transition suits which reason, given what the style permits. First
# entry the style allows is used; a style that allows only cuts therefore
# gets cuts, which is a correct outcome rather than a failure.
_REASON_PREFERENCES: dict[str, tuple[str, ...]] = {
    "act_change": ("dip_to_black", "fade", "dissolve"),
    "time_jump": ("dip_to_black", "dissolve", "fade"),
    "location_change": ("dissolve", "slide_left", "zoom", "fade"),
    "emotion_change": ("dissolve", "fade"),
    "music_section": ("zoom", "slide_left", "dissolve"),
    "match_subject": ("match_cut", "dissolve"),
    "ending": ("fade", "dip_to_black", "dissolve"),
    "opening": ("fade",),
}

# Words in a scene's own text that mark a change of place or of time. Kept
# small and literal: an over-eager matcher would find a "time jump" in
# every scene and turn the whole video into dissolves.
_PLACE_WORDS = re.compile(
    r"(移動|着いた|到着|向かう|次は|別の|離れ|出発|入る|入り口|外に|中へ|"
    r"駅|空港|ホテル|部屋|店|海|山|street|arrive|move)"
)
_TIME_WORDS = re.compile(
    r"(翌日|次の日|朝|昼|夕方|夜|深夜|数時間|しばらく|後で|やがて|"
    r"時間が|later|next day|morning|evening|night|sunset|sunrise)"
)


def _scene_text(scene) -> str:
    return " ".join(
        str(getattr(scene, field, "") or "")
        for field in ("purpose", "visual_prompt", "continuity", "subtitle_text", "narration")
    )


def _emotion(scene) -> str:
    return (getattr(scene, "emotion", "") or "").strip().casefold()


def _location_hint(scene) -> str:
    """A crude place signature for a scene, from its visual prompt.

    Two scenes whose prompts share no significant noun are, for our
    purposes, in different places. This is a heuristic and the plan says so
    in the finding's detail rather than asserting the location changed.
    """
    prompt = (getattr(scene, "visual_prompt", "") or "").strip()
    # Japanese has no spaces, so the signature is the set of 2-grams over
    # the non-punctuation characters plus any Latin words.
    cleaned = re.sub(r"[\s、。,.!?！？「」『』()（）]", "", prompt)
    return cleaned[:40].casefold()


def _shares_subject(a: str, b: str) -> bool:
    if not a or not b:
        return False
    grams_a = {a[i : i + 2] for i in range(len(a) - 1)}
    grams_b = {b[i : i + 2] for i in range(len(b) - 1)}
    if not grams_a or not grams_b:
        return False
    overlap = len(grams_a & grams_b) / max(1, min(len(grams_a), len(grams_b)))
    return overlap >= 0.34


def _detect_reason(previous, current, *, is_last: bool, act_boundary: bool) -> tuple[str, str]:
    """Why this boundary might deserve a transition. Returns (reason, detail)."""
    if act_boundary:
        return "act_change", "幕が変わるため"

    text = _scene_text(current)
    if _TIME_WORDS.search(text):
        return "time_jump", "シーンの内容に時間の経過が書かれているため"

    prev_place = _location_hint(previous)
    place = _location_hint(current)
    if _PLACE_WORDS.search(text):
        return "location_change", "シーンの内容に場所の移動が書かれているため"
    if prev_place and place and not _shares_subject(prev_place, place):
        return "location_change", "前後のカットで写るものが大きく変わるため"

    prev_emotion = _emotion(previous)
    emotion = _emotion(current)
    if prev_emotion and emotion and prev_emotion != emotion:
        return "emotion_change", f"感情が「{prev_emotion}」から「{emotion}」に変わるため"

    if prev_place and place and _shares_subject(prev_place, place):
        return "match_subject", "同じ被写体が続くため、つながりを見せられる箇所"

    return "none", ""


def _pick_transition(reason: str, directive: EditDirective) -> str:
    allowed = set(directive.transitions.allowed) | {"cut"}
    for candidate in _REASON_PREFERENCES.get(reason, ()):
        if candidate in allowed:
            return candidate
    # The style's own "strong" mark, if it permits it, else a plain cut.
    if directive.transitions.strong in allowed:
        return directive.transitions.strong
    return "cut"


def _music_boundaries(beat_sync, scene_count: int) -> set[int]:
    """Scene boundaries that fall on a musical section break.

    A section is taken as every eighth beat-group, which is one bar-length
    phrase at the grid the beat sync chose. Empty when there is no usable
    beat grid, which is a normal outcome and not an error.
    """
    if beat_sync is None or not getattr(beat_sync, "applied", False):
        return set()
    per_cut = int(getattr(beat_sync, "beats_per_cut", 0) or 0)
    if per_cut <= 0:
        return set()
    # Every 8 beats is a phrase; how many cuts that is depends on the grid.
    cuts_per_phrase = max(1, round(8 / per_cut))
    return {i for i in range(1, scene_count) if i % cuts_per_phrase == 0}


def plan(
    scenes: list,
    directive: EditDirective,
    *,
    beat_sync=None,
    act_boundaries: set[int] | None = None,
) -> TransitionPlan:
    """One decision per scene boundary, with its reason.

    `act_boundaries` are scene indices where a new chapter starts; the
    pipeline knows them from the chapter rows and they are the strongest
    signal available, so they are passed in rather than re-derived.
    """
    if len(scenes) < 2:
        return TransitionPlan(
            choices=[],
            boundary_count=0,
            summary="カットが1つしかないため、画面切り替えはありません。",
        )

    acts = act_boundaries or set()
    musical = _music_boundaries(beat_sync, len(scenes))
    allowed = set(directive.transitions.allowed) | {"cut"}

    # --- pass 1: what each boundary would want ------------------------
    wanted: list[tuple[int, str, str, str]] = []  # (index, reason, detail, transition)
    for i in range(1, len(scenes)):
        previous, current = scenes[i - 1], scenes[i]

        explicit = (getattr(current, "transition", "") or "").strip().lower()
        # The writer's own vocabulary (planning_service constrains it to
        # cut / fade / quick_cut) plus anything the directive named.
        explicit = {"quick_cut": "cut", "crossfade": "dissolve"}.get(explicit, explicit)
        if explicit and explicit != "cut" and explicit in allowed:
            wanted.append((i, "act_change" if i in acts else "emotion_change",
                           "シーン設計で指定された切り替え", explicit))
            continue

        reason, detail = _detect_reason(
            previous, current, is_last=(i == len(scenes) - 1), act_boundary=(i in acts)
        )
        if reason == "none" and i in musical:
            reason, detail = "music_section", "音楽の区切りに当たるため"
        if reason == "none":
            continue
        transition = _pick_transition(reason, directive)
        if transition == "cut":
            continue
        wanted.append((i, reason, detail, transition))

    # --- pass 2: the budget -------------------------------------------
    boundaries = len(scenes) - 1
    budget = int(boundaries * max(0.0, directive.transitions.max_ratio))
    # A video is allowed at least one transition when its style permits any
    # at all, so a six-cut short can still mark its one real break.
    if directive.transitions.max_ratio > 0 and budget == 0 and boundaries >= 3:
        budget = 1

    wanted.sort(key=lambda item: (-_REASON_PRIORITY.get(item[1], 0), item[0]))
    kept = wanted[:budget]
    dropped = len(wanted) - len(kept)
    kept_by_index = {item[0]: item for item in kept}

    # --- pass 3: the plan ---------------------------------------------
    choices: list[TransitionChoice] = []
    for i in range(1, len(scenes)):
        item = kept_by_index.get(i)
        if item is None:
            choices.append(
                TransitionChoice(
                    index=i,
                    transition="cut",
                    label=TRANSITION_LABELS["cut"],
                    duration=0.0,
                    reason="none",
                    reason_label=TRANSITION_REASON_LABELS["none"],
                    detail="意味のある切れ目ではないため、カットでつなぎます",
                )
            )
            continue
        _index, reason, detail, transition = item
        choices.append(
            TransitionChoice(
                index=i,
                transition=transition,  # type: ignore[arg-type]
                label=TRANSITION_LABELS.get(transition, transition),
                duration=round(directive.transitions.duration, 3),
                reason=reason,  # type: ignore[arg-type]
                reason_label=TRANSITION_REASON_LABELS.get(reason, reason),
                detail=detail,
            )
        )

    non_cut = sum(1 for c in choices if c.transition != "cut")
    if non_cut == 0:
        summary = (
            f"{boundaries}箇所すべてカットでつなぎます"
            f"（{directive.style_label}では切り替えを使う理由のある箇所がありませんでした）"
        )
    else:
        summary = (
            f"{boundaries}箇所のうち{non_cut}箇所だけ画面切り替えを使います"
            f"（上限{budget}箇所）"
        )
        if dropped:
            summary += f"。切り替えの候補が{dropped}箇所ありましたが、多用を避けるため見送りました"

    return TransitionPlan(
        choices=choices,
        non_cut_count=non_cut,
        boundary_count=boundaries,
        summary=summary,
    )


def to_json(plan_result: TransitionPlan) -> str:
    import json

    return json.dumps(plan_result.model_dump(), ensure_ascii=False)


def from_json(raw: str | None) -> TransitionPlan | None:
    if not raw:
        return None
    import json

    try:
        return TransitionPlan.model_validate(json.loads(raw))
    except Exception:  # noqa: BLE001
        return None
