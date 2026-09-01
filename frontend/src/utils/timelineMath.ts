import type { Clip } from "../types";

export interface PositionedClip {
  clip: Clip;
  start: number;
  end: number;
}

export function layoutClips(clips: Clip[]): PositionedClip[] {
  const sorted = [...clips].sort((a, b) => a.order_index - b.order_index);
  let cursor = 0;
  return sorted.map((clip) => {
    const duration = Math.max(0, clip.out_point - clip.in_point);
    const start = cursor;
    cursor += duration;
    return { clip, start, end: cursor };
  });
}

export function findClipAt(
  positioned: PositionedClip[],
  time: number,
): PositionedClip | undefined {
  return (
    positioned.find((p) => time >= p.start && time < p.end) ??
    (time > 0 ? positioned[positioned.length - 1] : positioned[0])
  );
}

export function indexAtTime(positioned: PositionedClip[], time: number): number {
  const idx = positioned.findIndex((p) => time < p.end);
  return idx === -1 ? positioned.length : idx;
}
