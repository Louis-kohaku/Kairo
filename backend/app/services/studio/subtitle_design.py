"""Captions as design, not as text (requirement 4).

`assembly_service.compose_cues` decides *what* each caption says and when.
This module decides what it looks like: which words are enlarged, how it
enters, where it sits, how tightly it is set, and - for the styles that
want it - which cue gets a different treatment entirely.

The output is one `CueDesign` per cue, stored on the cue row and turned
into per-line ASS override tags by `subtitle_style.build_ass`. Keeping the
design as data rather than as ASS means the UI can show it, the review can
score it, and a re-render produces exactly the same captions.

Two rules from the brief shape it:

* **Caption volume follows the style.** A Vlog does not caption every beat;
  a tutorial captions nearly all of them. So the design stage is also
  allowed to *drop* captions, and it drops the ones that add least - a
  caption that only restates the picture.
* **Emphasis is per word, not per caption.** Enlarging a whole line just
  makes the line bigger. Kinetic typography means the one word that carries
  the beat is set larger and heavier than the words around it, which is
  what ASS's inline override tags express.
"""
from __future__ import annotations

import json
import logging
import re

from app.schemas.edit_style import CueDesign, EditDirective, SubtitleDesignPlan

logger = logging.getLogger(__name__)

# Words that carry a beat and are worth enlarging: numbers, superlatives,
# and the short interjections short-form leans on. Deliberately a small,
# literal list - an emphasis detector that fires on every noun produces a
# caption where everything is emphasised, which is a caption where nothing
# is.
_EMPHASIS_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\d+(?:\.\d+)?(?:円|人|分|秒|時間|日|年|回|%|％|倍|位|個|kg|km|m|cm)?"),
    re.compile(
        r"(最高|最強|最悪|最大|最小|一番|絶対|超|激|神|ヤバ|やば|まさか|なんと|"
        r"実は|ついに|初めて|唯一|必見|注意|衝撃|本当|マジ|感動|完璧|無料)"
    ),
    re.compile(r"[A-Za-z]{3,}"),
)

# Captions whose text adds nothing beyond what the picture already shows.
# Dropped first when the style's coverage budget is exceeded.
_LOW_VALUE = re.compile(r"^(そして|それから|次に|さらに|また|こうして|というわけで)[。、]?$")


def _emphasis_words(text: str, limit: int = 2) -> list[str]:
    """The words in this caption worth setting larger.

    At most `limit`, because emphasis is a contrast effect: three enlarged
    words in a fourteen-character line is just a ragged line.
    """
    found: list[str] = []
    for pattern in _EMPHASIS_PATTERNS:
        for match in pattern.finditer(text):
            word = match.group(0).strip()
            if len(word) < 1 or word in found:
                continue
            found.append(word)
            if len(found) >= limit:
                return found
    return found


def _caption_value(text: str, index: int, total: int) -> float:
    """How much this caption earns its place, 0.0-1.0.

    Used only when the style's coverage budget forces some captions to be
    dropped. The opening and the closing caption are always worth keeping;
    a connective with no content is worth least.
    """
    stripped = text.strip()
    if not stripped:
        return 0.0
    if index == 0 or index == total - 1:
        return 1.0
    if _LOW_VALUE.match(stripped):
        return 0.1
    value = 0.5
    if _emphasis_words(stripped, limit=1):
        value += 0.3
    # A very short caption is usually a beat marker and reads fast; a very
    # long one is doing real work.
    if len(stripped) >= 8:
        value += 0.15
    return min(1.0, value)


def design(
    cues: list,
    directive: EditDirective,
    *,
    hook_cue_index: int = 0,
) -> SubtitleDesignPlan:
    """One design per caption, plus the ones that should not be shown.

    `cues` are the SubtitleCue rows in order. Nothing is written here; the
    caller stores the designs and drops the cues the plan marked.
    """
    if not cues:
        return SubtitleDesignPlan(summary="字幕はありません。")

    policy = directive.subtitle
    total = len(cues)
    # How many captions this style wants on screen at all.
    keep_count = max(1, round(total * max(0.05, min(1.0, policy.coverage))))

    valued = sorted(
        (
            (i, _caption_value((cues[i].text or ""), i, total))
            for i in range(total)
        ),
        key=lambda item: (-item[1], item[0]),
    )
    keep = {i for i, _v in valued[:keep_count]}

    designs: list[CueDesign] = []
    for i, cue in enumerate(cues):
        if i not in keep:
            continue
        text = (cue.text or "").strip()
        if not text:
            continue

        size_scale = 1.0
        bold = policy.density in ("medium", "high") or directive.font.impact >= 0.5
        animation = policy.animation
        reasons: list[str] = []

        if i == hook_cue_index:
            # The opening caption is the one the viewer decides on. It gets
            # more size and a harder entrance in the styles that want
            # impact, and is left alone in the ones that do not (a luxury
            # short whose first caption pops is not a luxury short).
            if directive.font.impact >= 0.4:
                size_scale = 1.18
                bold = True
                animation = "pop" if policy.animation != "none" else "none"
                reasons.append("冒頭の字幕は視聴継続を決めるため、大きく強く出します")
            else:
                reasons.append("冒頭の字幕ですが、このスタイルでは強調しません")

        emphasis = _emphasis_words(text) if policy.emphasis else []
        if emphasis:
            reasons.append("強調語: " + "・".join(emphasis))

        if not reasons:
            reasons.append(f"{directive.style_label}の字幕方針どおり")

        designs.append(
            CueDesign(
                index=i,
                text=text,
                start=float(getattr(cue, "start", 0.0) or 0.0),
                end=float(getattr(cue, "end", 0.0) or 0.0),
                size_scale=round(size_scale, 3),
                bold=bold,
                position=policy.position,
                style=policy.style,
                animation=animation,
                letter_spacing=policy.letter_spacing,
                line_spacing=policy.line_spacing,
                emphasis=emphasis,
                reason=" / ".join(reasons),
            )
        )

    dropped = total - len(designs)
    if dropped:
        summary = (
            f"{total}件の字幕のうち{len(designs)}件を表示します"
            f"（{directive.style_label}は字幕量「{policy.density}」のため、"
            f"内容の薄い{dropped}件は出しません）"
        )
    else:
        summary = f"{len(designs)}件すべての字幕を表示します（字幕量「{policy.density}」）"

    return SubtitleDesignPlan(cues=designs, dropped=dropped, summary=summary)


def apply(db, cues: list, plan: SubtitleDesignPlan) -> int:
    """Writes the designs onto the cue rows and deletes the dropped ones.

    Returns how many cues remain. Deleting rather than hiding is
    deliberate: the cue list is what the render burns, what the preview
    shows and what the SRT export contains, and three different definitions
    of "which captions exist" is how they drift apart.
    """
    by_index = {d.index: d for d in plan.cues}
    remaining = 0
    for i, cue in enumerate(cues):
        design_for_cue = by_index.get(i)
        if design_for_cue is None:
            db.delete(cue)
            continue
        cue.design_json = json.dumps(design_for_cue.model_dump(), ensure_ascii=False)
        remaining += 1
    db.commit()
    return remaining


def load(cue) -> CueDesign | None:
    raw = getattr(cue, "design_json", None)
    if not raw:
        return None
    try:
        return CueDesign.model_validate(json.loads(raw))
    except Exception:  # noqa: BLE001 - a cue with an unreadable design is
        # simply rendered in the project-wide style, which is correct.
        return None


def to_json(plan: SubtitleDesignPlan) -> str:
    return json.dumps(plan.model_dump(), ensure_ascii=False)


def from_json(raw: str | None) -> SubtitleDesignPlan | None:
    if not raw:
        return None
    try:
        return SubtitleDesignPlan.model_validate(json.loads(raw))
    except Exception:  # noqa: BLE001
        return None
