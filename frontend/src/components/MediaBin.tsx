import { useRef, useState } from "react";
import { api } from "../api/client";
import type { MediaAsset } from "../types";
import { formatTime } from "../utils/format";

interface Props {
  projectId: string;
  assets: MediaAsset[];
  onUploaded: (asset: MediaAsset) => void;
  onAddToTrack: (assetId: string, trackType: "video" | "audio") => void;
  onDetectSilence: (asset: MediaAsset) => void;
}

export default function MediaBin({
  projectId,
  assets,
  onUploaded,
  onAddToTrack,
  onDetectSilence,
}: Props) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploading(true);
    setError(null);
    try {
      for (const file of Array.from(files)) {
        const asset = await api.uploadMedia(projectId, file);
        onUploaded(asset);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  return (
    <div className="media-bin">
      <div className="panel-header">
        <span>メディア</span>
        <button onClick={() => fileInput.current?.click()} disabled={uploading}>
          {uploading ? "取込中..." : "+ 読み込み"}
        </button>
        <input
          ref={fileInput}
          type="file"
          accept="video/*,audio/*"
          multiple
          hidden
          onChange={(e) => handleFiles(e.target.files)}
        />
      </div>

      {error && <div style={{ color: "var(--danger)", fontSize: 12 }}>{error}</div>}

      <div className="media-list">
        {assets.map((asset) => (
          <div
            key={asset.id}
            className="media-item"
            draggable
            onDragStart={(e) => {
              e.dataTransfer.setData("application/x-kairo-asset", asset.id);
              e.dataTransfer.effectAllowed = "copy";
            }}
          >
            <div className="media-item-name" title={asset.original_filename}>
              {asset.kind === "video"
                ? "\u{1F3AC}"
                : asset.kind === "image"
                  ? "\u{1F5BC}"
                  : "\u{1F3B5}"}{" "}
              {asset.original_filename}
            </div>
            <div className="media-item-meta">
              {formatTime(asset.duration)}
              {asset.width ? ` · ${asset.width}x${asset.height}` : ""}
            </div>
            <div className="media-item-actions">
              {asset.kind === "image" ? (
                <span style={{ color: "var(--text-dim)", fontSize: 12 }}>
                  写真はオートモードの素材として使えます
                </span>
              ) : (
                <button onClick={() => onAddToTrack(asset.id, "video")}>
                  映像トラックへ
                </button>
              )}
              {asset.has_audio && (
                <button onClick={() => onAddToTrack(asset.id, "audio")}>
                  BGMへ
                </button>
              )}
              {asset.has_audio && (
                <button onClick={() => onDetectSilence(asset)}>無音カット</button>
              )}
            </div>
          </div>
        ))}
        {assets.length === 0 && (
          <div style={{ color: "var(--text-dim)", fontSize: 13, padding: 8 }}>
            動画・音声ファイルを読み込んでください
          </div>
        )}
      </div>
    </div>
  );
}
