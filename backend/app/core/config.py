"""Central configuration for the Kairo backend.

All filesystem roots are resolved here so the rest of the codebase never
hardcodes paths. This keeps the Intel dev machine and the future Apple
Silicon Mac mini deployment interchangeable.
"""
from __future__ import annotations

import os
from pathlib import Path

# Repository root is the parent of the `backend` directory this file lives in.
REPO_ROOT = Path(__file__).resolve().parents[3]

# Where all project data (videos, renders, the sqlite db, logs) is stored.
# Overridable via KAIRO_DATA_ROOT for tests / alternate installs.
DATA_ROOT = Path(os.environ.get("KAIRO_DATA_ROOT", REPO_ROOT / "data")).resolve()
PROJECTS_ROOT = DATA_ROOT / "projects"

DATABASE_PATH = DATA_ROOT / "kairo.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"

# Allowed source file extensions for imported media (defence in depth against
# path traversal / arbitrary file writes when handling uploads).
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
ALLOWED_MEDIA_EXTENSIONS = ALLOWED_VIDEO_EXTENSIONS | ALLOWED_AUDIO_EXTENSIONS

# Default render target. Individual projects can override resolution/fps.
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_FPS = 30.0

# Background music is mixed under the main audio at this relative volume.
DEFAULT_BGM_VOLUME = 0.25

# Local speech-to-text (faster-whisper). "small" is a reasonable
# quality/speed balance for the Apple Silicon Mac mini target; on the
# Intel dev machine a smaller size can be set via env var for faster
# iteration.
WHISPER_MODEL_SIZE = os.environ.get("KAIRO_WHISPER_MODEL", "small")
WHISPER_DEVICE = os.environ.get("KAIRO_WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.environ.get("KAIRO_WHISPER_COMPUTE", "int8")

# Silence detection defaults for AI auto-cut.
DEFAULT_SILENCE_NOISE_DB = -30.0
DEFAULT_SILENCE_MIN_DURATION = 0.5
DEFAULT_SILENCE_PADDING = 0.15
DEFAULT_MIN_KEEP_DURATION = 0.15

# LM Studio (or any OpenAI-compatible local server) backs the AI editing
# orchestrator. No cloud fallback is ever used - if this is unreachable,
# AI-edit requests fail with a clear message instead of degrading silently.
LLM_BASE_URL = os.environ.get("KAIRO_LLM_BASE_URL", "http://localhost:1234/v1")
LLM_MODEL = os.environ.get("KAIRO_LLM_MODEL", "local-model")
LLM_TIMEOUT = float(os.environ.get("KAIRO_LLM_TIMEOUT", "120"))
LLM_MAX_OPERATIONS = 10

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "tauri://localhost",
]


def ensure_data_dirs() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
