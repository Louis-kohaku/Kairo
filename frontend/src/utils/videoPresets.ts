import type { QualityPreset } from "../types";

export type Aspect = "9:16" | "16:9" | "1:1";

export const ASPECTS: { id: Aspect; label: string; description: string }[] = [
  { id: "9:16", label: "9:16", description: "縦型動画 / Shorts・TikTok" },
  { id: "16:9", label: "16:9", description: "横型動画 / YouTube" },
  { id: "1:1", label: "1:1", description: "正方形 / フィード投稿" },
];

export const QUALITY_PRESETS: { id: QualityPreset; label: string; description: string }[] = [
  { id: "fast", label: "高速", description: "処理時間優先(720p相当・24fps)" },
  { id: "standard", label: "標準", description: "品質と速度のバランス(1080p相当・30fps)" },
  { id: "high", label: "高品質", description: "映像品質優先(1080p相当・60fps、処理時間は長め)" },
];

export function resolutionFor(
  aspect: Aspect,
  quality: QualityPreset,
): { width: number; height: number; fps: number } {
  const base: Record<Aspect, { w: number; h: number }> = {
    "9:16": { w: 1080, h: 1920 },
    "16:9": { w: 1920, h: 1080 },
    "1:1": { w: 1080, h: 1080 },
  };
  const scale = quality === "fast" ? 2 / 3 : 1;
  const fps = quality === "high" || quality === "ultra" ? 60 : quality === "fast" ? 24 : 30;
  const { w, h } = base[aspect];
  return { width: Math.round((w * scale) / 2) * 2, height: Math.round((h * scale) / 2) * 2, fps };
}

export function aspectFromResolution(width: number, height: number): Aspect {
  if (width === height) return "1:1";
  return width > height ? "16:9" : "9:16";
}
