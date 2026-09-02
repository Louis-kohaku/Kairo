export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) seconds = 0;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}

// How the currently-configured LLM model was chosen (design doc section 4's
// selection priority) - shown next to the model id wherever it's displayed,
// so "why is this the model" never requires digging into settings.
export const MODEL_SOURCE_LABELS: Record<string, string> = {
  env: "環境変数で指定",
  user: "手動選択",
  auto: "自動選択",
  fallback: "自動選択(暫定)",
  none: "未解決",
};

export function formatMinuteRange(low: number, high: number): string {
  const fmt = (m: number) => (m < 1 ? "1分未満" : `${Math.round(m)}分`);
  if (Math.round(low) === Math.round(high)) return `約${fmt(high)}`;
  return `約${fmt(low)}〜${fmt(high)}`;
}

export function formatSecondsRangeAsMinutes(lowSeconds: number, highSeconds: number): string {
  return formatMinuteRange(lowSeconds / 60, highSeconds / 60);
}
