"""Central configuration for the Kairo backend.

All filesystem roots are resolved here so the rest of the codebase never
hardcodes paths. This keeps the Intel dev machine and the future Apple
Silicon Mac mini deployment interchangeable.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Repository root is the parent of the `backend` directory this file lives in.
REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Load backend/.env if present. Values already set in the real environment
# always win (python-dotenv's default), so this is a no-op when running
# under a process manager that injects env vars directly.
load_dotenv(BACKEND_ROOT / ".env")

# Where all project data (videos, renders, the sqlite db, logs) is stored.
# Overridable via KAIRO_DATA_ROOT for tests / alternate installs.
DATA_ROOT = Path(os.environ.get("KAIRO_DATA_ROOT", REPO_ROOT / "data")).resolve()
PROJECTS_ROOT = DATA_ROOT / "projects"

# Local AI model weights (image/video generation etc.) are downloaded here
# instead of the default ~/.cache/huggingface, so every model Kairo uses
# lives inside DATA_ROOT and shows up in Kairo's own disk-usage / model
# management views.
MODELS_ROOT = DATA_ROOT / "models"

# The Creative Asset Library: fonts, music and SFX Kairo can draw on,
# together with the licence record for each. Lives under DATA_ROOT (not the
# repository) because its contents are downloaded or user-supplied files,
# not source code, and because everything Kairo stores should be in one
# place the user can back up or delete.
LIBRARY_ROOT = Path(os.environ.get("KAIRO_LIBRARY_ROOT", DATA_ROOT / "library")).resolve()

DATABASE_PATH = DATA_ROOT / "kairo.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"

# Allowed source file extensions for imported media (defence in depth against
# path traversal / arbitrary file writes when handling uploads).
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
# Stills the user supplies as material. Restricted to what both Pillow and
# FFmpeg can read, because every one of them has to survive analysis
# (Pillow) *and* being turned into a clip (FFmpeg) - accepting a format
# only one of the two understands would fail halfway through a production
# instead of at import time.
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
ALLOWED_MEDIA_EXTENSIONS = (
    ALLOWED_VIDEO_EXTENSIONS | ALLOWED_AUDIO_EXTENSIONS | ALLOWED_IMAGE_EXTENSIONS
)

# Upload ceiling per file. Not a security boundary (this is a local app) but
# a way to fail with "この画像は大きすぎます" at import instead of with an
# out-of-memory error three phases into a production.
MAX_UPLOAD_BYTES = int(os.environ.get("KAIRO_MAX_UPLOAD_BYTES", str(2 * 1024 * 1024 * 1024)))
# Pillow refuses images beyond this many pixels as a decompression-bomb
# guard; Kairo reports the same limit up front with a usable message.
MAX_IMAGE_PIXELS = 80_000_000

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
# Explicit model override. When unset, Kairo auto-detects whatever LM Studio
# actually has loaded via /v1/models and picks a model itself (user setting
# -> PC-based recommendation -> first available) instead of guessing a
# fixed id - see app/services/llm_client.py's resolve_model(). There is
# deliberately no "local-model"-style placeholder default here: a fake
# default that happens to work with LM Studio's lenient dispatch used to
# mask real misconfiguration instead of surfacing it.
LLM_MODEL_ENV = os.environ.get("KAIRO_LLM_MODEL", "").strip() or None
# Generous by default: a 7B model on a CPU/iGPU machine (this project's
# target) regularly takes several minutes for a full scene-design reply,
# and a timeout there is indistinguishable to the user from a hang - the
# run just fails partway through. Lower it only if you are running on a
# fast discrete GPU and want failures surfaced sooner.
LLM_TIMEOUT = float(os.environ.get("KAIRO_LLM_TIMEOUT", "600"))
LLM_MAX_OPERATIONS = 10


# Extra allowed origins (comma-separated), e.g. for accessing the dev
# frontend from another device on the LAN: KAIRO_CORS_ORIGINS=http://192.168.1.20:5173
_extra_cors_origins = [
    o.strip() for o in os.environ.get("KAIRO_CORS_ORIGINS", "").split(",") if o.strip()
]

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "tauri://localhost",
    *_extra_cors_origins,
]


# Optional external service keys. Read here (never hardcoded, never
# committed) so one place answers "what is Kairo configured to reach?".
# Every one of these is optional: an unset key disables exactly one
# optional source and changes nothing else.
YOUTUBE_API_KEY = os.environ.get("KAIRO_YOUTUBE_API_KEY", "").strip()


def ensure_data_dirs() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
    MODELS_ROOT.mkdir(parents=True, exist_ok=True)
    LIBRARY_ROOT.mkdir(parents=True, exist_ok=True)
