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

// The core "何を使おうとしていて、何が分かっているか" fields - always shown
// directly in the panel (never behind a collapsed section), per Kairo's
// policy that AI failure diagnostics must be visible in the main UI.
const AI_CONTEXT_ROWS: { key: "task" | "provider" | "endpoint"; label: string }[] = [
  { key: "task", label: "Task" },
  { key: "provider", label: "AI Provider" },
  { key: "endpoint", label: "Endpoint" },
];

export default function AIErrorPanel({ diagnosis, jobId, onRetry, onRecheck }: Props) {
  const [log, setLog] = useState<string | null>(null);
  const [logLoading, setLogLoading] = useState(false);
  const [logError, setLogError] = useState<string | null>(null);
  const ctx = diagnosis.ai_context;

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

      {ctx && (
        <div className="ai-error-context">
          {AI_CONTEXT_ROWS.map(({ key, label }) => (
            <div className="ai-error-kv" key={key}>
              <span>{label}</span>
              <span>{ctx[key]}</span>
            </div>
          ))}
          <div className="ai-error-kv">
            <span>Requested Model</span>
            <span>
              {ctx.requested_model || ctx.model}
              {ctx.is_placeholder_model ? "(未設定・アプリの既定値)" : ""}
            </span>
          </div>
          <div className="ai-error-kv">
            <span>LM Studio API接続</span>
            <span className={ctx.connection_status === "OK" ? "ok" : "bad"}>
              {ctx.connection_status === "OK" ? "OK" : "NG"}
            </span>
          </div>
          {diagnosis.error_code && (
            <div className="ai-error-kv">
              <span>Error Code</span>
              <span>{diagnosis.error_code}</span>
            </div>
          )}
        </div>
      )}

      {ctx && (
        <div className="ai-error-models">
          <div className="ai-error-section-title">利用可能なモデル(LM Studioで現在ロード中)</div>
          {ctx.models_loaded.length > 0 ? (
            <ul>
              {ctx.models_loaded.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          ) : (
            <div className="ai-error-models-empty">(ロード済みモデルなし)</div>
          )}
        </div>
      )}

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

      {diagnosis.candidates.length > 0 && (
        <div className="ai-error-candidates">
          <div className="ai-error-section-title">
            {diagnosis.cause_known ? "確認事項" : "考えられる原因"}
          </div>
          <ul>
            {diagnosis.candidates.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </div>
      )}

      {diagnosis.suggestions.length > 0 && (
        <div className="ai-error-solutions">
          <div className="ai-error-section-title">解決方法</div>
          <ul>
            {diagnosis.suggestions.map((s) => (
              <li key={s.label}>{s.label}</li>
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
          {ctx && (
            <div className="ai-error-kv">
              <span>Operation</span>
              <span>{ctx.operation}</span>
            </div>
          )}
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
