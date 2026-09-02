import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Clip, MediaAsset } from "../types";
import { layoutClips, findClipAt } from "../utils/timelineMath";

interface Props {
  clips: Clip[];
  assets: Record<string, MediaAsset>;
  playhead: number;
  isPlaying: boolean;
  seekNonce: number;
  onTimeUpdate: (t: number) => void;
  onEnded: () => void;
  subtitleText?: string | null;
}

export default function PreviewPlayer({
  clips,
  assets,
  playhead,
  isPlaying,
  seekNonce,
  onTimeUpdate,
  onEnded,
  subtitleText,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [activeClipId, setActiveClipId] = useState<string | null>(null);

  const positioned = layoutClips(clips);
  const current = findClipAt(positioned, playhead);
  const asset = current ? assets[current.clip.media_asset_id] : undefined;

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !current) return;

    const localTime = current.clip.in_point + (playhead - current.start);
    const isNewClip = activeClipId !== current.clip.id;
    if (isNewClip) setActiveClipId(current.clip.id);

    video.volume = Math.min(1, Math.max(0, current.clip.volume ?? 1));

    const applySeek = () => {
      if (isNewClip) {
        // Assigned unconditionally when the clip changes, and nudged off
        // zero: at the very start of a video the target time and the
        // element's currentTime are both 0, so the guarded assignment
        // below is skipped, no seek is ever requested, and Chrome leaves
        // the player black until the user scrubs. A 1ms offset is
        // imperceptible and forces the first frame to be decoded.
        video.currentTime = Math.max(localTime, 0.001);
      } else if (Math.abs(video.currentTime - localTime) > 0.05) {
        video.currentTime = localTime;
      }
      if (isPlaying) video.play().catch(() => {});
    };

    if (isNewClip) {
      video.addEventListener("loadedmetadata", applySeek, { once: true });
    } else {
      applySeek();
    }
    if (!isPlaying) video.pause();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seekNonce, current?.clip.id]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (isPlaying) video.play().catch(() => {});
    else video.pause();
  }, [isPlaying]);

  const handleTimeUpdate = () => {
    const video = videoRef.current;
    if (!video || !current) return;
    const local = video.currentTime;

    if (local >= current.clip.out_point - 0.03) {
      const idx = positioned.findIndex((p) => p.clip.id === current.clip.id);
      const next = positioned[idx + 1];
      if (next) {
        onTimeUpdate(next.start);
      } else {
        onEnded();
      }
      return;
    }
    onTimeUpdate(current.start + (local - current.clip.in_point));
  };

  return (
    <div className="preview-player">
      {asset ? (
        <video
          key="preview-video"
          ref={videoRef}
          src={api.mediaFileUrl(asset.id)}
          preload="auto"
          onTimeUpdate={handleTimeUpdate}
          onEnded={onEnded}
          style={{ width: "100%", height: "100%", background: "#000" }}
        />
      ) : (
        <div className="preview-empty">
          タイムラインに動画クリップを追加するとここにプレビューが表示されます
        </div>
      )}
      {subtitleText && <div className="preview-subtitle-overlay">{subtitleText}</div>}
    </div>
  );
}
