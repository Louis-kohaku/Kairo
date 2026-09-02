import { useState } from "react";
import { api } from "../api/client";
import type { LLMStatus } from "../types";
import { MODEL_SOURCE_LABELS } from "../utils/format";
import AIErrorPanel from "./AIErrorPanel";

interface Props {
  // Lets the caller (e.g. ProductionPanel, which already polls status for
  // its own preflight checklist) push a freshly-fetched status in here
  // instead of this component re-fetching right after the caller did.
  onChecked?: (status: LLMStatus) => void;
}

export default function LlmModelCheckPanel({ onChecked }: Props) {
  const [status, setStatus] = useState<LLMStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleCheck = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.llmStatus();
      setStatus(result);
      onChecked?.(result);
    } catch (e) {
      setError(String(e));
      setStatus(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="llm-model-check">
      <button onClick={handleCheck} disabled={loading} className="llm-model-check-button">
        {loading ? "確認中..." : "モデル状態を確認"}
      </button>

      {error && <div className="llm-model-check-error">状態の取得に失敗しました: {error}</div>}

      {status && (
        <div className="llm-model-check-result">
          <div className="llm-model-check-row">
            <span className="llm-model-check-label">LM Studio</span>
            <span className={status.server_reachable ? "ok" : "bad"}>
              {status.server_reachable ? "✓ API Connected" : "✗ API未接続"}
            </span>
          </div>

          <div className="llm-model-check-row">
            <span className="llm-model-check-label">Available Models</span>
            {status.models_loaded.length > 0 ? (
              <ul>
                {status.models_loaded.map((m) => (
                  <li key={m} className="ok">
                    ✓ {m}
                  </li>
                ))}
              </ul>
            ) : (
              <span className="bad">✗ ロード済みモデルなし</span>
            )}
          </div>

          <div className="llm-model-check-row">
            <span className="llm-model-check-label">Selected Model</span>
            <span className={status.ready ? "ok" : "bad"}>
              {status.ready ? "✓" : "✗"} {status.model ?? "(未解決)"}
              {status.model_source ? ` (${MODEL_SOURCE_LABELS[status.model_source] ?? status.model_source})` : ""}
            </span>
          </div>

          <div className="llm-model-check-row">
            <span className="llm-model-check-label">Status</span>
            <span className={status.ready ? "ok" : "bad"}>
              {status.ready ? "✓ Ready" : "❌ Not Ready"}
            </span>
          </div>

          {!status.ready && status.diagnosis && (
            <AIErrorPanel diagnosis={status.diagnosis} onRecheck={handleCheck} />
          )}
        </div>
      )}
    </div>
  );
}
