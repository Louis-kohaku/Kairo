import { useEffect, useState } from "react";
import type { Diagnosis, Job } from "../types";
import { formatClock } from "../utils/format";
import AIErrorPanel from "./AIErrorPanel";

interface Props {
  job: Job;
  projectName: string;
  clipCount: number;
  hasBgm: boolean;
  burnSubtitles: boolean;
  ffmpegAvailable: boolean;
  onRetry: () => void;
  onCheckSettings: () => void;
}

function parseDiagnosis(raw: string | null): Diagnosis | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Diagnosis;
  } catch {
    return null;
  }
}

// "Segment 3/12" -> [3, 12]. The render job reports progress as free-form
// text (see render_service.py's _update_job messages), so this is the only
// way the UI can know which scene is currently being processed.
function parseSegmentProgress(message: string): [number, number] | null {
  const m = message.match(/Segment (\d+)\/(\d+)/);
  if (!m) return null;
  return [Number(m[1]), Number(m[2])];
}

interface ChecklistItem {
  key: string;
  label: string;
  state: "done" | "current" | "pending";
}

function buildChecklist(job: Job, clipCount: number, hasBgm: boolean, burnSubtitles: boolean): ChecklistItem[] {
  const items: ChecklistItem[] = [];
  const segProgress = parseSegmentProgress(job.message);
  const step = job.step ?? "";
  const started = job.progress > 0 || job.status !== "pending";

  items.push({
    key: "prepare",
    label: "シーン素材準備",
    state: started ? "done" : job.status === "pending" ? "current" : "pending",
  });

  // "Segment X/N" in job.message means X segments have fully finished and
  // (if X<N) segment X+1 (0-indexed: index X) is the one currently
  // encoding - see render_service.run_render's per-clip loop.
  const isSegmentPhase = step === "segment_normalization";
  const doneCount = isSegmentPhase ? segProgress?.[0] ?? 0 : job.progress >= 70 || job.status === "completed" ? clipCount : 0;

  for (let i = 0; i < clipCount; i++) {
    let state: ChecklistItem["state"] = "pending";
    if (i < doneCount) state = "done";
    else if (i === doneCount && isSegmentPhase) state = "current";
    items.push({ key: `scene-${i}`, label: `シーン${i + 1}`, state });
  }

  items.push({
    key: "concat",
    label: "シーン結合",
    state: step === "concat" ? "current" : job.progress > 75 || job.status === "completed" ? "done" : "pending",
  });

  if (hasBgm) {
    items.push({
      key: "audio_mix",
      label: "音声合成",
      state: step === "audio_mix" ? "current" : job.progress > 90 || job.status === "completed" ? "done" : "pending",
    });
  }

  if (burnSubtitles) {
    items.push({
      key: "subtitle_burn",
      label: "字幕を合成",
      state: step === "subtitle_burn" ? "current" : job.status === "completed" ? "done" : "pending",
    });
  }

  items.push({
    key: "finalize",
    label: "最終エンコード",
    state: job.status === "completed" ? "done" : job.progress >= 96 ? "current" : "pending",
  });

  return items;
}

const STEP_TEXT: Record<string, string> = {
  segment_normalization: "シーン素材を変換しています...",
  concat: "シーンを結合しています...",
  audio_mix: "音声を合成しています...",
  subtitle_burn: "字幕を合成しています...",
};

export default function RenderScreen({
  job,
  projectName,
  clipCount,
  hasBgm,
  burnSubtitles,
  ffmpegAvailable,
  onRetry,
  onCheckSettings,
}: Props) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (job.status !== "running" && job.status !== "pending") return;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [job.status]);

  const failedDiagnosis: Diagnosis | null =
    job.status === "failed"
      ? parseDiagnosis(job.error_detail) ?? {
          summary: job.error ?? "動画の生成に失敗しました",
          cause_known: false,
          cause: "原因を特定できませんでした。",
          category: "unknown",
          facts: [],
          candidates: [],
          suggestions: [],
          ai_context: null,
          step: job.step,
          retryable: true,
          raw_error: job.error ?? "",
          error_code: "",
        }
      : null;
  const elapsedSeconds = Math.max(0, (now - new Date(job.created_at).getTime()) / 1000);
  const remainingSeconds =
    job.progress > 3 && job.status === "running" ? (elapsedSeconds / job.progress) * (100 - job.progress) : null;

  const checklist = buildChecklist(job, clipCount, hasBgm, burnSubtitles);
  const segDone = parseSegmentProgress(job.message);
  const currentSceneNumber =
    job.step === "segment_normalization" ? Math.min((segDone?.[0] ?? 0) + 1, clipCount) : null;
  const currentStepText = STEP_TEXT[job.step ?? ""] ?? job.message;

  if (job.status === "failed" && failedDiagnosis !== null) {
    return (
      <div className="render-screen render-screen-failed">
        <div className="render-screen-header">
          <span className="render-screen-fail-icon">⚠</span>
          <h2>動画の生成に失敗しました</h2>
        </div>
        {!ffmpegAvailable && (
          <div className="render-screen-ffmpeg-missing">
            FFmpegが必要です。設定からFFmpegをインストールしてください。
          </div>
        )}
        <AIErrorPanel diagnosis={failedDiagnosis} jobId={job.id} onRetry={onRetry} />
        <div className="render-screen-actions">
          <button className="primary" onClick={onRetry} disabled={!failedDiagnosis.retryable}>
            再試行
          </button>
          <button onClick={onCheckSettings}>設定を確認</button>
        </div>
      </div>
    );
  }

  return (
    <div className="render-screen">
      <div className="render-screen-header">
        <span>🎬 動画を作成しています</span>
        <h2>{projectName}</h2>
      </div>

      <div className="render-screen-progress-bar">
        <div className="render-screen-progress-fill" style={{ width: `${job.progress}%` }} />
      </div>
      <div className="render-screen-percent">{job.progress.toFixed(0)}%</div>

      {currentSceneNumber !== null && (
        <div className="render-screen-scene-counter">
          Scene {currentSceneNumber} / {clipCount}
        </div>
      )}

      <div className="render-screen-current">
        <span className="video-settings-label">現在の処理</span>
        <span>{currentStepText}</span>
      </div>

      <div className="render-screen-times">
        <div>
          <span className="video-settings-label">経過時間</span>
          <span>{formatClock(elapsedSeconds)}</span>
        </div>
        <div>
          <span className="video-settings-label">推定残り時間</span>
          <span>{remainingSeconds !== null ? formatClock(remainingSeconds) : "計算中..."}</span>
        </div>
      </div>

      <div className="render-screen-preview-placeholder">
        {currentSceneNumber !== null ? (
          <>
            <div className="render-screen-preview-scene-num">Scene {currentSceneNumber}</div>
            <div className="generation-engine-reason">{currentStepText}</div>
          </>
        ) : (
          <div className="generation-engine-reason">{currentStepText}</div>
        )}
      </div>

      <div className="render-screen-checklist">
        <div className="panel-header">処理状況</div>
        {checklist.map((item) => (
          <div key={item.key} className={`render-screen-checklist-item render-screen-checklist-${item.state}`}>
            <span>{item.state === "done" ? "✓" : item.state === "current" ? "●" : "○"}</span>
            <span>{item.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
