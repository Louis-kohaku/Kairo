import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Diagnosis, EngineCapabilities, Generation } from "../types";
import { useJobPolling } from "../hooks/useJobPolling";
import AIErrorPanel from "./AIErrorPanel";

interface Props {
  projectId: string;
  onCompleted: () => void;
}

const ENGINE_STATUS_LABEL: Record<EngineCapabilities["status"], string> = {
  ready: "🟢 準備完了",
  not_downloaded: "🟡 未ダウンロード(初回生成時に取得)",
  not_recommended: "🟠 非推奨(スペック不足の可能性)",
};

function parseDiagnosis(raw: string | null): Diagnosis | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Diagnosis;
  } catch {
    return null;
  }
}

export default function GenerationPanel({ projectId, onCompleted }: Props) {
  const { job, error, setError, track, isBusy } = useJobPolling();
  const [engines, setEngines] = useState<EngineCapabilities[]>([]);
  const [engineId, setEngineId] = useState("svd");
  const [prompt, setPrompt] = useState("");
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreviewUrl, setImagePreviewUrl] = useState<string | null>(null);
  const [history, setHistory] = useState<Generation[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const engine = engines.find((e) => e.id === engineId) ?? null;

  const refreshHistory = () =>
    api.listGenerations(projectId).then(setHistory).catch(() => {});

  useEffect(() => {
    api.listGenerationEngines().then(setEngines).catch((e) => setError(String(e)));
    api
      .getSettings()
      .then((s) => {
        if (s.generation.default_engine_id) setEngineId(s.generation.default_engine_id);
      })
      .catch(() => {});
    refreshHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  useEffect(() => {
    if (job?.status === "completed" || job?.status === "failed") {
      refreshHistory();
    }
    if (job?.status === "completed") {
      onCompleted();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.status]);

  const handlePickFile = (file: File | null) => {
    setImageFile(file);
    setImagePreviewUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return file ? URL.createObjectURL(file) : null;
    });
  };

  const handleGenerate = async () => {
    if (!imageFile) return;
    setError(null);
    try {
      const started = await api.generateImageToVideo(projectId, imageFile, {
        prompt,
        engineId,
      });
      track(started);
    } catch (e) {
      setError(String(e));
    }
  };

  const failedDiagnosis = job?.status === "failed" ? parseDiagnosis(job.error_detail) : null;

  return (
    <div className="generation-panel">
      <div className="generation-form">
        <div
          className="generation-dropzone"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const file = e.dataTransfer.files[0];
            if (file) handlePickFile(file);
          }}
          onClick={() => fileInputRef.current?.click()}
        >
          {imagePreviewUrl ? (
            <img src={imagePreviewUrl} alt="入力画像プレビュー" />
          ) : (
            <span>画像をドラッグ&ドロップ、またはクリックして選択(JPG/PNG/WebP)</span>
          )}
          <input
            ref={fileInputRef}
            type="file"
            accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"
            hidden
            onChange={(e) => handlePickFile(e.target.files?.[0] ?? null)}
          />
        </div>

        <div className="generation-controls">
          <label className="scene-field">
            エンジン
            <select value={engineId} onChange={(e) => setEngineId(e.target.value)}>
              {engines.map((eng) => (
                <option key={eng.id} value={eng.id}>
                  {eng.display_name}
                </option>
              ))}
            </select>
          </label>

          {engine && (
            <div className="generation-engine-info">
              <span>{ENGINE_STATUS_LABEL[engine.status]}</span>
              <span className="generation-engine-reason">{engine.status_reason}</span>
              {!engine.commercial_use && (
                <span className="generation-engine-reason" style={{ color: "var(--warning)" }}>
                  ⚠ 非商用ライセンスです({engine.license})
                </span>
              )}
              {!engine.prompt_conditioned && (
                <span className="generation-engine-reason" style={{ color: "var(--warning)" }}>
                  ⚠ このエンジンはテキストプロンプトに対応していません(入力画像のみから生成されます)
                </span>
              )}
              {engine.estimate_low_seconds != null && engine.estimate_high_seconds != null && (
                <span className="generation-engine-reason">
                  推定生成時間: 約{Math.round(engine.estimate_low_seconds / 60)}〜
                  {Math.round(engine.estimate_high_seconds / 60)}分(このPC・軽量設定での推定値、CPU実行のため長め)
                </span>
              )}
            </div>
          )}

          <label className="scene-field">
            プロンプト{engine && !engine.prompt_conditioned ? "(このエンジンでは無視されます)" : ""}
            <textarea
              rows={2}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="例: 猫がこちらを見て尻尾を動かす"
              disabled={isBusy}
            />
          </label>

          <button
            className="primary"
            onClick={handleGenerate}
            disabled={isBusy || !imageFile}
          >
            {isBusy ? "生成中..." : "Generate"}
          </button>
        </div>
      </div>

      {job && (
        <div className="generation-job-status">
          <div className="render-progress-bar">
            <div className="render-progress-fill" style={{ width: `${job.progress}%` }} />
          </div>
          <span>
            {job.status === "failed"
              ? failedDiagnosis?.summary ?? job.message
              : `${job.message || job.status} (${job.progress.toFixed(0)}%)`}
          </span>
        </div>
      )}

      {failedDiagnosis && (
        <AIErrorPanel diagnosis={failedDiagnosis} jobId={job?.id} onRetry={handleGenerate} />
      )}

      {error && <div style={{ color: "var(--danger)", padding: "0 16px" }}>{error}</div>}

      {history.length > 0 && (
        <div className="generation-history">
          <div className="panel-header">生成履歴</div>
          <div className="generation-history-list">
            {history.map((g) => {
              const histDiagnosis = g.status === "failed" ? parseDiagnosis(g.error_detail) : null;
              return (
                <div key={g.id} className="generation-history-entry">
                  <div className="generation-history-item">
                    <span className={`scene-status scene-status-${g.status}`}>{g.status}</span>
                    <span>{g.engine_id}</span>
                    <span className="generation-engine-reason">
                      {g.prompt || "(プロンプトなし)"}
                    </span>
                    {g.elapsed_seconds != null && <span>{g.elapsed_seconds.toFixed(0)}秒</span>}
                  </div>
                  {histDiagnosis && (
                    <details className="generation-history-diagnosis">
                      <summary>{histDiagnosis.summary}</summary>
                      <AIErrorPanel diagnosis={histDiagnosis} jobId={g.job_id ?? undefined} />
                    </details>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
