import type { MediaAsset, SubtitleCue, Track } from "../types";
import { formatTime } from "../utils/format";
import { indexAtTime, layoutClips } from "../utils/timelineMath";

const PX_PER_SECOND = 60;
const MIN_DURATION = 0.5;

interface Props {
  tracks: Track[];
  assets: Record<string, MediaAsset>;
  playhead: number;
  selectedClipId: string | null;
  onSeek: (time: number) => void;
  onSelectClip: (clipId: string | null) => void;
  onDropAsset: (trackId: string, assetId: string, index: number) => void;
  onDeleteClip: (clipId: string) => void;
  subtitleCues?: SubtitleCue[];
}

export default function Timeline({
  tracks,
  assets,
  playhead,
  selectedClipId,
  onSeek,
  onSelectClip,
  onDropAsset,
  onDeleteClip,
  subtitleCues = [],
}: Props) {
  const totalDuration = Math.max(
    MIN_DURATION,
    ...tracks.map((t) => layoutClips(t.clips).at(-1)?.end ?? 0),
    ...subtitleCues.map((c) => c.end),
  );
  const rulerWidth = totalDuration * PX_PER_SECOND;

  const timeFromClientX = (container: HTMLElement, clientX: number): number => {
    const rect = container.getBoundingClientRect();
    const x = clientX - rect.left + container.scrollLeft;
    return Math.max(0, x / PX_PER_SECOND);
  };

  return (
    <div className="timeline">
      <div
        className="timeline-ruler"
        style={{ width: rulerWidth }}
        onClick={(e) => onSeek(timeFromClientX(e.currentTarget, e.clientX))}
      >
        {Array.from({ length: Math.ceil(totalDuration) + 1 }, (_, s) => (
          <div
            key={s}
            className="timeline-tick"
            style={{ left: s * PX_PER_SECOND }}
          >
            {s % 5 === 0 ? formatTime(s) : ""}
          </div>
        ))}
        <div
          className="timeline-playhead"
          style={{ left: playhead * PX_PER_SECOND }}
        />
      </div>

      {tracks.map((track) => {
        const positioned = layoutClips(track.clips);
        return (
          <div
            key={track.id}
            className={`timeline-track timeline-track-${track.type}`}
            style={{ width: Math.max(rulerWidth, 200) }}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const assetId = e.dataTransfer.getData("application/x-kairo-asset");
              if (!assetId) return;
              const time = timeFromClientX(e.currentTarget, e.clientX);
              onDropAsset(track.id, assetId, indexAtTime(positioned, time));
            }}
            onClick={(e) => {
              if (e.target === e.currentTarget) {
                onSeek(timeFromClientX(e.currentTarget, e.clientX));
                onSelectClip(null);
              }
            }}
          >
            <div className="track-label">{track.name}</div>
            {positioned.map(({ clip, start, end }) => {
              const asset = assets[clip.media_asset_id];
              return (
                <div
                  key={clip.id}
                  className={`timeline-clip${
                    clip.id === selectedClipId ? " selected" : ""
                  }`}
                  style={{
                    left: start * PX_PER_SECOND,
                    width: Math.max(4, (end - start) * PX_PER_SECOND - 2),
                  }}
                  onClick={(e) => {
                    e.stopPropagation();
                    onSelectClip(clip.id);
                    onSeek(start);
                  }}
                >
                  <span className="timeline-clip-label">
                    {asset?.original_filename ?? clip.media_asset_id}
                  </span>
                  <button
                    className="timeline-clip-delete"
                    title="削除"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteClip(clip.id);
                    }}
                  >
                    &times;
                  </button>
                </div>
              );
            })}
            {track.clips.length === 0 && (
              <div className="track-empty-hint">
                メディアをドラッグ&ドロップ
              </div>
            )}
          </div>
        );
      })}

      {subtitleCues.length > 0 && (
        <div className="timeline-track timeline-track-subtitle" style={{ width: Math.max(rulerWidth, 200) }}>
          <div className="track-label">字幕</div>
          {subtitleCues.map((cue) => (
            <div
              key={cue.id}
              className="timeline-clip timeline-subtitle-clip"
              style={{
                left: cue.start * PX_PER_SECOND,
                width: Math.max(4, (cue.end - cue.start) * PX_PER_SECOND - 2),
              }}
              title={cue.text}
              onClick={(e) => {
                e.stopPropagation();
                onSeek(cue.start);
              }}
            >
              <span className="timeline-clip-label">{cue.text}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export { PX_PER_SECOND };
