import { useState } from "react";
import { api } from "../api/client";
import type { Diagnosis } from "../types";

interface Props {
  diagnosis: Diagnosis;
  jobId?: string;
  onRetry?: () => void;
  onRecheck?: () => void;
}

const CATEGORY_LABELS: Record<string, string> = {
  ai_provider: "AI Provider Error",
  model: "Model Error",
  api: "API Error",
  network: "Network Error",
  resource: "Resource Error",
  memory: "Memory Error",
  ffmpeg: "FFmpeg Error",
  input_material: "Input/Material Error",
  configuration: "Configuration Error",
  unknown: "Unknown Error",
};

const CONTEXT_FIELDS: { key: keyof NonNullable<Diagnosis["ai_context"]>; label: string }[] = [
  { key: "provider", label: "AI Provider" },
  { key: "model", label: "Model" },
  { key: "task", label: "Task" },
  { key: "operation", label: "Operation" },
  { key: "endpoint", label: "Endpoint" },
  { key: "model_status", label: "Model Status" },
];

export default function AIErrorPanel({ diagnosis, jobId, onRetry, onRecheck }: Props) {
  const [log, setLog] = useState<string | null>(null);
  const [logLoading, setLogLoading] = useState(false);
  const [logError, setLogError] = useState<string | null>(null);

  const handleLoadLog = async () => {
    if (!jobId || log !== null) return;
    setLogLoading(true);
    setLogError(null);
    try {
      setLog(await api.getJobLog(jobId));
    } catch (e) {
      setLogError(String(e));
    } finally {
      setLogLoading(false);
    }
  };

  return (
    <div className="ai-error-panel">
      <div className="ai-error-summary">
        <span className="ai-error-icon">⚠</span> {diagnosis.summary}
      </div>

      {diagnosis.facts.length > 0 && (
        <div className="ai-error-facts">
          <div className="ai-error-section-title">確認された状態</div>
          <ul>
            {diagnosis.facts.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="ai-error-cause">
        <span className="ai-error-section-title">
          {diagnosis.cause_known ? "原因" : "推定される原因"}
        </span>
        <span>{diagnosis.cause}</span>
      </div>

      {!diagnosis.cause_known && diagnosis.candidates.length > 0 && (
        <div className="ai-error-candidates">
          <div className="ai-error-section-title">考えられる原因</div>
          <ul>
            {diagnosis.candidates.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="ai-error-actions">
        {onRecheck && (
          <button onClick={onRecheck} className="ai-error-action">
            状態を再確認
          </button>
        )}
        {onRetry && diagnosis.retryable && (
          <button onClick={onRetry} className="ai-error-action primary">
            再実行
          </button>
        )}
      </div>

      <details className="ai-error-details">
        <summary>詳細情報</summary>
        <div className="ai-error-details-body">
          <div className="ai-error-kv">
            <span>分類</span>
            <span>{CATEGORY_LABELS[diagnosis.category] ?? diagnosis.category}</span>
          </div>
          {diagnosis.step && (
            <div className="ai-error-kv">
              <span>失敗した工程</span>
              <span>{diagnosis.step}</span>
            </div>
          )}
          {diagnosis.ai_context &&
            CONTEXT_FIELDS.map(({ key, label }) => (
              <div className="ai-error-kv" key={key}>
                <span>{label}</span>
                <span>{diagnosis.ai_context![key]}</span>
              </div>
            ))}
          <div className="ai-error-kv">
            <span>再試行可能</span>
            <span>{diagnosis.retryable ? "はい" : "いいえ"}</span>
          </div>

          <details className="ai-error-dev-log">
            <summary>開発者向けログ</summary>
            <div className="ai-error-dev-log-body">
              <div className="ai-error-kv">
                <span>Raw Error</span>
                <span>{diagnosis.raw_error}</span>
              </div>
              {jobId && (
                <>
                  {log === null && (
                    <button onClick={handleLoadLog} disabled={logLoading} className="ai-error-action">
                      {logLoading ? "読み込み中..." : "ログを読み込む"}
                    </button>
                  )}
                  {logError && <div className="ai-error-log-error">{logError}</div>}
                  {log !== null && <pre className="ai-error-log-pre">{log}</pre>}
                </>
              )}
            </div>
          </details>
        </div>
      </details>
    </div>
  );
}
