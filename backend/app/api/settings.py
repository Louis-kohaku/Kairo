from __future__ import annotations

from fastapi import APIRouter

from app.schemas.settings import AppSettings, AppSettingsPatch
from app.services import settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=AppSettings)
def get_settings():
    return settings_service.get_settings()


@router.put("", response_model=AppSettings)
def update_settings(patch: AppSettingsPatch):
    return settings_service.update_settings(patch)


@router.post("/reset", response_model=AppSettings)
def reset_settings():
    return settings_service.reset_settings()
