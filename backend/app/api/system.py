from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.services import connected_services, system_info_service

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/system/info")
def system_info():
    return system_info_service.get_system_report()


@router.get("/system/services")
def connected(db: Session = Depends(get_db)):
    """Every external and local service Kairo uses, checked live.

    Design rule 25: the user must be able to see what is actually connected
    - endpoint, model, auth, cost and current state - rather than take the
    documentation's word for it.
    """
    return connected_services.collect(db)
