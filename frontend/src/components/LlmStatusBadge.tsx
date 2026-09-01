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

const UNREADY_LABELS: Record<string, string> = {
  MODEL_NOT_LOADED: "モデル未ロード",
  MODEL_NOT_FOUND: "モデルが見つかりません",
  MODEL_ID_MISMATCH: "モデルID不一致",
};

function summarize(status: LLMStatus | null): { dot: string; text: string; title: string } {
  if (status === null) return { dot: "⚪", text: "LM Studio: 確認中", title: "確認中" };
  if (!status.server_reachable) {
    return { dot: "🔴", text: "LM Studio: 未接続", title: `${status.base_url} に接続できません` };
  }
  if (!status.api_ok) {
    return { dot: "🔴", text: "LM Studio: API応答なし", title: "モデル一覧を取得できません" };
  }
  if (status.ready) {
    return {
      dot: "🟢",
      text: "LM Studio: 準備完了",
      title: `使用モデル: ${status.model}`,
    };
  }
  return {
    dot: "🟡",
    text: `LM Studio: ${UNREADY_LABELS[status.error_code] ?? "未準備"}`,
    title: `要求モデル: ${status.model} / ロード済み: ${status.models_loaded.join(", ") || "なし"}`,
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
              is_placeholder_model: false,
              error_code: "LM_STUDIO_CONNECTION_FAILED",
              ready: false,
              diagnosis: null,
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
