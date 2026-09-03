from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import (
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_MEDIA_EXTENSIONS,
    ALLOWED_VIDEO_EXTENSIONS,
    MAX_IMAGE_PIXELS,
    MAX_UPLOAD_BYTES,
)
from app.core.paths import assets_dir, project_dir
from app.models.media_asset import MediaAsset
from app.services.ffmpeg.probe import ProbeError, probe_media

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024  # 1 MiB


class UnsupportedMediaError(ValueError):
    """An import that failed for a reason the user can act on.

    Carries the cause separately from the headline so the UI can show
    "MP4の読み込みに失敗しました" with "動画コーデックが対応していません"
    underneath, instead of the single "エラーが発生しました" that told the
    user nothing (design requirement 14). `hint` is what to actually do.
    """

    def __init__(self, message: str, *, cause: str = "", hint: str = "", raw: str = "") -> None:
        self.message = message
        self.cause = cause
        self.hint = hint
        self.raw = raw
        super().__init__(message if not cause else f"{message} {cause}")

    def to_dict(self) -> dict:
        return {
            "message": self.message,
            "cause": self.cause,
            "hint": self.hint,
            "raw": self.raw,
        }


def kind_for_suffix(suffix: str) -> str:
    if suffix in ALLOWED_VIDEO_EXTENSIONS:
        return "video"
    if suffix in ALLOWED_IMAGE_EXTENSIONS:
        return "image"
    return "audio"


def _safe_suffix(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if not suffix:
        raise UnsupportedMediaError(
            f"「{filename or '(名前なし)'}」を読み込めませんでした。",
            cause="拡張子がないため、ファイルの種類を判別できませんでした。",
            hint="拡張子付きのファイル名（例: photo.jpg）で保存してから読み込んでください。",
        )
    if suffix not in ALLOWED_MEDIA_EXTENSIONS:
        raise UnsupportedMediaError(
            f"「{filename}」は対応していない形式です。",
            cause=f"拡張子 {suffix} には対応していません。",
            hint=(
                "写真: JPG / PNG / WEBP、"
                "動画: MP4 / MOV / MKV / WEBM、"
                "音声: MP3 / WAV / M4A に対応しています。"
            ),
        )
    return suffix


def _diagnose_probe_failure(filename: str, suffix: str, raw: str) -> UnsupportedMediaError:
    """Turns ffprobe's stderr into something the user can act on.

    ffprobe is precise about *why* it could not read a file, and that
    precision is exactly what the old generic message threw away.
    """
    low = raw.lower()
    kind_label = {"video": "動画", "image": "画像", "audio": "音声"}[kind_for_suffix(suffix)]
    headline = f"{suffix.lstrip('.').upper()}の読み込みに失敗しました（{filename}）。"

    if "decoder" in low and ("not found" in low or "no decoder" in low):
        return UnsupportedMediaError(
            headline,
            cause="この動画のコーデックにFFmpegが対応していません。",
            hint="別の形式（H.264のMP4など）に変換してから読み込んでください。",
            raw=raw,
        )
    if "invalid data found" in low or "moov atom not found" in low:
        return UnsupportedMediaError(
            headline,
            cause=f"ファイルが壊れているか、{kind_label}として読み取れる内容がありませんでした。",
            hint="元のファイルを開けるか確認し、開けない場合は書き出し直してください。",
            raw=raw,
        )
    if "permission denied" in low:
        return UnsupportedMediaError(
            headline,
            cause="ファイルを読み取る権限がありませんでした。",
            hint="ファイルの権限を確認するか、別の場所にコピーしてから読み込んでください。",
            raw=raw,
        )
    if "timed out" in low:
        return UnsupportedMediaError(
            headline,
            cause="ファイルの解析が時間内に終わりませんでした。",
            hint="非常に長い動画の場合は、必要な部分だけを書き出してから読み込んでください。",
            raw=raw,
        )
    if "ffprobe" in low and "not found" in low:
        return UnsupportedMediaError(
            headline,
            cause="FFmpeg（ffprobe）が見つかりませんでした。",
            hint="FFmpegをインストールし、PATHを通してからKairoを再起動してください。",
            raw=raw,
        )
    return UnsupportedMediaError(
        headline,
        cause="FFmpegがこのファイルを解析できませんでした。",
        hint="別の形式に変換するか、別のファイルで試してください。",
        raw=raw,
    )


def import_media(
    db: Session,
    project_id: str,
    upload: UploadFile,
    *,
    origin: str = "user",
    origin_detail: str = "",
) -> MediaAsset:
    filename = upload.filename or ""
    suffix = _safe_suffix(filename)
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    dest_dir = assets_dir(project_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / stored_name

    written = 0
    try:
        with dest_path.open("wb") as out_file:
            while chunk := upload.file.read(CHUNK_SIZE):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise UnsupportedMediaError(
                        f"「{filename}」はファイルサイズが大きすぎます。",
                        cause=(
                            f"{written / (1024 * 1024):.0f}MB以上あり、"
                            f"上限の{MAX_UPLOAD_BYTES / (1024 * 1024 * 1024):.1f}GBを超えました。"
                        ),
                        hint="解像度を下げるか、必要な部分だけを書き出してから読み込んでください。",
                    )
                out_file.write(chunk)
    except UnsupportedMediaError:
        dest_path.unlink(missing_ok=True)
        raise
    except OSError as exc:
        dest_path.unlink(missing_ok=True)
        raise UnsupportedMediaError(
            f"「{filename}」の保存に失敗しました。",
            cause=str(exc),
            hint="保存先の空き容量とアクセス権を確認してください。",
            raw=str(exc),
        ) from exc

    if written == 0:
        dest_path.unlink(missing_ok=True)
        raise UnsupportedMediaError(
            f"「{filename}」は中身が空でした。",
            cause="ファイルサイズが0バイトです。",
            hint="ファイルが正しく保存されているか確認してください。",
        )

    try:
        info = probe_media(dest_path)
    except ProbeError as exc:
        dest_path.unlink(missing_ok=True)
        raise _diagnose_probe_failure(filename, suffix, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - reported to the user verbatim
        dest_path.unlink(missing_ok=True)
        raise _diagnose_probe_failure(filename, suffix, str(exc)) from exc

    kind = kind_for_suffix(suffix)
    if kind == "image" and info.width and info.height:
        pixels = info.width * info.height
        if pixels > MAX_IMAGE_PIXELS:
            dest_path.unlink(missing_ok=True)
            raise UnsupportedMediaError(
                f"「{filename}」は画像サイズが大きすぎます。",
                cause=(
                    f"{info.width}×{info.height}（約{pixels / 1_000_000:.0f}メガピクセル）あり、"
                    f"上限の{MAX_IMAGE_PIXELS / 1_000_000:.0f}メガピクセルを超えています。"
                ),
                hint="画像を縮小してから読み込んでください。",
            )
    if kind == "image" and not info.has_video:
        dest_path.unlink(missing_ok=True)
        raise UnsupportedMediaError(
            f"「{filename}」を画像として読み込めませんでした。",
            cause="画像データが含まれていませんでした。",
            hint="JPG / PNG / WEBP のいずれかで保存し直してから読み込んでください。",
        )
    if kind == "video" and not info.has_video:
        dest_path.unlink(missing_ok=True)
        raise UnsupportedMediaError(
            f"「{filename}」に映像トラックがありませんでした。",
            cause="音声だけのファイルの可能性があります。",
            hint="音声として使う場合は拡張子をm4a/mp3にして読み込んでください。",
        )

    asset = MediaAsset(
        project_id=project_id,
        kind=kind,
        original_filename=filename or stored_name,
        stored_path=f"assets/{stored_name}",
        # A still has no duration of its own; how long it is shown is a
        # scene decision, so leaving it at 0 keeps the two from being
        # confused with each other.
        duration=0.0 if kind == "image" else info.duration,
        width=info.width,
        height=info.height,
        fps=info.fps if kind == "video" else None,
        has_audio=info.has_audio,
        video_codec=info.video_codec,
        audio_codec=info.audio_codec,
        origin=origin,
        origin_detail=origin_detail,
        analysis_status="pending",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def register_file(
    db: Session,
    project_id: str,
    path: Path,
    *,
    original_filename: str,
    origin: str,
    origin_detail: str = "",
) -> MediaAsset:
    """Registers a file already sitting inside the project's assets dir.

    Used by the material stages (web download, AI generation) so material
    Kairo fetched or produced becomes an ordinary MediaAsset with honest
    provenance, rather than a second kind of thing the timeline would need
    to learn about.
    """
    info = probe_media(path)
    suffix = path.suffix.lower()
    kind = kind_for_suffix(suffix)
    asset = MediaAsset(
        project_id=project_id,
        kind=kind,
        original_filename=original_filename,
        stored_path=f"assets/{path.name}",
        duration=0.0 if kind == "image" else info.duration,
        width=info.width,
        height=info.height,
        fps=info.fps if kind == "video" else None,
        has_audio=info.has_audio,
        video_codec=info.video_codec,
        audio_codec=info.audio_codec,
        origin=origin,
        origin_detail=origin_detail,
        analysis_status="pending",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def list_media(db: Session, project_id: str) -> list[MediaAsset]:
    return (
        db.query(MediaAsset)
        .filter(MediaAsset.project_id == project_id)
        .order_by(MediaAsset.imported_at.asc())
        .all()
    )


def list_user_material(db: Session, project_id: str) -> list[MediaAsset]:
    """The photos and videos the user supplied, in import order.

    Audio is excluded: it is never a candidate for a scene's picture, and
    including it made "写真8枚・動画3本" counts wrong the moment a project
    had BGM in it.
    """
    return [
        a
        for a in list_media(db, project_id)
        if (a.origin or "user") == "user" and a.kind in ("image", "video")
    ]


def get_media(db: Session, asset_id: str) -> MediaAsset | None:
    return db.get(MediaAsset, asset_id)


def asset_path(asset: MediaAsset) -> Path:
    return project_dir(asset.project_id) / asset.stored_path


def delete_media(db: Session, asset: MediaAsset) -> None:
    """Removes an imported asset and its file.

    Any scene pinned to it is unpinned rather than left pointing at a
    missing row, so deleting a photo the user changed their mind about
    cannot break the next rebuild.
    """
    from app.models.production import Scene
    from app.models.timeline import Clip

    for clip in db.query(Clip).filter(Clip.media_asset_id == asset.id).all():
        db.delete(clip)
    for scene in db.query(Scene).filter(Scene.user_asset_id == asset.id).all():
        scene.user_asset_id = None
        scene.user_asset_start = None
        scene.user_asset_end = None
        if scene.asset_source == "user":
            scene.asset_source = "auto"

    path = asset_path(asset)
    db.delete(asset)
    db.commit()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not delete media file %s", path)
