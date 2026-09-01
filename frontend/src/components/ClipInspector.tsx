import { useEffect, useState } from "react";
import type { Clip, MediaAsset } from "../types";

interface Props {
  clip: Clip | null;
  asset: MediaAsset | null;
  onUpdate: (patch: Partial<Pick<Clip, "in_point" | "out_point" | "volume">>) => void;
  onDelete: () => void;
  onSplitHere: () => void;
}

export default function ClipInspector({
  clip,
  asset,
  onUpdate,
  onDelete,
  onSplitHere,
}: Props) {
  const [inPoint, setInPoint] = useState(0);
  const [outPoint, setOutPoint] = useState(0);
  const [volume, setVolume] = useState(1);

  useEffect(() => {
    if (clip) {
      setInPoint(clip.in_point);
      setOutPoint(clip.out_point);
      setVolume(clip.volume);
    }
  }, [clip?.id, clip?.in_point, clip?.out_point, clip?.volume]);

  if (!clip) {
    return (
      <div className="clip-inspector">
        <div className="panel-header">
          <span>クリップ</span>
        </div>
        <div style={{ color: "var(--text-dim)", fontSize: 13, padding: 8 }}>
          タイムラインでクリップを選択してください
        </div>
      </div>
    );
  }

  const maxDuration = asset?.duration ?? outPoint;

  return (
    <div className="clip-inspector">
      <div className="panel-header">
        <span>クリップ</span>
        <button className="danger" onClick={onDelete}>
          削除
        </button>
      </div>
      <div style={{ fontSize: 12, color: "var(--text-dim)", padding: "0 8px" }}>
        {asset?.original_filename}
      </div>

      <label className="inspector-field">
        イン点 (秒)
        <input
          type="number"
          step={0.1}
          min={0}
          max={outPoint - 0.1}
          value={inPoint.toFixed(2)}
          onChange={(e) => setInPoint(Number(e.target.value))}
          onBlur={() => onUpdate({ in_point: inPoint })}
        />
      </label>

      <label className="inspector-field">
        アウト点 (秒)
        <input
          type="number"
          step={0.1}
          min={inPoint + 0.1}
          max={maxDuration}
          value={outPoint.toFixed(2)}
          onChange={(e) => setOutPoint(Number(e.target.value))}
          onBlur={() => onUpdate({ out_point: outPoint })}
        />
      </label>

      <label className="inspector-field">
        音量 ({Math.round(volume * 100)}%)
        <input
          type="range"
          min={0}
          max={2}
          step={0.05}
          value={volume}
          onChange={(e) => {
            const v = Number(e.target.value);
            setVolume(v);
            onUpdate({ volume: v });
          }}
        />
      </label>

      <button onClick={onSplitHere}>再生位置で分割</button>
    </div>
  );
}
