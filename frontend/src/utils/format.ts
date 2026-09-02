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

export function formatRelativeDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "-";
  const now = new Date();
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const dayDiff = Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000);
  if (dayDiff === 0) return "今日";
  if (dayDiff === 1) return "昨日";
  if (dayDiff > 1 && dayDiff < 7) return `${dayDiff}日前`;
  return date.toLocaleDateString("ja-JP", { year: "numeric", month: "numeric", day: "numeric" });
}

export function aspectRatioLabel(width: number, height: number): string {
  if (width === height) return "1:1";
  if (width > height) return "16:9";
  return "9:16";
}
