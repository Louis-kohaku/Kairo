"""The always-available visual engine: composes a scene's key frame from
its design (emotion, camera, visual type, prompt) using Pillow.

Why this exists. Section 23 requires that a user with no footage can still
get a finished video, and section 45 requires a real, playable MP4 at the
end. A diffusion model can do neither reliably here: on this CPU-only
target a single 512px image is minutes of work, and the weights are a
multi-gigabyte download Kairo is not allowed to start on its own
(section 12). So the default path produces composed, designed frames -
palette, light, depth, particles and typography chosen from the scene's
own emotion and content - in tens of milliseconds, with nothing to
install.

It is never presented as AI image generation. `display_name` and the model
plan both say what it is, because section 8's rule is that Kairo does not
pretend (see also `capabilities.notes`). A downloaded diffusion engine can
take over per scene when one is available; this is the floor, not the
ceiling.
"""
from __future__ import annotations

import colorsys
import hashlib
import math
import random
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# Fonts installed with Windows/Japanese locales, best first. Resolved once
# and cached; a missing font is not fatal (Pillow's default bitmap font is
# used, which still renders, just plainly).
_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\YuGothB.ttc",
    r"C:\Windows\Fonts\YuGothM.ttc",
    r"C:\Windows\Fonts\meiryob.ttc",
    r"C:\Windows\Fonts\meiryo.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
)

_font_path_cache: str | None | bool = False


def font_path() -> str | None:
    global _font_path_cache
    if _font_path_cache is not False:
        return _font_path_cache  # type: ignore[return-value]
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            _font_path_cache = candidate
            return candidate
    _font_path_cache = None
    return None


def load_font(size: int) -> ImageFont.ImageFont:
    path = font_path()
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


# --------------------------------------------------------------- palettes
#
# Keyed on the feeling a scene is going for. The script stage is asked for
# an `emotion` per scene precisely so this lookup has something real to
# work from instead of hashing the narration and hoping.


@dataclass(frozen=True)
class Palette:
    top: tuple[int, int, int]
    bottom: tuple[int, int, int]
    glow: tuple[int, int, int]
    accent: tuple[int, int, int]
    particle: tuple[int, int, int]


_PALETTES: dict[str, Palette] = {
    "wonder": Palette((28, 42, 84), (12, 16, 36), (120, 170, 255), (255, 236, 190), (226, 240, 255)),
    "calm": Palette((36, 58, 74), (14, 22, 30), (110, 190, 200), (200, 235, 235), (220, 240, 245)),
    "joy": Palette((92, 58, 30), (30, 18, 14), (255, 186, 96), (255, 226, 150), (255, 240, 205)),
    "surprise": Palette((64, 30, 82), (18, 12, 30), (198, 120, 255), (255, 226, 120), (240, 220, 255)),
    "funny": Palette((96, 66, 24), (28, 20, 12), (255, 206, 92), (255, 244, 170), (255, 248, 220)),
    "tension": Palette((70, 24, 30), (18, 10, 14), (255, 96, 96), (255, 190, 150), (255, 220, 210)),
    "sad": Palette((32, 40, 62), (10, 12, 22), (110, 130, 190), (180, 200, 240), (205, 218, 245)),
    "cool": Palette((22, 48, 70), (8, 14, 24), (90, 180, 230), (190, 230, 255), (225, 245, 255)),
    "warm": Palette((88, 48, 34), (26, 14, 12), (255, 160, 96), (255, 214, 160), (255, 236, 210)),
    "neutral": Palette((40, 46, 58), (14, 16, 22), (130, 150, 190), (210, 220, 240), (230, 236, 248)),
}

# Japanese and English cues the script realistically produces, mapped onto
# the palettes above.
_EMOTION_ALIASES: dict[str, str] = {
    "驚き": "surprise", "びっくり": "surprise", "衝撃": "surprise", "surprise": "surprise",
    "感動": "wonder", "неожид": "surprise", "wonder": "wonder", "好奇心": "wonder", "期待": "wonder",
    "かわいい": "joy", "可愛い": "joy", "嬉しい": "joy", "喜び": "joy", "楽しい": "joy", "joy": "joy",
    "幸せ": "joy", "しあわせ": "joy", "満足": "joy", "happy": "joy", "元気": "joy",
    "興奮": "surprise", "わくわく": "wonder", "ワクワク": "wonder", "excited": "surprise",
    "夢中": "wonder", "発見": "wonder", "はじめて": "wonder", "初めて": "wonder",
    "安心": "calm", "眠": "calm", "うとうと": "calm", "リラックス": "calm",
    "笑い": "funny", "面白": "funny", "ユーモア": "funny", "funny": "funny", "コミカル": "funny",
    "穏やか": "calm", "静か": "calm", "落ち着": "calm", "calm": "calm", "癒し": "calm",
    "緊張": "tension", "不安": "tension", "焦り": "tension", "tension": "tension",
    "悲し": "sad", "切な": "sad", "sad": "sad", "寂し": "sad",
    "寒": "cool", "雪": "cool", "冬": "cool", "cold": "cool", "snow": "cool", "winter": "cool",
    "暖か": "warm", "夕": "warm", "warm": "warm", "sunset": "warm", "秋": "warm",
}


def resolve_palette(emotion: str, extra_text: str = "") -> Palette:
    haystack = f"{emotion} {extra_text}".lower()
    for cue, key in _EMOTION_ALIASES.items():
        if cue.lower() in haystack:
            return _PALETTES[key]
    return _PALETTES["neutral"]


# Particle systems, chosen from what the scene is actually about.
_PARTICLE_CUES: dict[str, str] = {
    "雪": "snow", "snow": "snow", "冬": "snow", "winter": "snow",
    "雨": "rain", "rain": "rain",
    "光": "bokeh", "きらきら": "bokeh", "キラキラ": "bokeh", "sparkle": "bokeh", "星": "bokeh",
    "花": "petal", "桜": "petal", "petal": "petal",
    "煙": "dust", "埃": "dust", "dust": "dust", "砂": "dust",
}


def resolve_particles(text: str) -> str:
    low = text.lower()
    for cue, kind in _PARTICLE_CUES.items():
        if cue.lower() in low:
            return kind
    return "bokeh"


def _seed_of(*parts: str) -> int:
    digest = hashlib.sha256("||".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _vertical_gradient(width: int, height: int, top: tuple, bottom: tuple) -> Image.Image:
    """Drawn at 1px wide and stretched: filling every row of a tall image
    individually is the single slowest thing this module could do, and the
    result is identical."""
    strip = Image.new("RGB", (1, height))
    px = strip.load()
    for y in range(height):
        t = y / max(1, height - 1)
        # Eased so the horizon sits lower than a linear ramp puts it,
        # which reads as light falling from above rather than as a swatch.
        e = t * t * (3 - 2 * t)
        px[0, y] = (
            int(_lerp(top[0], bottom[0], e)),
            int(_lerp(top[1], bottom[1], e)),
            int(_lerp(top[2], bottom[2], e)),
        )
    return strip.resize((width, height), Image.BILINEAR)


def _radial_glow(
    width: int, height: int, cx: float, cy: float, radius: float, color: tuple, strength: float
) -> Image.Image:
    """A soft light source. Built small and upscaled - a full-resolution
    per-pixel falloff costs ~100x more for no visible difference once it's
    blurred."""
    small_w, small_h = max(24, width // 8), max(24, height // 8)
    layer = Image.new("L", (small_w, small_h), 0)
    draw = ImageDraw.Draw(layer)
    r = radius / 8
    steps = 26
    for i in range(steps, 0, -1):
        t = i / steps
        rr = r * t
        value = int(255 * strength * (1 - t) ** 1.6)
        draw.ellipse(
            [cx / 8 - rr, cy / 8 - rr, cx / 8 + rr, cy / 8 + rr],
            fill=max(0, min(255, value)),
        )
    layer = layer.filter(ImageFilter.GaussianBlur(radius=small_w / 18))
    layer = layer.resize((width, height), Image.BILINEAR)

    tint = Image.new("RGB", (width, height), color)
    out = Image.new("RGB", (width, height), (0, 0, 0))
    out.paste(tint, (0, 0), layer)
    return out


def _add(base: Image.Image, layer: Image.Image) -> Image.Image:
    from PIL import ImageChops

    return ImageChops.add(base, layer)


def _draw_particles(
    img: Image.Image, kind: str, palette: Palette, rng: random.Random, intensity: float
) -> None:
    width, height = img.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    unit = max(width, height)

    if kind == "snow":
        count = int(90 * intensity)
        for _ in range(count):
            x, y = rng.uniform(0, width), rng.uniform(0, height)
            r = rng.uniform(unit * 0.0015, unit * 0.006)
            alpha = int(rng.uniform(90, 235))
            draw.ellipse([x - r, y - r, x + r, y + r], fill=(*palette.particle, alpha))
    elif kind == "rain":
        count = int(70 * intensity)
        for _ in range(count):
            x, y = rng.uniform(0, width), rng.uniform(0, height)
            length = rng.uniform(unit * 0.02, unit * 0.06)
            draw.line([x, y, x - length * 0.18, y + length], fill=(*palette.particle, 90), width=2)
    elif kind == "petal":
        count = int(45 * intensity)
        for _ in range(count):
            x, y = rng.uniform(0, width), rng.uniform(0, height)
            r = rng.uniform(unit * 0.004, unit * 0.012)
            draw.ellipse([x - r, y - r * 0.6, x + r, y + r * 0.6], fill=(*palette.accent, 120))
    elif kind == "dust":
        count = int(120 * intensity)
        for _ in range(count):
            x, y = rng.uniform(0, width), rng.uniform(0, height)
            r = rng.uniform(unit * 0.0008, unit * 0.0025)
            draw.ellipse([x - r, y - r, x + r, y + r], fill=(*palette.particle, 70))
    else:  # bokeh
        count = int(26 * intensity)
        for _ in range(count):
            x, y = rng.uniform(0, width), rng.uniform(0, height)
            r = rng.uniform(unit * 0.01, unit * 0.05)
            alpha = int(rng.uniform(18, 60))
            draw.ellipse([x - r, y - r, x + r, y + r], fill=(*palette.glow, alpha))

    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=unit * 0.0012))
    img.alpha_composite(overlay) if img.mode == "RGBA" else img.paste(
        overlay.convert("RGB"), (0, 0), overlay
    )


def _vignette(img: Image.Image, strength: float = 0.55) -> None:
    width, height = img.size
    small_w, small_h = max(16, width // 10), max(16, height // 10)
    mask = Image.new("L", (small_w, small_h), 0)
    draw = ImageDraw.Draw(mask)
    margin_x, margin_y = small_w * 0.06, small_h * 0.06
    draw.ellipse([margin_x, margin_y, small_w - margin_x, small_h - margin_y], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=small_w / 6))
    mask = mask.resize((width, height), Image.BILINEAR)

    dark = Image.new("RGB", (width, height), (0, 0, 0))
    faded = Image.blend(dark, img.convert("RGB"), 1.0 - strength)
    img.paste(Image.composite(img.convert("RGB"), faded, mask), (0, 0))


def _grain(img: Image.Image, rng: random.Random, amount: int = 7) -> None:
    """A little sensor noise. Flat digital gradients read as "unfinished
    graphic"; a touch of grain reads as photographed."""
    width, height = img.size
    small = Image.new("L", (max(8, width // 3), max(8, height // 3)))
    small.putdata([128 + rng.randint(-amount, amount) for _ in range(small.width * small.height)])
    noise = small.resize((width, height), Image.BILINEAR).convert("RGB")
    img.paste(Image.blend(img.convert("RGB"), noise, 0.05), (0, 0))


# ------------------------------------------------------------- composition
#
# A gradient with particles on it is a mood, not a shot. These give each
# frame some structure - a horizon, a light shaft, a framing edge - and the
# layout is picked from the scene index so consecutive scenes in one video
# don't all look like the same wallpaper. That variety is most of what
# separates "designed motion graphics" from "a coloured background".

LAYOUTS = ("glow_center", "horizon", "shaft", "arc", "low_light", "frame", "split")


def _layout_for(index: int, rng: random.Random) -> str:
    # Index-driven rather than random so re-rendering one scene keeps its
    # look, and so a run cycles through layouts instead of repeating one.
    return LAYOUTS[(index * 3 + rng.randint(0, 1)) % len(LAYOUTS)]


def _draw_horizon(img: Image.Image, palette: Palette, rng: random.Random) -> None:
    """Two soft silhouette bands. Reads as ground/landscape depth."""
    width, height = img.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    base_y = height * rng.uniform(0.62, 0.74)
    for layer in range(2):
        y = base_y + layer * height * 0.06
        amp = height * (0.035 - layer * 0.012)
        alpha = 150 + layer * 60
        points = [(0, height), (0, y)]
        steps = 14
        phase = rng.uniform(0, math.pi * 2)
        for i in range(steps + 1):
            x = width * i / steps
            points.append((x, y - math.sin(phase + i * 0.7) * amp))
        points += [(width, y), (width, height)]
        draw.polygon(points, fill=(0, 0, 0, alpha))
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=max(width, height) * 0.004))
    img.paste(overlay.convert("RGB"), (0, 0), overlay)


def _draw_shaft(img: Image.Image, palette: Palette, rng: random.Random) -> None:
    """A diagonal light shaft, as if coming through a window."""
    width, height = img.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    top_x = width * rng.uniform(0.15, 0.55)
    spread = width * rng.uniform(0.22, 0.42)
    drift = width * rng.uniform(0.1, 0.3)
    for i in range(3):
        offset = i * spread * 0.28
        draw.polygon(
            [
                (top_x + offset, -10),
                (top_x + offset + spread * 0.5, -10),
                (top_x + offset + spread * 0.5 + drift, height + 10),
                (top_x + offset + drift, height + 10),
            ],
            fill=(*palette.glow, 26),
        )
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=max(width, height) * 0.02))
    img.paste(overlay.convert("RGB"), (0, 0), overlay)


def _draw_arc(img: Image.Image, palette: Palette, rng: random.Random) -> None:
    """Concentric rings around the focal point - draws the eye inward."""
    width, height = img.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    cx, cy = width * rng.uniform(0.4, 0.6), height * rng.uniform(0.34, 0.46)
    for i in range(4):
        r = max(width, height) * (0.12 + i * 0.11)
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            outline=(*palette.accent, 40 - i * 7),
            width=max(2, int(width * 0.004)),
        )
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=max(width, height) * 0.006))
    img.paste(overlay.convert("RGB"), (0, 0), overlay)


def _draw_frame_edges(img: Image.Image, palette: Palette, rng: random.Random) -> None:
    """A soft inner border - a framing device that makes the shot feel
    composed rather than cropped."""
    width, height = img.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    inset_x, inset_y = width * 0.07, height * 0.05
    draw.rounded_rectangle(
        [inset_x, inset_y, width - inset_x, height - inset_y],
        radius=int(width * 0.04),
        outline=(*palette.accent, 55),
        width=max(2, int(width * 0.003)),
    )
    img.paste(overlay.convert("RGB"), (0, 0), overlay)


def _draw_split(img: Image.Image, palette: Palette, rng: random.Random) -> None:
    """A diagonal tonal split - strong graphic separation for beat changes."""
    width, height = img.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    y1 = height * rng.uniform(0.3, 0.5)
    y2 = height * rng.uniform(0.5, 0.72)
    draw.polygon([(0, y1), (width, y2), (width, height), (0, height)], fill=(0, 0, 0, 90))
    draw.line([(0, y1), (width, y2)], fill=(*palette.accent, 90), width=max(2, int(width * 0.0035)))
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=max(width, height) * 0.003))
    img.paste(overlay.convert("RGB"), (0, 0), overlay)


def _apply_layout(img: Image.Image, layout: str, palette: Palette, rng: random.Random) -> None:
    if layout == "horizon":
        _draw_horizon(img, palette, rng)
    elif layout == "shaft":
        _draw_shaft(img, palette, rng)
    elif layout == "arc":
        _draw_arc(img, palette, rng)
    elif layout == "frame":
        _draw_frame_edges(img, palette, rng)
    elif layout == "split":
        _draw_split(img, palette, rng)
    elif layout == "low_light":
        _draw_horizon(img, palette, rng)
        _draw_shaft(img, palette, rng)
    # "glow_center" is the bare gradient + glow already composed by the
    # caller, kept as a deliberate breather between busier frames.


def _wrap_text(text: str, font: ImageFont.ImageFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    """Character-wise wrapping, because Japanese has no spaces to break on
    and word-wrapping a Japanese caption produces one enormous line."""
    lines: list[str] = []
    current = ""
    for ch in text:
        if ch == "\n":
            lines.append(current)
            current = ""
            continue
        trial = current + ch
        if draw.textlength(trial, font=font) > max_width and current:
            lines.append(current)
            current = ch
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def _draw_caption(
    img: Image.Image, text: str, palette: Palette, *, emphasis: bool
) -> None:
    """Typography for scenes whose *content is the words* (text_animation,
    and the title/ending cards). Regular captions are burned in later by
    the subtitle pass instead, so they stay editable."""
    if not text.strip():
        return
    width, height = img.size
    draw = ImageDraw.Draw(img)
    size = int(width * (0.115 if emphasis else 0.085))
    font = load_font(size)
    max_width = int(width * 0.82)
    lines = _wrap_text(text.strip(), font, max_width, draw)[:4]

    line_h = size * 1.32
    total_h = line_h * len(lines)
    y = (height - total_h) / 2

    for line in lines:
        w = draw.textlength(line, font=font)
        x = (width - w) / 2
        # Halo first, then the glyph: keeps text legible over any
        # background without a box, which is what short-form titles do.
        for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3), (-2, -2), (2, 2), (-2, 2), (2, -2)):
            draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=palette.accent if emphasis else (255, 255, 255))
        y += line_h


def _draw_bars(img: Image.Image, palette: Palette, rng: random.Random, labels: list[str]) -> None:
    """A minimal chart for `chart`/`diagram` scenes. Deliberately abstract:
    inventing precise-looking numbers the script never produced would be a
    fabricated fact on screen."""
    width, height = img.size
    draw = ImageDraw.Draw(img)
    n = max(3, min(6, len(labels) or 4))
    area_w = width * 0.66
    area_h = height * 0.34
    x0 = (width - area_w) / 2
    y1 = height * 0.62
    gap = area_w / (n * 1.7)
    bar_w = (area_w - gap * (n - 1)) / n

    for i in range(n):
        h = area_h * (0.35 + 0.65 * ((i + 1) / n) * rng.uniform(0.7, 1.0))
        x = x0 + i * (bar_w + gap)
        draw.rounded_rectangle(
            [x, y1 - h, x + bar_w, y1],
            radius=int(bar_w * 0.18),
            fill=palette.glow if i < n - 1 else palette.accent,
        )
    draw.line([x0 - 8, y1, x0 + area_w + 8, y1], fill=(255, 255, 255), width=3)


@dataclass
class SceneVisualSpec:
    """Everything the renderer needs about one scene, already resolved by
    the caller so this module never has to reach into the database."""

    index: int
    visual_type: str
    visual_prompt: str
    emotion: str = ""
    camera: str = ""
    caption: str = ""
    title: str = ""
    seed_text: str = ""


def render_scene_image(spec: SceneVisualSpec, width: int, height: int, dest: Path) -> Path:
    """Composes and writes one scene key frame as a PNG."""
    seed = _seed_of(spec.seed_text or spec.visual_prompt, str(spec.index), spec.emotion)
    rng = random.Random(seed)

    palette = resolve_palette(spec.emotion, f"{spec.visual_prompt} {spec.title}")

    # A whole video's worth of scenes routinely lands on one palette - a
    # short about a surprised cat is "驚き" from beginning to end - and a
    # random ±0.035 hue jitter was far too small to see, so the result read
    # as nineteen copies of the same purple frame.
    #
    # The shift is therefore driven by the scene index, sweeping a visible
    # arc through the palette's neighbourhood: adjacent scenes differ
    # clearly, the video moves through a progression rather than sitting on
    # one colour, and re-rendering scene 7 still reproduces scene 7 exactly.
    sweep = ((spec.index % 6) - 2.5) / 2.5  # -1.0 .. +1.0 over six scenes
    shift = sweep * 0.075 + rng.uniform(-0.012, 0.012)
    # Alternating tonal weight stops consecutive scenes reading as one
    # continuous shot even when their hues are close.
    lift = 1.0 + sweep * 0.14

    def nudge(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
        h, l, s = colorsys.rgb_to_hls(*[c / 255 for c in rgb])
        l = max(0.02, min(0.96, l * lift))
        s = max(0.0, min(1.0, s * (1.0 + sweep * 0.10)))
        r, g, b = colorsys.hls_to_rgb((h + shift) % 1.0, l, s)
        return (int(r * 255), int(g * 255), int(b * 255))

    base = _vertical_gradient(width, height, nudge(palette.top), nudge(palette.bottom))

    # One or two light sources, placed off-centre on a third.
    for _ in range(rng.choice([1, 1, 2])):
        cx = width * rng.choice([0.32, 0.5, 0.68])
        cy = height * rng.uniform(0.22, 0.45)
        radius = max(width, height) * rng.uniform(0.45, 0.85)
        base = _add(
            base,
            _radial_glow(width, height, cx, cy, radius, nudge(palette.glow), rng.uniform(0.35, 0.6)),
        )

    img = base.convert("RGB")

    layout = _layout_for(spec.index, rng)
    _apply_layout(img, layout, palette, rng)

    visual_type = spec.visual_type
    if visual_type in ("chart", "diagram"):
        _draw_bars(img, palette, rng, [spec.visual_prompt])
    else:
        _draw_particles(
            img,
            resolve_particles(f"{spec.visual_prompt} {spec.emotion} {spec.title}"),
            palette,
            rng,
            intensity=1.0 if visual_type in ("ai_video", "ai_image", "photo") else 0.5,
        )

    if visual_type in ("text_animation",) or spec.caption:
        _draw_caption(img, spec.caption or spec.visual_prompt, palette, emphasis=True)

    _vignette(img, strength=0.38)
    _grain(img, rng)

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, format="PNG", optimize=True)
    return dest


def render_title_card(text: str, subtitle: str, width: int, height: int, dest: Path, emotion: str = "") -> Path:
    spec = SceneVisualSpec(
        index=0,
        visual_type="text_animation",
        visual_prompt=text,
        emotion=emotion,
        caption=text,
        title=text,
        seed_text=text + subtitle,
    )
    return render_scene_image(spec, width, height, dest)


def is_available() -> bool:
    """Pillow is a hard dependency of this engine and ships with the
    backend requirements, so this is really a guard against a broken
    install rather than an optional feature check."""
    try:
        Image.new("RGB", (2, 2))
        return True
    except Exception:
        return False


# Camera language -> a (zoom start, zoom end, pan) recipe the clip builder
# turns into an ffmpeg zoompan expression. Keeping the mapping here means
# the script's `camera` field has one authoritative interpretation.
CAMERA_MOVES: dict[str, tuple[float, float, str]] = {
    "close-up": (1.06, 1.20, "center"),
    "closeup": (1.06, 1.20, "center"),
    "クローズアップ": (1.06, 1.20, "center"),
    "アップ": (1.06, 1.20, "center"),
    "wide": (1.18, 1.02, "center"),
    "ワイド": (1.18, 1.02, "center"),
    "引き": (1.18, 1.02, "center"),
    "zoom_in": (1.0, 1.18, "center"),
    "ズームイン": (1.0, 1.18, "center"),
    "zoom_out": (1.18, 1.0, "center"),
    "ズームアウト": (1.18, 1.0, "center"),
    "pan_left": (1.12, 1.12, "left"),
    "パン": (1.12, 1.12, "left"),
    "pan_right": (1.12, 1.12, "right"),
    "tilt": (1.12, 1.12, "up"),
    "static": (1.02, 1.06, "center"),
    "固定": (1.02, 1.06, "center"),
}


def resolve_camera(camera: str) -> tuple[float, float, str]:
    low = (camera or "").strip().lower()
    for cue, move in CAMERA_MOVES.items():
        if cue.lower() in low:
            return move
    # A gentle push-in is the safe short-form default: motion holds
    # attention, and a still frame for 3 seconds reads as a stalled video.
    return (1.02, 1.12, "center")


def estimate_render_seconds(width: int, height: int) -> float:
    return max(0.05, (width * height) / 6_000_000)


def describe() -> dict:
    return {
        "id": "procedural",
        "display_name": "Kairo Composer (ローカル合成)",
        "provider": "Kairo Local",
        "needs_download": False,
        "notes": (
            "拡散モデルを使わず、シーンの感情・内容から配色・光・粒子・タイポグラフィを"
            "組み立てて映像素材を生成します。ダウンロード不要で、CPUのみで動作します。"
        ),
    }
