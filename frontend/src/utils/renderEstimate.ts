import type { QualityPreset } from "../types";

// Client-side, rule-of-thumb estimates only (no backend round-trip) - shown
// in the UI clearly labelled as an approximation. There is no per-PC
// benchmark data for the ffmpeg render step (unlike AI generation, which
// has time_estimate_service on the backend), so this scales a few
// reference bitrates/speeds by resolution, fps and quality preset instead
// of claiming false precision.
const REF_PIXELS = 1920 * 1080;
const REF_FPS = 30;

const QUALITY_VIDEO_MBPS: Record<QualityPreset, number> = {
  fast: 5,
  standard: 8,
  high: 14,
  ultra: 20,
  custom: 8,
};

const QUALITY_ENCODE_FACTOR: Record<QualityPreset, number> = {
  fast: 0.8,
  standard: 1.4,
  high: 2.2,
  ultra: 3.2,
  custom: 1.4,
};

export function estimateFileSizeMB(
  width: number,
  height: number,
  fps: number,
  quality: QualityPreset,
  durationSeconds: number,
): number {
  const pixelRatio = (width * height) / REF_PIXELS;
  const fpsRatio = fps / REF_FPS;
  const videoMbps = (QUALITY_VIDEO_MBPS[quality] ?? 8) * Math.sqrt(pixelRatio) * Math.sqrt(fpsRatio);
  const audioMbps = 0.192; // AAC audio track
  return ((videoMbps + audioMbps) * durationSeconds) / 8;
}

// libx264 CRF (0-51, lower = higher quality/larger file) actually sent to
// the render job - this is what makes the "品質" dropdown a real knob on
// the encoded output, not just a label.
export const QUALITY_CRF: Record<QualityPreset, number> = {
  fast: 23,
  standard: 20,
  high: 17,
  ultra: 15,
  custom: 20,
};

export interface RenderTimeEstimate {
  lowSeconds: number;
  highSeconds: number;
}

export function estimateRenderSeconds(
  durationSeconds: number,
  clipCount: number,
  quality: QualityPreset,
  cpuOnly: boolean,
): RenderTimeEstimate {
  const factor = (QUALITY_ENCODE_FACTOR[quality] ?? 1.4) * (cpuOnly ? 1.3 : 1);
  const base = durationSeconds * factor;
  const perClipOverhead = clipCount * 1.5;
  const low = Math.max(5, base * 0.7 + perClipOverhead * 0.5);
  const high = Math.max(10, base * 1.5 + perClipOverhead);
  return { lowSeconds: low, highSeconds: high };
}
