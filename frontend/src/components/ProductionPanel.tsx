import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ProductionData, Scene, VisualType } from "../types";
import { VISUAL_TYPE_LABELS } from "../types";
import { useJobPolling } from "../hooks/useJobPolling";
import { formatTime } from "../utils/format";

const VISUAL_TYPES = Object.keys(VISUAL_TYPE_LABELS) as VisualType[];

export default function ProductionPanel({ projectId }: { projectId: string }) {
  const { job, error, setError, track, isBusy } = useJobPolling();
  const [data, setData] = useState<ProductionData | null>(null);
  const [instruction, setInstruction] = useState("");
  const [durationMinutes, setDurationMinutes] = useState(10);
  const [llmAvailable, setLlmAvailable] = useState<boolean | null>(null);

  const refresh = () => {
    api
      .getProduction(projectId)
      .then(setData)
      .catch((e) => setError(String(e)));
  };

  useEffect(refresh, [projectId]);

  useEffect(() => {
    api
      .llmStatus()
      .then((s) => setLlmAvailable(s.available))
      .catch(() => setLlmAvailable(false));
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
        <button
          className="primary"
          onClick={handleStart}
          disabled={isBusy || !instruction.trim()}
        >
          {isBusy ? "制作中..." : data?.spec ? "再生成する" : "AI制作を開始"}
        </button>
        <span className={`llm-indicator ${llmAvailable ? "ok" : "off"}`}>
          {llmAvailable === null
            ? "LM Studio: 確認中"
            : llmAvailable
              ? "LM Studio: 接続済み"
              : "LM Studio: 未接続"}
        </span>
      </div>

      {job && (
        <div className="production-job-status">
          <div className="render-progress-bar">
            <div className="render-progress-fill" style={{ width: `${job.progress}%` }} />
          </div>
          <span>
            {job.status === "failed" ? (
              <span style={{ color: "var(--danger)" }}>{job.error}</span>
            ) : (
              `${job.message || job.status} (${job.progress.toFixed(0)}%)`
            )}
          </span>
        </div>
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
