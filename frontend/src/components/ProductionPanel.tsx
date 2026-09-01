import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Diagnosis, LLMStatus, ProductionData, Scene, VisualType } from "../types";
import { VISUAL_TYPE_LABELS } from "../types";
import { useJobPolling } from "../hooks/useJobPolling";
import { formatTime } from "../utils/format";
import AIErrorPanel from "./AIErrorPanel";
import LlmModelCheckPanel from "./LlmModelCheckPanel";
import LlmStatusBadge from "./LlmStatusBadge";

const MODEL_STATUS_LABELS: Record<string, string> = {
  LM_STUDIO_CONNECTION_FAILED: "未接続",
  MODELS_FETCH_FAILED: "モデル一覧取得失敗",
  MODEL_NOT_LOADED: "Not Loaded",
  MODEL_NOT_FOUND: "Not Found",
  MODEL_ID_MISMATCH: "ID Mismatch",
};

const VISUAL_TYPES = Object.keys(VISUAL_TYPE_LABELS) as VisualType[];

// The pipeline as it actually exists today (see production_service.py's
// module docstring):企画生成 -> 台本・シーン生成. Later phases have no
// implementation yet, so they are listed separately as "未実装" rather
// than as checklist steps that could appear to run or fail.
const PRODUCTION_STEPS: { id: string; label: string }[] = [
  { id: "planning", label: "企画生成" },
  { id: "scene_generation", label: "台本・シーン生成" },
];
const UNIMPLEMENTED_STAGES = ["画像生成", "動画生成", "音声合成", "FFmpeg編集", "最終書き出し"];

function parseDiagnosis(raw: string | null): Diagnosis | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Diagnosis;
  } catch {
    return null;
  }
}

export default function ProductionPanel({ projectId }: { projectId: string }) {
  const { job, error, setError, track, isBusy } = useJobPolling();
  const [data, setData] = useState<ProductionData | null>(null);
  const [instruction, setInstruction] = useState("");
  const [durationMinutes, setDurationMinutes] = useState(10);
  const [llmStatus, setLlmStatus] = useState<LLMStatus | null>(null);

  const refresh = () => {
    api
      .getProduction(projectId)
      .then(setData)
      .catch((e) => setError(String(e)));
  };

  const refreshLlmStatus = () =>
    api
      .llmStatus()
      .then(setLlmStatus)
      .catch(() => setLlmStatus(null));

  useEffect(refresh, [projectId]);

  useEffect(() => {
    refreshLlmStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (job?.status === "completed") refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.status]);

  const handleStart = async () => {
    if (!instruction.trim()) return;
    if (
      data?.spec &&
      !window.confirm("既存の企画・台本・シーンは上書きされます。よろしいですか?")
    ) {
      return;
    }
    setError(null);
    try {
      const started = await api.produce(projectId, instruction, durationMinutes);
      track(started);
    } catch (e) {
      setError(String(e));
    }
  };

  const handleUpdateScene = async (
    sceneId: string,
    patch: Parameters<typeof api.updateScene>[1],
  ) => {
    try {
      const updated = await api.updateScene(sceneId, patch);
      setData((prev) =>
        prev
          ? {
              ...prev,
              chapters: prev.chapters.map((ch) => ({
                ...ch,
                scenes: ch.scenes.map((s) => (s.id === sceneId ? updated : s)),
              })),
            }
          : prev,
      );
    } catch (e) {
      setError(String(e));
    }
  };

  const handleDeleteScene = async (sceneId: string) => {
    try {
      await api.deleteScene(sceneId);
      refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  const totalScenes = data?.chapters.reduce((n, c) => n + c.scenes.length, 0) ?? 0;
  const totalEstimated =
    data?.chapters.reduce(
      (n, c) => n + c.scenes.reduce((s, sc) => s + sc.estimated_duration, 0),
      0,
    ) ?? 0;

  const preflightBlocked = llmStatus !== null && !llmStatus.ready;
  const failedDiagnosis = job?.status === "failed" ? parseDiagnosis(job.error_detail) : null;
  const currentStepIndex = job ? PRODUCTION_STEPS.findIndex((s) => s.id === job.step) : -1;

  return (
    <div className="production-panel">
      <div className="production-form">
        <textarea
          className="production-instruction"
          placeholder="例: 量子コンピュータについて初心者向けに解説するYouTube動画を作って。ドキュメンタリー風で。"
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          rows={2}
          disabled={isBusy}
        />
        <label className="production-duration-field">
          目標時間(分)
          <input
            type="number"
            min={1}
            max={120}
            value={durationMinutes}
            onChange={(e) => setDurationMinutes(Number(e.target.value))}
            disabled={isBusy}
          />
        </label>

        <div className="production-preflight">
          <div className="production-preflight-title">制作前チェック</div>
          <div className="llm-status-grid">
            <div className="llm-status-row">
              <span className="llm-status-key">AI Provider</span>
              <span className="llm-status-value">LM Studio</span>
            </div>
            <div className="llm-status-row">
              <span className="llm-status-key">Connection</span>
              <span className={llmStatus?.server_reachable ? "ok" : "bad"}>
                {llmStatus?.server_reachable ? "● Connected" : "● Disconnected"}
              </span>
            </div>
            <div className="llm-status-row">
              <span className="llm-status-key">Server</span>
              <span className={llmStatus?.api_ok ? "ok" : "bad"}>
                {llmStatus?.api_ok ? "● Running" : "● 応答なし"}
              </span>
            </div>
            <div className="llm-status-row">
              <span className="llm-status-key">Model</span>
              <span className={llmStatus?.ready ? "ok" : "warn"}>
                {llmStatus?.ready ? `● ${llmStatus.model}` : "⚠ Not Loaded"}
              </span>
            </div>
            {llmStatus && !llmStatus.ready && (
              <div className="llm-status-row">
                <span className="llm-status-key">Requested</span>
                <span className="llm-status-value">
                  {llmStatus.model}
                  {llmStatus.is_placeholder_model ? "(未設定・アプリの既定値)" : ""}
                </span>
              </div>
            )}
            <div className="llm-status-row">
              <span className="llm-status-key">Model Status</span>
              <span className={llmStatus?.ready ? "ok" : "bad"}>
                {llmStatus?.ready
                  ? "● Loaded"
                  : `● ${MODEL_STATUS_LABELS[llmStatus?.error_code ?? ""] ?? "未確認"}`}
              </span>
            </div>
          </div>
          {preflightBlocked && llmStatus?.diagnosis && (
            <div className="production-preflight-reason">
              制作を開始できません。原因: {llmStatus.diagnosis.cause || llmStatus.diagnosis.summary}
            </div>
          )}
          <LlmModelCheckPanel onChecked={setLlmStatus} />
        </div>

        <button
          className="primary"
          onClick={handleStart}
          disabled={isBusy || !instruction.trim() || preflightBlocked}
          title={preflightBlocked ? "制作前チェックを満たしていません" : undefined}
        >
          {isBusy ? "制作中..." : data?.spec ? "再生成する" : "AI制作を開始"}
        </button>
        <LlmStatusBadge status={llmStatus} />
      </div>

      {job && (
        <div className="production-job-status">
          <div className="render-progress-bar">
            <div className="render-progress-fill" style={{ width: `${job.progress}%` }} />
          </div>
          <span>
            {job.status === "failed"
              ? (failedDiagnosis?.summary ?? job.error)
              : `${job.message || job.status} (${job.progress.toFixed(0)}%)`}
          </span>
        </div>
      )}

      <div className="production-steps">
        {PRODUCTION_STEPS.map((step, i) => {
          const mark =
            job?.status === "failed" && i === currentStepIndex
              ? "✗"
              : i < currentStepIndex || job?.status === "completed"
                ? "✓"
                : i === currentStepIndex
                  ? "…"
                  : "○";
          return (
            <span key={step.id} className={`production-step production-step-${mark === "✓" ? "done" : mark === "✗" ? "failed" : mark === "…" ? "active" : "pending"}`}>
              {mark} {step.label}
            </span>
          );
        })}
        <span className="production-step-unimplemented">
          未実装(今後追加予定): {UNIMPLEMENTED_STAGES.join(" / ")}
        </span>
      </div>

      {failedDiagnosis && (
        <AIErrorPanel
          diagnosis={failedDiagnosis}
          jobId={job?.id}
          onRecheck={refreshLlmStatus}
          onRetry={handleStart}
        />
      )}

      {error && <div style={{ color: "var(--danger)", padding: "0 16px" }}>{error}</div>}

      {data?.spec && (
        <div className="production-summary">
          <h2>{data.spec.title}</h2>
          <div className="production-meta">
            対象視聴者: {data.spec.target_audience} / トーン: {data.spec.tone} / {" "}
            {data.chapters.length}章・{totalScenes}シーン・推定{formatTime(totalEstimated)}
          </div>
        </div>
      )}

      <div className="chapter-list">
        {data?.chapters.map((chapter, ci) => (
          <div key={chapter.id} className="chapter-card">
            <div className="chapter-header">
              第{ci + 1}章: {chapter.title}
            </div>
            <div className="chapter-summary">{chapter.summary}</div>
            <div className="scene-list">
              {chapter.scenes.map((scene, si) => (
                <SceneCard
                  key={scene.id}
                  index={si}
                  scene={scene}
                  onUpdate={(patch) => handleUpdateScene(scene.id, patch)}
                  onDelete={() => handleDeleteScene(scene.id)}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SceneCard({
  index,
  scene,
  onUpdate,
  onDelete,
}: {
  index: number;
  scene: Scene;
  onUpdate: (patch: Partial<Scene>) => void;
  onDelete: () => void;
}) {
  const [narration, setNarration] = useState(scene.narration);
  const [visualPrompt, setVisualPrompt] = useState(scene.visual_prompt);

  return (
    <div className="scene-card">
      <div className="scene-card-header">
        <span>シーン {index + 1}</span>
        <span className={`scene-status scene-status-${scene.status}`}>{scene.status}</span>
        <button className="danger" onClick={onDelete}>
          削除
        </button>
      </div>
      <label className="scene-field">
        ナレーション
        <textarea
          value={narration}
          rows={2}
          onChange={(e) => setNarration(e.target.value)}
          onBlur={() => onUpdate({ narration })}
        />
      </label>
      <div className="scene-row">
        <label className="scene-field">
          ビジュアルタイプ
          <select
            value={scene.visual_type}
            onChange={(e) => onUpdate({ visual_type: e.target.value as VisualType })}
          >
            {VISUAL_TYPES.map((vt) => (
              <option key={vt} value={vt}>
                {VISUAL_TYPE_LABELS[vt]}
              </option>
            ))}
          </select>
        </label>
        <label className="scene-field scene-field-duration">
          長さ(秒)
          <input
            type="number"
            min={0.5}
            step={0.5}
            value={scene.estimated_duration}
            onChange={(e) => onUpdate({ estimated_duration: Number(e.target.value) })}
          />
        </label>
      </div>
      <label className="scene-field">
        ビジュアル指示
        <textarea
          value={visualPrompt}
          rows={2}
          onChange={(e) => setVisualPrompt(e.target.value)}
          onBlur={() => onUpdate({ visual_prompt: visualPrompt })}
        />
      </label>
    </div>
  );
}
