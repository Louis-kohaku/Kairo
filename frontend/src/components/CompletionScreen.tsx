import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Job, Project } from "../types";
import { aspectRatioLabel, formatBytes, formatClock } from "../utils/format";

interface Props {
  job: Job;
  project: Project;
  totalDurationSeconds: number;
  burnSubtitles: boolean;
  onBackToEdit: () => void;
  onRerender: () => void;
}

type SaveState = "idle" | "saving" | "done" | "error";

// Parses a filename out of a Content-Disposition header - the download
// endpoint sets this to the actual "提出用" filename
// (kairo_<project>_<date>.mp4), so reading it back here keeps the UI's
// displayed name and the file the browser actually saves in sync. Project
// names are usually Japanese, so FastAPI's FileResponse encodes them as the
// RFC 5987 `filename*=UTF-8''<percent-encoded>` form rather than a plain
// `filename="..."` - both are checked here.
function filenameFromContentDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback;
  const extended = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (extended) {
    try {
      return decodeURIComponent(extended[1]);
    } catch {
      // fall through to the plain form below
    }
  }
  const plain = header.match(/filename="?([^";]+)"?/);
  return plain ? plain[1] : fallback;
}

export default function CompletionScreen({
  job,
  project,
  totalDurationSeconds,
  burnSubtitles,
  onBackToEdit,
  onRerender,
}: Props) {
  const [fileSize, setFileSize] = useState<number | null>(null);
  const [filename, setFilename] = useState(`${job.id}.mp4`);
  const [playbackConfirmed, setPlaybackConfirmed] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveProgress, setSaveProgress] = useState(0);
  const [saveError, setSaveError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  const downloadUrl = api.downloadUrl(job.id);
  const isVertical = project.height > project.width;

  useEffect(() => {
    fetch(downloadUrl, { method: "HEAD" })
      .then((res) => {
        const len = res.headers.get("content-length");
        if (len) setFileSize(Number(len));
        setFilename(filenameFromContentDisposition(res.headers.get("content-disposition"), `${job.id}.mp4`));
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.id]);

  const handleSave = async () => {
    setSaveState("saving");
    setSaveError(null);
    setSaveProgress(0);
    try {
      const res = await fetch(downloadUrl);
      if (!res.ok || !res.body) throw new Error(`ダウンロードに失敗しました (${res.status})`);
      const total = Number(res.headers.get("content-length") ?? fileSize ?? 0);
      const reader = res.body.getReader();
      const chunks: Uint8Array[] = [];
      let received = 0;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        if (value) {
          chunks.push(value);
          received += value.length;
          if (total > 0) setSaveProgress(Math.min(99, Math.round((received / total) * 100)));
        }
      }
      const blob = new Blob(chunks as BlobPart[], { type: "video/mp4" });
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objectUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(objectUrl);
      setSaveProgress(100);
      setSaveState("done");
    } catch (e) {
      setSaveError(String(e));
      setSaveState("error");
    }
  };

  return (
    <div className="completion-screen">
      <div className="completion-header">
        <span className="completion-header-icon">🎉</span>
        <h1>動画が完成しました！</h1>
      </div>

      <div className={`completion-preview-frame${isVertical ? " completion-preview-vertical" : ""}`}>
        {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
        <video
          ref={videoRef}
          src={downloadUrl}
          controls
          onCanPlay={() => setPlaybackConfirmed(true)}
        />
      </div>

      <div className="completion-title">{project.name}</div>
      <div className="completion-meta-row">
        <span>{formatClock(totalDurationSeconds)}</span>
        <span>
          {project.width} × {project.height} ({aspectRatioLabel(project.width, project.height)})
        </span>
        <span>{project.fps}fps</span>
        <span>MP4 / H.264</span>
      </div>
      {fileSize !== null && <div className="completion-filesize">ファイルサイズ: {formatBytes(fileSize)}</div>}

      <div className="completion-actions">
        <button
          className="primary completion-save-btn"
          onClick={handleSave}
          disabled={saveState === "saving"}
        >
          {saveState === "saving" ? "保存中..." : saveState === "done" ? "✓ 保存済み - もう一度保存" : "⬇ MP4を保存"}
        </button>
        <button onClick={() => videoRef.current?.play()}>▶ 再生</button>
        <button onClick={onBackToEdit}>✏ 編集に戻る</button>
        <button onClick={onRerender}>🔄 再生成</button>
      </div>

      {saveState === "saving" && (
        <div className="completion-save-progress">
          <div className="render-progress-bar">
            <div className="render-progress-fill" style={{ width: `${saveProgress}%` }} />
          </div>
          <span>{saveProgress < 100 ? "MP4を準備しています..." : "まもなく保存できます"}</span>
        </div>
      )}
      {saveState === "done" && <div className="completion-save-done">✓ MP4を保存しました</div>}
      {saveState === "error" && <div className="completion-save-error">保存に失敗しました: {saveError}</div>}

      <div className="completion-panels">
        <div className="completion-panel">
          <div className="panel-header">提出用ファイル</div>
          <div className="completion-submission-filename">{filename}</div>
          <ul className="completion-checklist">
            <li className="ok">✓ MP4</li>
            <li className="ok">✓ H.264</li>
            <li className="ok">
              ✓ {project.width} × {project.height}
            </li>
            <li className="ok">✓ {project.fps}fps</li>
            <li className="ok">✓ 音声正常 (AAC)</li>
            {burnSubtitles && <li className="ok">✓ 字幕焼き込み済み</li>}
            <li className={playbackConfirmed ? "ok" : "warn"}>
              {playbackConfirmed ? "✓ 再生確認済み" : "○ 再生確認待ち(再生ボタンを押してください)"}
            </li>
          </ul>
        </div>

        <div className="completion-panel">
          <div className="panel-header">動画情報</div>
          <dl className="completion-info-list">
            <dt>タイトル</dt>
            <dd>{project.name}</dd>
            <dt>ファイル形式</dt>
            <dd>MP4</dd>
            <dt>コーデック</dt>
            <dd>H.264</dd>
            <dt>音声</dt>
            <dd>AAC</dd>
            <dt>解像度</dt>
            <dd>
              {project.width} × {project.height}
            </dd>
            <dt>FPS</dt>
            <dd>{project.fps}</dd>
            <dt>長さ</dt>
            <dd>{formatClock(totalDurationSeconds)}</dd>
            <dt>ファイルサイズ</dt>
            <dd>{fileSize !== null ? formatBytes(fileSize) : "取得中..."}</dd>
          </dl>
        </div>
      </div>
    </div>
  );
}
