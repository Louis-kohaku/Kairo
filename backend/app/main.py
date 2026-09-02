from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    ai,
    ai_edit,
    cut,
    generation,
    jobs,
    media,
    production,
    projects,
    settings,
    studio,
    subtitles,
    system,
    timeline,
)
from app.core.config import CORS_ORIGINS, ensure_data_dirs
from app.core.db import init_db

app = FastAPI(title="Kairo", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Content-Disposition isn't on the CORS default-safelisted response
    # header set, so without this the frontend's completion screen (reading
    # the render's suggested filename via HEAD) silently falls back to the
    # raw job id instead of the "kairo_<title>_<date>.mp4" name the backend
    # actually sends (see jobs.py's download endpoint).
    expose_headers=["Content-Disposition"],
)

app.include_router(projects.router)
app.include_router(media.router)
app.include_router(timeline.router)
app.include_router(jobs.router)
app.include_router(subtitles.router)
app.include_router(cut.router)
app.include_router(ai_edit.router)
app.include_router(production.router)
app.include_router(generation.router)
app.include_router(system.router)
app.include_router(ai.router)
app.include_router(settings.router)
app.include_router(studio.router)


@app.on_event("startup")
def on_startup() -> None:
    ensure_data_dirs()
    init_db()


@app.get("/api/health")
def health():
    return {"status": "ok"}
