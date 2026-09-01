import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Diagnosis, LLMStatus } from "../types";
import { useJobPolling } from "../hooks/useJobPolling";
import AIErrorPanel from "./AIErrorPanel";
import LlmStatusBadge from "./LlmStatusBadge";

interface Props {
  projectId: string;
  onApplied: () => void;
}

function parseDiagnosis(raw: string | null): Diagnosis | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Diagnosis;
  } catch {
    return null;
  }
}

export default function AIEditPanel({ projectId, onApplied }: Props) {
  const { job, error, setError, track, isBusy } = useJobPolling();
  const [instruction, setInstruction] = useState("");
  const [llmStatus, setLlmStatus] = useState<LLMStatus | null>(null);

  const refreshLlmStatus = () =>
    api
      .llmStatus()
      .then(setLlmStatus)
      .catch(() => setLlmStatus(null));

  useEffect(() => {
    refreshLlmStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  const failedDiagnosis = job?.status === "failed" ? parseDiagnosis(job.error_detail) : null;

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
      <LlmStatusBadge status={llmStatus} />

      {job && (
        <span className="ai-edit-status">
          {job.status === "failed"
            ? (failedDiagnosis?.summary ?? job.error)
            : `${job.message || job.status} (${job.progress.toFixed(0)}%)`}
        </span>
      )}
      {error && <span style={{ color: "var(--danger)" }}>{error}</span>}

      {failedDiagnosis && (
        <AIErrorPanel
          diagnosis={failedDiagnosis}
          jobId={job?.id}
          onRecheck={refreshLlmStatus}
          onRetry={handleRun}
        />
      )}
    </div>
  );
}
