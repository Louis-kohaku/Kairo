"""Project-on-disk layout helpers.

Mirrors the directory structure from the design doc (section 21). Phase 1
only actively uses `assets/`, `timeline/`, `renders/` and `logs/`; the other
directories are created up front so later phases (script, storyboard,
scenes, sources, subtitles) can drop files in without a migration.
"""
from __future__ import annotations

from pathlib import Path

from app.core.config import PROJECTS_ROOT

SUBDIRS = (
    "script",
    "storyboard",
    "sources",
    "scenes",
    "audio",
    "subtitles",
    "assets",
    "timeline",
    "renders",
    "logs",
)


def project_dir(project_id: str) -> Path:
    return PROJECTS_ROOT / project_id


def assets_dir(project_id: str) -> Path:
    return project_dir(project_id) / "assets"


def renders_dir(project_id: str) -> Path:
    return project_dir(project_id) / "renders"


def logs_dir(project_id: str) -> Path:
    return project_dir(project_id) / "logs"


def tmp_segments_dir(project_id: str) -> Path:
    d = renders_dir(project_id) / "_segments_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_project_layout(project_id: str) -> Path:
    root = project_dir(project_id)
    for sub in SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def resolve_within(base: Path, relative: str) -> Path:
    """Join `relative` onto `base` and guarantee the result stays inside base.

    Raises ValueError on any attempt to escape (e.g. via `..` segments),
    since `relative` values can originate from data we generated ourselves
    but this is cheap insurance against path traversal.
    """
    candidate = (base / relative).resolve()
    base_resolved = base.resolve()
    if base_resolved not in candidate.parents and candidate != base_resolved:
        raise ValueError(f"Path {relative!r} escapes base directory {base}")
    return candidate
