from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import ai_edit, cut, jobs, media, production, projects, subtitles, timeline
from app.core.config import CORS_ORIGINS, ensure_data_dirs
from app.core.db import init_db

app = FastAPI(title="Kairo", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(media.router)
app.include_router(timeline.router)
app.include_router(jobs.router)
app.include_router(subtitles.router)
app.include_router(cut.router)
app.include_router(ai_edit.router)
app.include_router(production.router)


@app.on_event("startup")
def on_startup() -> None:
    ensure_data_dirs()
    init_db()


@app.get("/api/health")
def health():
    return {"status": "ok"}
