"""Second smoke test at the API's actual default parameters
(512x320 / 14 frames / 15 steps), to get a realistic time estimate for the
README and for calibrating estimate_duration_seconds(). Not part of the app.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw  # noqa: E402

from app.services.video_engines.svd_engine import SVDEngine  # noqa: E402

TEST_IMAGE_PATH = Path(__file__).resolve().parent / "_smoke_test_cat2.png"
OUTPUT_PATH = Path(__file__).resolve().parent / "_smoke_test_output2.mp4"


def make_test_image() -> Path:
    img = Image.new("RGB", (512, 320), (60, 130, 200))
    draw = ImageDraw.Draw(img)
    draw.ellipse((180, 120, 380, 280), fill=(240, 200, 140))
    draw.ellipse((150, 60, 240, 150), fill=(240, 200, 140))
    draw.polygon([(150, 75), (135, 30), (172, 68)], fill=(240, 200, 140))
    draw.polygon([(220, 68), (240, 25), (238, 72)], fill=(240, 200, 140))
    draw.ellipse((168, 95, 180, 107), fill=(20, 20, 20))
    draw.ellipse((205, 95, 217, 107), fill=(20, 20, 20))
    img.save(TEST_IMAGE_PATH)
    return TEST_IMAGE_PATH


def progress(pct: float, msg: str) -> None:
    print(f"[{pct:5.1f}%] {msg}", flush=True)


def main() -> None:
    image_path = make_test_image()
    engine = SVDEngine()

    t0 = time.time()
    result = engine.generate_image_to_video(
        image_path,
        OUTPUT_PATH,
        width=512,
        height=320,
        num_frames=14,
        num_inference_steps=15,
        fps=7,
        progress_cb=progress,
    )
    total = time.time() - t0

    print("---- RESULT (default params 512x320/14f/15steps) ----")
    print("output:", result.output_path, result.output_path.stat().st_size, "bytes")
    print("elapsed (pipeline only):", result.elapsed_seconds, "s")
    print("elapsed (incl. model load):", total, "s")
    print("seconds/step:", result.elapsed_seconds / 15)


if __name__ == "__main__":
    main()
