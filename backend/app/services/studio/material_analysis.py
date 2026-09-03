"""Working out what the user actually uploaded.

The material pipeline can only prefer the user's own photos and videos
(design requirement 7) if it knows what is *in* them, and it can only fill
the gaps (requirement 8) if it knows what is missing. That knowledge comes
from here.

Three sources of truth, in descending order of how much they can say:

1. **A vision model**, when LM Studio has one loaded. It is the only thing
   that can look at a photo and say "海・ビーチ・夕日". Its output is
   labelled `analyzed_by="vision_ai"` so the UI can say so.
2. **The pixels themselves**, always available: resolution, orientation,
   brightness, dominant colours, and - for video - how much movement there
   is and which part of the clip is worth cutting from. This is measured,
   not guessed.
3. **The file name**, as a last source of subject tags. "沖縄_海.jpg" says
   something real; "IMG_1023.jpg" does not, and is left alone rather than
   turned into an invented tag.

What this module never does is claim more than it knows. An analysis
produced without a vision model says `metadata` or `metadata+filename`, and
the material list shows that verbatim, because a tag list that looks
AI-derived but was actually scraped off a file name is exactly the kind of
placeholder-as-feature the rest of Kairo avoids.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import tempfile
from pathlib import Path

from app.core.paths import project_dir
from app.models.media_asset import MediaAsset
from app.schemas.material import MaterialAnalysis, UsableRange
from app.services import llm_client, media_service
from app.services.ffmpeg import compose
from app.services.json_extract import JSONExtractionError, parse_json_object

logger = logging.getLogger(__name__)

# Near-black frames. A phone video that starts in a pocket, or ends on a
# hand over the lens, is measurably darker than any real shot.
DARK_THRESHOLD = 0.07
# Below this, consecutive frames are effectively the same picture.
STATIC_THRESHOLD = 0.012

_THUMB_SIZE = (480, 480)
_ANALYSIS_FRAME_COUNT = 5


def _pillow():
    """Pillow, or None when it is not installed.

    Every caller degrades rather than fails: without Pillow a still's
    resolution still comes from ffprobe, only the brightness/colour
    measurements are missing, and the analysis says so.
    """
    try:
        from PIL import Image  # noqa: PLC0415

        return Image
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------ thumbnails


def thumbnails_dir(project_id: str) -> Path:
    d = project_dir(project_id) / "thumbnails"
    d.mkdir(parents=True, exist_ok=True)
    return d


def thumbnail_path(asset: MediaAsset) -> Path:
    return thumbnails_dir(asset.project_id) / f"{asset.id}.jpg"


def ensure_thumbnail(asset: MediaAsset) -> Path | None:
    """A small JPEG preview of the asset, generated once and cached.

    Done on the backend rather than by pointing an <img> at the original:
    a 12MP photo or a 200MB video would otherwise be downloaded in full,
    several times over, just to draw a 96px tile.
    """
    dest = thumbnail_path(asset)
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    src = media_service.asset_path(asset)
    if not src.exists():
        return None

    if asset.kind == "image":
        Image = _pillow()
        if Image is None:
            return None
        try:
            with Image.open(src) as im:
                im = im.convert("RGB")
                im.thumbnail(_THUMB_SIZE)
                im.save(dest, "JPEG", quality=82)
            return dest
        except Exception:
            logger.exception("Thumbnail failed for image %s", asset.id)
            return None

    if asset.kind == "video":
        at = min(1.0, max(0.0, (asset.duration or 0.0) * 0.1))
        tmp = Path(tempfile.mkdtemp(prefix="kairo_thumb_"))
        try:
            frames = compose.extract_frames(src, tmp, [at], width=_THUMB_SIZE[0])
            if not frames:
                return None
            shutil.copyfile(frames[0], dest)
            return dest
        except Exception:
            logger.exception("Thumbnail failed for video %s", asset.id)
            return None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    return None


# --------------------------------------------------------- pixel measures


def _measure_image(path: Path) -> dict:
    """Brightness and dominant colours of one still, from its pixels."""
    Image = _pillow()
    if Image is None:
        return {}
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            width, height = im.size
            small = im.copy()
            small.thumbnail((64, 64))
            pixels = list(small.getdata())
            if not pixels:
                return {"width": width, "height": height}
            luminance = sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b in pixels)
            brightness = luminance / (len(pixels) * 255.0)

            quantized = small.convert("P", palette=Image.Palette.ADAPTIVE, colors=5)
            palette = quantized.getpalette() or []
            counts = sorted(quantized.getcolors() or [], reverse=True)
            colors = []
            for _count, index in counts[:3]:
                base = index * 3
                if base + 2 < len(palette):
                    colors.append(
                        "#%02x%02x%02x" % (palette[base], palette[base + 1], palette[base + 2])
                    )
            return {
                "width": width,
                "height": height,
                "brightness": round(brightness, 3),
                "colors": colors,
            }
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"画像を解析できませんでした: {exc}") from exc


def _gray_signature(path: Path) -> list[int] | None:
    Image = _pillow()
    if Image is None:
        return None
    try:
        with Image.open(path) as im:
            small = im.convert("L").resize((32, 32))
            return list(small.getdata())
    except Exception:
        return None


def _measure_video(path: Path, duration: float) -> dict:
    """Brightness, movement and the usable interval of a video.

    Sampled rather than exhaustive: five frames spread across the clip are
    enough to tell a static dark shot from a bright moving one, and cheap
    enough that analysing ten videos does not become its own phase.
    """
    duration = max(0.1, duration)
    stamps = [duration * f for f in (0.05, 0.25, 0.5, 0.75, 0.95)][:_ANALYSIS_FRAME_COUNT]
    tmp = Path(tempfile.mkdtemp(prefix="kairo_analysis_"))
    try:
        frames = compose.extract_frames(path, tmp, stamps, width=320)
        if not frames:
            # Nothing decodable. The caller still cleans up, so the working
            # directory is handed back rather than leaked.
            return {"frames": [], "keep_dir": tmp}

        brightnesses: list[float] = []
        signatures: list[list[int] | None] = []
        for frame in frames:
            measured = _measure_image(frame)
            brightnesses.append(float(measured.get("brightness") or 0.0))
            signatures.append(_gray_signature(frame))

        motion = 0.0
        pairs = 0
        for a, b in zip(signatures, signatures[1:]):
            if a is None or b is None:
                continue
            diff = sum(abs(x - y) for x, y in zip(a, b)) / (len(a) * 255.0)
            motion += diff
            pairs += 1
        motion = motion / pairs if pairs else 0.0

        # The usable interval: drop dark sample windows at either end. Only
        # the ends, because a dark middle is a cut in the footage, not
        # something to skip past.
        step = duration / max(1, len(brightnesses))
        start_index = 0
        while start_index < len(brightnesses) - 1 and brightnesses[start_index] < DARK_THRESHOLD:
            start_index += 1
        end_index = len(brightnesses) - 1
        while end_index > start_index and brightnesses[end_index] < DARK_THRESHOLD:
            end_index -= 1

        usable_start = round(step * start_index, 2) if start_index else 0.0
        usable_end = (
            round(min(duration, step * (end_index + 1)), 2)
            if end_index < len(brightnesses) - 1
            else round(duration, 2)
        )
        reason = ""
        if usable_start > 0.0 or usable_end < round(duration, 2):
            reason = "暗い部分を除いた区間です"

        colors: list[str] = []
        mid = _measure_image(frames[len(frames) // 2])
        colors = mid.get("colors") or []

        return {
            "frames": frames,
            "brightness": round(sum(brightnesses) / len(brightnesses), 3),
            "motion": round(min(1.0, motion * 4), 3),
            "usable": UsableRange(start=usable_start, end=usable_end, reason=reason),
            "colors": colors,
            "representative": frames[len(frames) // 2],
            "keep_dir": tmp,
        }
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


# ------------------------------------------------------------ file names


# Words that appear in file names and mean something about the content.
# Deliberately small and explicit: a lookup table that says 海 when it sees
# "umi" is honest, a fuzzy matcher that turns "IMG" into a subject is not.
_FILENAME_TAGS: dict[str, tuple[str, ...]] = {
    "海": ("海", "水"),
    "umi": ("海",),
    "sea": ("海",),
    "ocean": ("海",),
    "beach": ("ビーチ", "海"),
    "ビーチ": ("ビーチ", "海"),
    "空": ("空",),
    "sky": ("空",),
    "sunset": ("夕日", "空"),
    "夕日": ("夕日", "空"),
    "夕焼け": ("夕日", "空"),
    "sunrise": ("朝日", "空"),
    "flight": ("飛行機",),
    "plane": ("飛行機",),
    "airplane": ("飛行機",),
    "飛行機": ("飛行機",),
    "airport": ("空港", "飛行機"),
    "空港": ("空港",),
    "food": ("食事",),
    "lunch": ("食事",),
    "dinner": ("食事",),
    "食事": ("食事",),
    "cafe": ("カフェ", "食事"),
    "hotel": ("ホテル", "建物"),
    "building": ("建物",),
    "街": ("街", "建物"),
    "city": ("街", "建物"),
    "swing": ("ブランコ",),
    "ブランコ": ("ブランコ",),
    "山": ("山",),
    "mountain": ("山",),
    "川": ("川", "水"),
    "river": ("川", "水"),
    "花": ("花",),
    "flower": ("花",),
    "夜": ("夜景", "夜"),
    "night": ("夜景", "夜"),
    "沖縄": ("沖縄",),
    "okinawa": ("沖縄",),
    "旅行": ("旅行",),
    "travel": ("旅行",),
    "trip": ("旅行",),
    "猫": ("猫", "動物"),
    "cat": ("猫", "動物"),
    "犬": ("犬", "動物"),
    "dog": ("犬", "動物"),
    "人": ("人物",),
    "portrait": ("人物",),
    "selfie": ("人物",),
}

# Camera-generated names carry no subject at all.
_MEANINGLESS_TOKENS = re.compile(r"^(img|dsc|dscn|p|pxl|photo|video|movie|mov|vid|image|screenshot|スクリーンショット)?[\d_\-]*$", re.I)


def tags_from_filename(filename: str) -> list[str]:
    stem = Path(filename).stem
    low = stem.lower()
    found: list[str] = []
    for needle, tags in _FILENAME_TAGS.items():
        if needle in low:
            for tag in tags:
                if tag not in found:
                    found.append(tag)

    # Any remaining human-written token is kept as-is: a user who named a
    # file 「首里城.jpg」 told us the subject, and dropping it because it
    # is not in the table would throw away the best tag available.
    for token in re.split(r"[\s_\-.()\[\]（）　]+", stem):
        token = token.strip()
        if not token or _MEANINGLESS_TOKENS.match(token):
            continue
        if len(token) < 2 or token.isdigit():
            continue
        if any(tag in token or token in tag for tag in found):
            continue
        if re.fullmatch(r"[A-Za-z0-9]+", token) and len(token) <= 3:
            continue
        found.append(token)
    return found[:8]


def _appearance_tags(brightness: float | None, motion: float | None, orientation: str) -> list[str]:
    tags: list[str] = []
    if brightness is not None:
        if brightness >= 0.62:
            tags.append("明るい")
        elif brightness <= 0.25:
            tags.append("暗い")
    if motion is not None:
        if motion >= 0.12:
            tags.append("動きあり")
        elif motion <= STATIC_THRESHOLD:
            tags.append("静止")
    if orientation:
        tags.append({"vertical": "縦向き", "horizontal": "横向き", "square": "正方形"}[orientation])
    return tags


def _orientation(width: int | None, height: int | None) -> str:
    if not width or not height:
        return ""
    if height > width * 1.05:
        return "vertical"
    if width > height * 1.05:
        return "horizontal"
    return "square"


# ------------------------------------------------------------- vision AI


_VISION_SYSTEM = (
    "あなたは動画編集のアシスタントです。渡された画像を見て、動画素材として"
    "使うための情報をJSONで返してください。JSONオブジェクトのみを返してください。\n"
    "出力形式:\n"
    '{"tags": ["海", "ビーチ", "夕日"], "description": "画面に写っているものの説明", '
    '"scene": "どんな場面か"}\n'
    "制約:\n"
    "- tags は日本語の名詞で3〜8個。写っているものだけを書き、推測で足さないこと。\n"
    "- description は1文。写っているものを具体的に書くこと。\n"
    "- 人物が写っている場合は tags に「人物」を含めること。"
)


# What the vision model is actually sent. A holiday photo is 12 megapixels;
# a vision model tokenises it into thousands of image tokens and spends
# minutes on a question that a 768px version answers identically. Downscaling
# is the difference between analysing ten photos in a minute and in ten.
_VISION_MAX_EDGE = 768


def _vision_payload(image_path: Path) -> tuple[str, bytes] | None:
    """The image to send, downscaled, or None if it cannot be read."""
    Image = _pillow()
    if Image is not None:
        try:
            import io

            with Image.open(image_path) as im:
                im = im.convert("RGB")
                im.thumbnail((_VISION_MAX_EDGE, _VISION_MAX_EDGE))
                buffer = io.BytesIO()
                im.save(buffer, "JPEG", quality=85)
                return "image/jpeg", buffer.getvalue()
        except Exception:  # noqa: BLE001 - falls back to the original file
            logger.info("Could not downscale %s for vision analysis", image_path.name)
    try:
        blob = image_path.read_bytes()
    except OSError:
        return None
    return ("image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"), blob


def _vision_tags(image_path: Path) -> dict | None:
    """Asks a loaded vision model what is in the frame. None when there
    is no vision model, or it did not answer usefully."""
    if llm_client.vision_model() is None:
        return None
    payload = _vision_payload(image_path)
    if payload is None:
        return None

    try:
        raw = llm_client.vision_completion(
            "この画像を動画素材として説明してください。",
            [payload],
            system=_VISION_SYSTEM,
        )
    except Exception as exc:  # noqa: BLE001 - falls back to metadata
        logger.warning("Vision analysis unavailable for %s: %s", image_path.name, exc)
        return None

    try:
        data = parse_json_object(raw)
    except JSONExtractionError:
        logger.warning(
            "Vision model returned unparsable analysis for %s: %s",
            image_path.name,
            raw[:200].replace(chr(10), " "),
        )
        return None

    tags = [str(t).strip() for t in (data.get("tags") or []) if str(t).strip()]
    return {
        "tags": tags[:10],
        "description": str(data.get("description") or "").strip()[:200],
        "scene": str(data.get("scene") or "").strip()[:120],
    }


# ---------------------------------------------------------------- analyse


def load_analysis(asset: MediaAsset) -> MaterialAnalysis | None:
    if not asset.analysis_json:
        return None
    try:
        return MaterialAnalysis.model_validate(json.loads(asset.analysis_json))
    except Exception:
        return None


def analyze_asset(
    db, asset: MediaAsset, *, use_vision: bool = True, force: bool = False
) -> MaterialAnalysis:
    """Analyses one asset and caches the result on its row."""
    if not force and asset.analysis_status == "done":
        cached = load_analysis(asset)
        if cached is not None:
            return cached

    path = media_service.asset_path(asset)
    if not path.exists():
        asset.analysis_status = "failed"
        asset.analysis_error = "ファイルが見つかりません。"
        db.commit()
        raise FileNotFoundError(f"素材ファイルが見つかりません: {asset.original_filename}")

    analysis = MaterialAnalysis(
        asset_id=asset.id,
        kind=asset.kind,
        width=asset.width,
        height=asset.height,
        duration=asset.duration or 0.0,
        fps=asset.fps,
        has_audio=bool(asset.has_audio),
    )
    representative: Path | None = None
    temp_dir: Path | None = None

    try:
        if asset.kind == "image":
            measured = _measure_image(path)
            analysis.width = measured.get("width") or asset.width
            analysis.height = measured.get("height") or asset.height
            analysis.brightness = measured.get("brightness")
            analysis.dominant_colors = measured.get("colors") or []
            representative = path
        elif asset.kind == "video":
            measured = _measure_video(path, asset.duration or 0.0)
            analysis.brightness = measured.get("brightness")
            analysis.motion = measured.get("motion")
            analysis.dominant_colors = measured.get("colors") or []
            usable = measured.get("usable")
            analysis.usable = usable if isinstance(usable, UsableRange) else UsableRange(
                start=0.0, end=asset.duration or 0.0
            )
            representative = measured.get("representative")
            temp_dir = measured.get("keep_dir")
        else:
            analysis.analyzed_by = "metadata"
            analysis.notes = "音声素材のため映像解析は行いません。"
            asset.analysis_status = "skipped"
            asset.analysis_json = analysis.model_dump_json()
            asset.analysis_error = None
            db.commit()
            return analysis

        analysis.orientation = _orientation(analysis.width, analysis.height)
        if analysis.kind == "video" and analysis.usable.end <= 0:
            analysis.usable = UsableRange(start=0.0, end=analysis.duration)

        tags: list[str] = []
        vision = _vision_tags(representative) if (use_vision and representative) else None
        if vision:
            tags.extend(vision["tags"])
            analysis.description = vision["description"]
            analysis.scene_summary = vision["scene"]
            analysis.analyzed_by = "vision_ai"
        else:
            analysis.analyzed_by = "metadata"

        name_tags = tags_from_filename(asset.original_filename)
        if name_tags:
            if analysis.analyzed_by == "metadata":
                analysis.analyzed_by = "metadata+filename"
            for tag in name_tags:
                if tag not in tags:
                    tags.append(tag)

        for tag in _appearance_tags(analysis.brightness, analysis.motion, analysis.orientation):
            if tag not in tags:
                tags.append(tag)

        analysis.tags = tags[:14]
        if analysis.analyzed_by != "vision_ai":
            analysis.notes = (
                "画像を解析できるAIモデル（Vision対応）がLM Studioにロードされていないため、"
                "ファイル名と画像の明るさ・向きから推定しています。"
            )

        asset.analysis_status = "done"
        asset.analysis_error = None
        asset.analysis_json = analysis.model_dump_json()
        db.commit()
        return analysis
    except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
        logger.exception("Material analysis failed for %s", asset.id)
        asset.analysis_status = "failed"
        asset.analysis_error = f"{type(exc).__name__}: {exc}"
        db.commit()
        raise
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)


def analyze_project(
    db, project_id: str, *, force: bool = False, on_progress=None
) -> list[MaterialAnalysis]:
    """Analyses every unanalysed piece of user material in a project."""
    assets = media_service.list_user_material(db, project_id)
    results: list[MaterialAnalysis] = []
    total = len(assets)
    for i, asset in enumerate(assets):
        if on_progress:
            on_progress(i, total, asset)
        try:
            results.append(analyze_asset(db, asset, force=force))
        except Exception:
            # Already recorded on the asset row; one unreadable file must
            # not stop the other nine from being usable.
            continue
    return results


def vision_available() -> bool:
    try:
        return llm_client.vision_model() is not None
    except Exception:  # noqa: BLE001
        return False
