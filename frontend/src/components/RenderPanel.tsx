import { useState } from "react";
import { api } from "../api/client";
import { useJobPolling } from "../hooks/useJobPolling";

interface Props {
  projectId: string;
  hasVideoClips: boolean;
  hasSubtitles: boolean;
}

export default function RenderPanel({ projectId, hasVideoClips, hasSubtitles }: Props) {
  const { job, error, setError, track, isBusy } = useJobPolling();
  const [burnSubtitles, setBurnSubtitles] = useState(false);

  const handleRender = async () => {
    setError(null);
    try {
      const started = await api.startRender(projectId, burnSubtitles && hasSubtitles);
      track(started);
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div className="render-panel">
      {hasSubtitles && (
        <label className="burn-subtitles-toggle">
          <input
            type="checkbox"
            checked={burnSubtitles}
            onChange={(e) => setBurnSubtitles(e.target.checked)}
          />
          字幕を焼き込む
        </label>
      )}

      <button
        className="primary"
        onClick={handleRender}
        disabled={!hasVideoClips || isBusy}
      >
        {isBusy ? "書き出し中..." : "書き出し (レンダリング)"}
      </button>

      {job && (
        <div className="render-status">
          <div className="render-progress-bar">
            <div
              className="render-progress-fill"
              style={{ width: `${job.progress}%` }}
            />
          </div>
          <div className="render-message">
            {job.message || job.status} ({job.progress.toFixed(0)}%)
          </div>
          {job.status === "completed" && (
            <a
              href={api.downloadUrl(job.id)}
              target="_blank"
              rel="noreferrer"
              className="render-download-link"
            >
              完成した動画を開く / ダウンロード
            </a>
          )}
          {job.status === "failed" && (
            <div style={{ color: "var(--danger)" }}>
              失敗しました: {job.error}
            </div>
          )}
        </div>
      )}
      {error && <div style={{ color: "var(--danger)" }}>{error}</div>}
    </div>
  );
}
