"""Standalone smoke test for SVDEngine - NOT part of the app, just a
one-off script to measure real CPU generation time on this machine before
wiring the full API/job/UI stack on top of it.

Usage (from repo root):
    backend/.venv/Scripts/python.exe backend/scripts/test_svd_smoke.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw  # noqa: E402

from app.services.video_engines.svd_engine import SVDEngine  # noqa: E402

TEST_IMAGE_PATH = Path(__file__).resolve().parent / "_smoke_test_cat.png"
OUTPUT_PATH = Path(__file__).resolve().parent / "_smoke_test_output.mp4"


def make_test_image() -> Path:
    """A simple synthetic image (not a real photo) purely to exercise the
    pipeline mechanics and measure timing. Real end-to-end validation with
    an actual user photo happens through the Kairo UI."""
    img = Image.new("RGB", (512, 320), (60, 130, 200))
    draw = ImageDraw.Draw(img)
    draw.ellipse((180, 100, 340, 240), fill=(240, 200, 140))  # body
    draw.ellipse((150, 60, 220, 130), fill=(240, 200, 140))  # head
    draw.polygon([(150, 70), (140, 40), (165, 65)], fill=(240, 200, 140))  # ear
    draw.polygon([(210, 65), (225, 35), (222, 70)], fill=(240, 200, 140))  # ear
    draw.ellipse((165, 85, 175, 95), fill=(20, 20, 20))  # eye
    img.save(TEST_IMAGE_PATH)
    return TEST_IMAGE_PATH


def progress(pct: float, msg: str) -> None:
    print(f"[{pct:5.1f}%] {msg}", flush=True)


def main() -> None:
    image_path = make_test_image()
    engine = SVDEngine()

    print("already downloaded?", engine.is_model_downloaded())
    print("estimate (14f/15steps default):", engine.estimate_duration_seconds())

    t0 = time.time()
    result = engine.generate_image_to_video(
        image_path,
        OUTPUT_PATH,
        width=384,
        height=256,
        num_frames=8,
        num_inference_steps=6,
        fps=6,
        progress_cb=progress,
    )
    total = time.time() - t0

    print("---- RESULT ----")
    print("output:", result.output_path, result.output_path.stat().st_size, "bytes")
    print("elapsed (pipeline only):", result.elapsed_seconds, "s")
    print("elapsed (incl. model load):", total, "s")
    print("seconds/step:", result.elapsed_seconds / 6)


if __name__ == "__main__":
    main()
