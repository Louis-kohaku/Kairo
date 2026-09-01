import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { LLMStatus } from "../types";

interface Props {
  // When provided, the badge just renders this status instead of polling
  // its own (lets a panel that already fetched /api/llm/status reuse it
  // instead of doubling the request).
  status?: LLMStatus | null;
  pollIntervalMs?: number;
}

function summarize(status: LLMStatus | null): { dot: string; text: string; title: string } {
  if (status === null) return { dot: "⚪", text: "LM Studio: 確認中", title: "確認中" };
  if (!status.server_reachable) {
    return { dot: "🔴", text: "LM Studio: 未接続", title: `${status.base_url} に接続できません` };
  }
  if (!status.can_generate) {
    return {
      dot: "🟡",
      text: "LM Studio: モデル未ロード",
      title: "サーバーには接続できていますが、ロード済みモデルがありません",
    };
  }
  return {
    dot: "🟢",
    text: "LM Studio: 準備完了",
    title: `ロード済み: ${status.models_loaded.join(", ")}`,
  };
}

export default function LlmStatusBadge({ status: externalStatus, pollIntervalMs = 15000 }: Props) {
  const [internalStatus, setInternalStatus] = useState<LLMStatus | null>(null);

  useEffect(() => {
    if (externalStatus !== undefined) return;
    let cancelled = false;
    const refresh = () => {
      api
        .llmStatus()
        .then((s) => !cancelled && setInternalStatus(s))
        .catch(
          () =>
            !cancelled &&
            setInternalStatus({
              available: false,
              base_url: "",
              model: "",
              server_reachable: false,
              api_ok: false,
              models_loaded: [],
              configured_model_loaded: false,
              can_generate: false,
            }),
        );
    };
    refresh();
    const id = window.setInterval(refresh, pollIntervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalStatus === undefined]);

  const status = externalStatus !== undefined ? externalStatus : internalStatus;
  const { dot, text, title } = summarize(status);

  return (
    <span className="llm-status-badge" title={title}>
      {dot} {text}
    </span>
  );
}
