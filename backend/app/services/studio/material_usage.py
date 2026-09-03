"""Where every shot in the finished video came from.

Design requirement 11: after a video is made, the user must be able to ask
of any moment "この素材はどこから来たのか" and get a real answer - their own
file, a licensed web image, or something Kairo generated - with the time
range it occupies.

The report is derived from the scene rows rather than stored separately, so
it cannot drift from what was actually rendered: the same `material_origin`
the asset stage wrote is the thing being reported, and the time ranges come
from the durations the timeline was built with.
"""
from __future__ import annotations

from app.models.media_asset import MediaAsset
from app.models.production import Scene
from app.schemas.material import (
    ORIGIN_LABELS,
    MaterialUsageEntry,
    MaterialUsageReport,
)


def _origin_for(scene: Scene) -> str:
    """The recorded origin, or the best honest guess for older projects.

    Scenes planned before the material pipeline existed have no
    `material_origin`, and inventing one would be a claim about a video
    Kairo cannot inspect after the fact. Falling back to the pin state is
    the most that can be said truthfully.
    """
    if scene.material_origin:
        return scene.material_origin
    if scene.asset_source == "user" and scene.user_asset_id:
        return "user"
    if scene.asset_source == "web" and scene.user_asset_id:
        return "web"
    return "procedural"


def build_report(db, project_id: str) -> MaterialUsageReport:
    from app.services.studio import planning_service

    scenes = planning_service.ordered_scenes(db, project_id)
    report = MaterialUsageReport()
    cursor = 0.0
    counts: dict[str, int] = {}

    for i, scene in enumerate(scenes):
        duration = float(scene.estimated_duration or 0.0)
        origin = _origin_for(scene)
        asset = db.get(MediaAsset, scene.user_asset_id) if scene.user_asset_id else None
        note = scene.material_note or ""
        if asset is not None and asset.origin_detail and not note:
            note = asset.origin_detail

        report.entries.append(
            MaterialUsageEntry(
                scene_index=i,
                scene_number=i + 1,
                start=round(cursor, 2),
                end=round(cursor + duration, 2),
                origin=origin,  # type: ignore[arg-type]
                origin_label=ORIGIN_LABELS.get(origin, origin),
                asset_id=asset.id if asset is not None else None,
                filename=(
                    asset.original_filename
                    if asset is not None
                    else (scene.visual_prompt or "")[:40]
                ),
                subtitle=scene.subtitle_text or "",
                note=note,
                source_start=scene.user_asset_start,
                source_end=scene.user_asset_end,
            )
        )
        counts[origin] = counts.get(origin, 0) + 1
        cursor += duration

    report.total_duration = round(cursor, 2)
    report.counts = counts
    return report
