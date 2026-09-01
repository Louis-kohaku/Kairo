from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.media_asset import MediaAsset
from app.models.timeline import Clip, Track


class TimelineError(ValueError):
    pass


def _clips_of_track(db: Session, track_id: str) -> list[Clip]:
    """Fresh, un-cached read of a track's clips.

    Several callers (notably the AI-edit orchestrator) run multiple clip
    mutations back-to-back in one long-lived session. `track.clips` is an
    ORM relationship that can go stale across those calls when new rows
    are inserted by setting the FK column directly rather than through the
    relationship attribute, which previously caused order_index clashes.
    Querying by track_id directly sidesteps that caching entirely.
    """
    return (
        db.query(Clip)
        .filter(Clip.track_id == track_id)
        .order_by(Clip.order_index)
        .all()
    )


def get_tracks(db: Session, project_id: str) -> list[Track]:
    return (
        db.query(Track)
        .filter(Track.project_id == project_id)
        .order_by(Track.order_index)
        .all()
    )


def track_duration(track: Track) -> float:
    return sum(c.duration for c in track.clips)


def timeline_duration(tracks: list[Track]) -> float:
    return max((track_duration(t) for t in tracks), default=0.0)


def _renumber(clips: list[Clip]) -> None:
    for i, clip in enumerate(sorted(clips, key=lambda c: c.order_index)):
        clip.order_index = i


def add_clip(
    db: Session,
    track_id: str,
    media_asset_id: str,
    in_point: float,
    out_point: float | None,
    volume: float,
    index: int | None,
) -> Clip:
    track = db.get(Track, track_id)
    if track is None:
        raise TimelineError(f"Track {track_id} not found")

    asset = db.get(MediaAsset, media_asset_id)
    if asset is None:
        raise TimelineError(f"Media asset {media_asset_id} not found")

    resolved_out = out_point if out_point is not None else asset.duration
    if in_point < 0 or resolved_out <= in_point or resolved_out > asset.duration + 1e-3:
        raise TimelineError(
            f"Invalid trim range [{in_point}, {resolved_out}] for asset of "
            f"duration {asset.duration}"
        )

    existing = _clips_of_track(db, track_id)
    insert_at = index if index is not None else len(existing)
    insert_at = max(0, min(insert_at, len(existing)))

    for clip in existing:
        if clip.order_index >= insert_at:
            clip.order_index += 1

    clip = Clip(
        track_id=track_id,
        media_asset_id=media_asset_id,
        order_index=insert_at,
        in_point=in_point,
        out_point=resolved_out,
        volume=volume,
    )
    db.add(clip)
    db.commit()
    db.refresh(clip)
    return clip


def update_clip(
    db: Session,
    clip_id: str,
    in_point: float | None,
    out_point: float | None,
    volume: float | None,
) -> Clip:
    clip = db.get(Clip, clip_id)
    if clip is None:
        raise TimelineError(f"Clip {clip_id} not found")

    new_in = in_point if in_point is not None else clip.in_point
    new_out = out_point if out_point is not None else clip.out_point
    asset = clip.media_asset

    if new_in < 0 or new_out <= new_in or new_out > asset.duration + 1e-3:
        raise TimelineError(
            f"Invalid trim range [{new_in}, {new_out}] for asset of "
            f"duration {asset.duration}"
        )

    clip.in_point = new_in
    clip.out_point = new_out
    if volume is not None:
        clip.volume = volume

    db.commit()
    db.refresh(clip)
    return clip


def delete_clip(db: Session, clip_id: str) -> None:
    clip = db.get(Clip, clip_id)
    if clip is None:
        raise TimelineError(f"Clip {clip_id} not found")

    track_id = clip.track_id
    db.delete(clip)
    db.flush()
    _renumber(_clips_of_track(db, track_id))
    db.commit()


def split_clip(db: Session, track_id: str, at_time: float) -> tuple[Clip, Clip]:
    """Split whichever clip on `track_id` covers absolute timeline position
    `at_time` into two adjacent clips, preserving total duration.
    """
    track = db.get(Track, track_id)
    if track is None:
        raise TimelineError(f"Track {track_id} not found")

    track_clips = _clips_of_track(db, track_id)
    cursor = 0.0
    for clip in track_clips:
        clip_end = cursor + clip.duration
        if cursor <= at_time < clip_end:
            offset = at_time - cursor
            if offset <= 1e-3 or offset >= clip.duration - 1e-3:
                raise TimelineError("Split point is too close to a clip boundary")

            split_point = clip.in_point + offset

            second = Clip(
                track_id=track.id,
                media_asset_id=clip.media_asset_id,
                order_index=clip.order_index + 1,
                in_point=split_point,
                out_point=clip.out_point,
                volume=clip.volume,
            )
            clip.out_point = split_point

            for other in track_clips:
                if other.id != clip.id and other.order_index >= clip.order_index + 1:
                    other.order_index += 1

            db.add(second)
            db.commit()
            db.refresh(clip)
            db.refresh(second)
            return clip, second

        cursor = clip_end

    raise TimelineError(f"No clip on track {track_id} covers time {at_time}")
