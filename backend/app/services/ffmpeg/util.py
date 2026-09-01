from __future__ import annotations

import shutil


class FFmpegNotFoundError(RuntimeError):
    pass


def require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise FFmpegNotFoundError(
            f"'{name}' was not found on PATH. Install FFmpeg and ensure it is "
            "available before importing media or rendering."
        )
    return path
