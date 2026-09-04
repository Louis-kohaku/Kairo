from __future__ import annotations

from fastapi import APIRouter

from app.schemas.settings import AppSettings, AppSettingsPatch
from app.services import settings_service
from app.services.studio import style_memory

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=AppSettings)
def get_settings():
    return settings_service.get_settings()


@router.put("", response_model=AppSettings)
def update_settings(patch: AppSettingsPatch):
    updated = settings_service.update_settings(patch)
    _remember_subtitle_preferences(patch)
    return updated


def _remember_subtitle_preferences(patch: AppSettingsPatch) -> None:
    """Files an explicit caption change into the Style Memory.

    This is the half of requirement 16 that has to happen *here*: what the
    user changes by hand is a standing preference the next production
    should start from, and it is only recognisable as one at the moment
    they change it. What Kairo itself chose is recorded separately, by the
    pipeline, as variety data - see services/studio/style_memory.py for why
    the two must not be mixed.

    Never fails a settings save: a memory that cannot be written is a lost
    convenience, and refusing the user's setting over it would be absurd.
    """
    if patch.subtitle is None:
        return
    try:
        for key, value in (
            ("subtitle_size", patch.subtitle.size),
            ("subtitle_position", patch.subtitle.position),
            ("subtitle_style", patch.subtitle.style),
            ("subtitle_color", patch.subtitle.color),
            ("font_family", patch.subtitle.font),
        ):
            if value is not None:
                style_memory.remember_preference(key, value, source="user")
    except Exception:  # noqa: BLE001
        pass


@router.post("/reset", response_model=AppSettings)
def reset_settings():
    return settings_service.reset_settings()


# --------------------------------------------------------- style memory


@router.get("/style-memory")
def get_style_memory():
    """What Kairo has learned about how this user likes their videos.

    Reported as frequencies and explicit choices rather than as "your
    favourite": a count of three is not a preference, and presenting it as
    one would be the same kind of overclaim as an unlabelled AI score.
    """
    return style_memory.summary()


@router.delete("/style-memory")
def clear_style_memory():
    style_memory.clear()
    return style_memory.summary()
