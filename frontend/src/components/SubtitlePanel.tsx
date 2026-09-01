import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Diagnosis, SubtitleCue } from "../types";
import { useJobPolling } from "../hooks/useJobPolling";
import { formatTime } from "../utils/format";
import AIErrorPanel from "./AIErrorPanel";

function parseDiagnosis(raw: string | null): Diagnosis | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Diagnosis;
  } catch {
    return null;
  }
}

interface Props {
  projectId: string;
  hasVideoClips: boolean;
  onSeek: (time: number) => void;
  onCuesChanged: (cues: SubtitleCue[]) => void;
  refreshToken?: number;
}

export default function SubtitlePanel({
  projectId,
  hasVideoClips,
  onSeek,
  onCuesChanged,
  refreshToken,
}: Props) {
  const { job, error, setError, track, isBusy } = useJobPolling();
  const [cues, setCues] = useState<SubtitleCue[]>([]);

  const refresh = () => {
    api
      .listSubtitles(projectId)
      .then((c) => {
        setCues(c);
        onCuesChanged(c);
      })
      .catch((e) => setError(String(e)));
  };

  useEffect(refresh, [projectId, refreshToken]);

  useEffect(() => {
    if (job?.status === "completed") refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.status]);

  const handleGenerate = async () => {
    setError(null);
    try {
      const started = await api.generateSubtitles(projectId);
      track(started);
    } catch (e) {
      setError(String(e));
    }
  };

  const handleTextChange = async (cueId: string, text: string) => {
    setCues((prev) => prev.map((c) => (c.id === cueId ? { ...c, text } : c)));
    try {
      await api.updateSubtitle(cueId, { text });
    } catch (e) {
      setError(String(e));
    }
  };

  const handleDelete = async (cueId: string) => {
    try {
      await api.deleteSubtitle(cueId);
      refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div className="subtitle-panel">
      <div className="panel-header">
        <span>字幕</span>
        <button onClick={handleGenerate} disabled={!hasVideoClips || isBusy}>
          {isBusy ? "生成中..." : "AIで字幕生成"}
        </button>
      </div>

      {job && (
        <div className="render-status" style={{ padding: "6px 12px" }}>
          <div className="render-progress-bar">
            <div className="render-progress-fill" style={{ width: `${job.progress}%` }} />
          </div>
          <span style={{ fontSize: 11 }}>{job.message} ({job.progress.toFixed(0)}%)</span>
        </div>
      )}
      {job?.status === "failed" && parseDiagnosis(job.error_detail) && (
        <AIErrorPanel diagnosis={parseDiagnosis(job.error_detail)!} jobId={job.id} onRetry={handleGenerate} />
      )}
      {error && <div style={{ color: "var(--danger)", fontSize: 12, padding: "0 12px" }}>{error}</div>}

      <div className="subtitle-list">
        {cues.map((cue) => (
          <div key={cue.id} className="subtitle-cue">
            <button
              className="subtitle-cue-time"
              onClick={() => onSeek(cue.start)}
              title="この位置へ移動"
            >
              {formatTime(cue.start)} - {formatTime(cue.end)}
            </button>
            <input
              type="text"
              value={cue.text}
              onChange={(e) => handleTextChange(cue.id, e.target.value)}
            />
            <button className="danger" onClick={() => handleDelete(cue.id)}>
              &times;
            </button>
          </div>
        ))}
        {cues.length === 0 && !isBusy && (
          <div style={{ color: "var(--text-dim)", fontSize: 12, padding: 8 }}>
            字幕はまだありません
          </div>
        )}
      </div>

      {cues.length > 0 && (
        <a
          className="subtitle-srt-link"
          href={api.srtUrl(projectId)}
          target="_blank"
          rel="noreferrer"
        >
          SRTを書き出し
        </a>
      )}
    </div>
  );
}
