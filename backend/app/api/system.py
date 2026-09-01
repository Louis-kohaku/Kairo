from __future__ import annotations

from fastapi import APIRouter

from app.services import system_info_service

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/system/info")
def system_info():
    return system_info_service.get_system_report()
