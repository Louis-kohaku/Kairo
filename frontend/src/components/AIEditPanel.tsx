import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useJobPolling } from "../hooks/useJobPolling";

interface Props {
  projectId: string;
  onApplied: () => void;
}

export default function AIEditPanel({ projectId, onApplied }: Props) {
  const { job, error, setError, track, isBusy } = useJobPolling();
  const [instruction, setInstruction] = useState("");
  const [llmAvailable, setLlmAvailable] = useState<boolean | null>(null);

  useEffect(() => {
    api
      .llmStatus()
      .then((s) => setLlmAvailable(s.available))
      .catch(() => setLlmAvailable(false));
  }, []);

  useEffect(() => {
    if (job?.status === "completed") onApplied();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.status]);

  const handleRun = async () => {
    if (!instruction.trim()) return;
    setError(null);
    try {
      const started = await api.aiEdit(projectId, instruction);
      track(started);
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div className="ai-edit-panel">
      <input
        type="text"
        className="ai-edit-input"
        placeholder="例: 無音部分を削除して、字幕をつけてください"
        value={instruction}
        onChange={(e) => setInstruction(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && handleRun()}
        disabled={isBusy}
      />
      <button className="primary" onClick={handleRun} disabled={isBusy || !instruction.trim()}>
        {isBusy ? "実行中..." : "AIで編集"}
      </button>
      <span className={`llm-indicator ${llmAvailable ? "ok" : "off"}`}>
        {llmAvailable === null
          ? "LM Studio: 確認中"
          : llmAvailable
            ? "LM Studio: 接続済み"
            : "LM Studio: 未接続"}
      </span>

      {job && (
        <span className="ai-edit-status">
          {job.status === "failed" ? (
            <span style={{ color: "var(--danger)" }}>{job.error}</span>
          ) : (
            `${job.message || job.status} (${job.progress.toFixed(0)}%)`
          )}
        </span>
      )}
      {error && <span style={{ color: "var(--danger)" }}>{error}</span>}
    </div>
  );
}
