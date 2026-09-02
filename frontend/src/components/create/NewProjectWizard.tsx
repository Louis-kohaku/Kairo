import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { AISettingsT, EstimateOut, LLMStatus, ModelInfo, QualityPreset } from "../../types";
import { formatSecondsRangeAsMinutes, MODEL_SOURCE_LABELS } from "../../utils/format";
import { ASPECTS, QUALITY_PRESETS, resolutionFor, type Aspect } from "../../utils/videoPresets";
import AIErrorPanel from "../AIErrorPanel";
import SelectCard from "./SelectCard";

interface Props {
  onCreated: (projectId: string) => void;
  onCancel: () => void;
  onOpenSettings: () => void;
}

type VideoType = "short" | "sns" | "youtube" | "other";

const VIDEO_TYPES: { id: VideoType; label: string; description: string }[] = [
  { id: "short", label: "ショート動画", description: "15〜60秒程度の縦型動画" },
  { id: "sns", label: "SNS動画", description: "Instagram / X などへの投稿向け" },
  { id: "youtube", label: "YouTube動画", description: "横型・長尺の解説/紹介動画" },
  { id: "other", label: "その他", description: "自由な内容・形式" },
];

const LENGTH_PRESETS = [15, 30, 60] as const;

export default function NewProjectWizard({ onCreated, onCancel, onOpenSettings }: Props) {
  const [videoType, setVideoType] = useState<VideoType | null>(null);
  const [content, setContent] = useState("");
  const [lengthPreset, setLengthPreset] = useState<number | "custom">(30);
  const [customSeconds, setCustomSeconds] = useState(45);
  const [aspect, setAspect] = useState<Aspect>("9:16");
  const [quality, setQuality] = useState<QualityPreset>("standard");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [overrideRes, setOverrideRes] = useState<{ width: number; height: number; fps: number } | null>(null);

  const [aiSettings, setAiSettings] = useState<AISettingsT | null>(null);
  const [llmStatus, setLlmStatus] = useState<LLMStatus | null>(null);
  const [manualModels, setManualModels] = useState<ModelInfo[]>([]);

  const [estimate, setEstimate] = useState<EstimateOut | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const durationSeconds = lengthPreset === "custom" ? customSeconds : lengthPreset;
  const resolution = overrideRes ?? resolutionFor(aspect, quality);

  useEffect(() => {
    api.getSettings().then((s) => setAiSettings(s.ai)).catch(() => {});
    api.llmStatus().then(setLlmStatus).catch(() => {});
  }, []);

  useEffect(() => {
    if (aiSettings?.mode === "manual") {
      api.getAiModels().then((r) => setManualModels(r.models)).catch(() => {});
    }
  }, [aiSettings?.mode]);

  useEffect(() => {
    const t = window.setTimeout(() => {
      api.getEstimate(durationSeconds, quality).then(setEstimate).catch(() => setEstimate(null));
    }, 250);
    return () => window.clearTimeout(t);
  }, [durationSeconds, quality]);

  const handleAiModeChange = async (mode: "auto" | "manual") => {
    try {
      const updated = await api.updateSettings({ ai: { mode } });
      setAiSettings(updated.ai);
      api.llmStatus().then(setLlmStatus).catch(() => {});
    } catch (e) {
      setError(String(e));
    }
  };

  const handleSelectManualModel = async (modelId: string) => {
    try {
      const updated = await api.updateSettings({ ai: { mode: "manual", selected_model: modelId } });
      setAiSettings(updated.ai);
      api.llmStatus().then(setLlmStatus).catch(() => {});
      // The model list's `is_current` flags reflect the settings as of the
      // last fetch, so without this the newly-selected card's checkmark
      // never moves even though the setting itself saved correctly.
      api.getAiModels().then((r) => setManualModels(r.models)).catch(() => {});
    } catch (e) {
      setError(String(e));
    }
  };

  const missing: string[] = [];
  if (!videoType) missing.push("動画タイプを選択してください");
  if (!content.trim()) missing.push("内容を入力してください");
  const canSubmit = missing.length === 0 && !submitting;

  const handleSubmit = async () => {
    if (!canSubmit || !videoType) return;
    setSubmitting(true);
    setError(null);
    try {
      const typeLabel = VIDEO_TYPES.find((t) => t.id === videoType)?.label ?? "";
      const name = content.trim().slice(0, 40) || "新しい動画";
      const project = await api.createProject(name, resolution.fps, resolution.width, resolution.height);
      const instruction = `[${typeLabel}] ${content.trim()}`;
      await api.produce(project.id, instruction, durationSeconds / 60);
      onCreated(project.id);
    } catch (e) {
      setError(String(e));
      setSubmitting(false);
    }
  };

  return (
    <div className="wizard-root">
      <div className="wizard-main">
        <h1 className="wizard-title">新しい動画を作成</h1>

        <section className="wizard-section">
          <div className="wizard-section-label">
            ① 何を作る？<span className="req-badge">必須</span>
          </div>
          <div className="select-card-grid select-card-grid-4" role="radiogroup" aria-label="動画タイプ">
            {VIDEO_TYPES.map((t) => (
              <SelectCard
                key={t.id}
                title={t.label}
                description={t.description}
                selected={videoType === t.id}
                onSelect={() => setVideoType(t.id)}
              />
            ))}
          </div>
        </section>

        <section className="wizard-section">
          <div className="wizard-section-label">
            ② 内容<span className="req-badge">必須</span>
          </div>
          <textarea
            className="wizard-content-input"
            placeholder="例: かわいい猫が遊ぶ60秒ショート動画"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={3}
          />
        </section>

        <section className="wizard-section">
          <div className="wizard-section-label">
            ③ 長さ<span className="opt-badge">任意</span>
          </div>
          <div className="select-card-grid select-card-grid-4">
            {LENGTH_PRESETS.map((s) => (
              <SelectCard
                key={s}
                title={`${s}秒`}
                selected={lengthPreset === s}
                onSelect={() => setLengthPreset(s)}
              />
            ))}
            <SelectCard
              title="カスタム"
              description={lengthPreset === "custom" ? `${customSeconds}秒` : undefined}
              selected={lengthPreset === "custom"}
              onSelect={() => setLengthPreset("custom")}
            />
          </div>
          {lengthPreset === "custom" && (
            <input
              type="number"
              min={5}
              max={1200}
              value={customSeconds}
              onChange={(e) => setCustomSeconds(Number(e.target.value))}
              className="wizard-custom-length-input"
            />
          )}
        </section>

        <section className="wizard-section">
          <div className="wizard-section-label">
            ④ 比率<span className="opt-badge">任意</span>
          </div>
          <div className="select-card-grid select-card-grid-3">
            {ASPECTS.map((a) => (
              <SelectCard
                key={a.id}
                title={a.label}
                description={a.description}
                selected={aspect === a.id}
                onSelect={() => {
                  setAspect(a.id);
                  setOverrideRes(null);
                }}
              />
            ))}
          </div>
        </section>

        <section className="wizard-section">
          <div className="wizard-section-label">
            ⑤ 品質<span className="opt-badge">任意</span>
          </div>
          <div className="select-card-grid select-card-grid-3">
            {QUALITY_PRESETS.map((q) => (
              <SelectCard
                key={q.id}
                title={q.label}
                description={q.description}
                selected={quality === q.id}
                onSelect={() => {
                  setQuality(q.id);
                  setOverrideRes(null);
                }}
              />
            ))}
          </div>
        </section>

        <section className="wizard-section">
          <div className="wizard-section-label">
            ⑥ AI<span className="opt-badge">任意</span>
          </div>
          <div className="wizard-ai-box">
            <div className="select-card-grid select-card-grid-2">
              <SelectCard
                title="Auto"
                description="KairoがPC性能と用途から自動選択"
                selected={aiSettings?.mode !== "manual"}
                onSelect={() => handleAiModeChange("auto")}
              />
              <SelectCard
                title="Manual"
                description="自分でモデルを選択"
                selected={aiSettings?.mode === "manual"}
                onSelect={() => handleAiModeChange("manual")}
              />
            </div>

            <div className="wizard-ai-current">
              <span className="wizard-ai-current-label">現在のモデル:</span>
              <span className={llmStatus?.ready ? "ok" : "warn"}>
                {llmStatus === null
                  ? "確認中..."
                  : llmStatus.model
                    ? `${llmStatus.model} (${MODEL_SOURCE_LABELS[llmStatus.model_source] ?? llmStatus.model_source})`
                    : "未解決"}
              </span>
              <button onClick={onOpenSettings} className="wizard-ai-change-btn">
                変更 / 詳細
              </button>
            </div>

            {aiSettings?.mode === "manual" && (
              <div className="select-card-grid select-card-grid-3" style={{ marginTop: 8 }}>
                {manualModels.map((m) => (
                  <SelectCard
                    key={m.id}
                    title={m.id}
                    description={m.recommended ? `推奨(${m.catalog_tier_label})` : "Available"}
                    selected={m.is_current}
                    onSelect={() => handleSelectManualModel(m.id)}
                  />
                ))}
                {manualModels.length === 0 && (
                  <div className="generation-engine-reason">LM Studioで利用可能なモデルが見つかりません。</div>
                )}
              </div>
            )}

            {llmStatus && !llmStatus.ready && llmStatus.diagnosis && (
              <AIErrorPanel diagnosis={llmStatus.diagnosis} onRecheck={() => api.llmStatus().then(setLlmStatus)} />
            )}
          </div>
        </section>

        <section className="wizard-section">
          <button className="wizard-advanced-toggle" onClick={() => setAdvancedOpen((o) => !o)}>
            {advancedOpen ? "▾" : "▸"} 詳細設定
          </button>
          {advancedOpen && (
            <div className="wizard-advanced-body">
              <div className="wizard-section-label">
                ⑦ 出力<span className="opt-badge">任意</span>
              </div>
              <div className="wizard-output-row">
                <label className="scene-field">
                  解像度
                  <input
                    type="number"
                    value={resolution.width}
                    onChange={(e) =>
                      setOverrideRes({ ...resolution, width: Number(e.target.value) })
                    }
                  />
                </label>
                <span>×</span>
                <label className="scene-field">
                  &nbsp;
                  <input
                    type="number"
                    value={resolution.height}
                    onChange={(e) =>
                      setOverrideRes({ ...resolution, height: Number(e.target.value) })
                    }
                  />
                </label>
                <label className="scene-field">
                  FPS
                  <input
                    type="number"
                    value={resolution.fps}
                    onChange={(e) => setOverrideRes({ ...resolution, fps: Number(e.target.value) })}
                  />
                </label>
              </div>
            </div>
          )}
        </section>

        {error && <div className="wizard-error">{error}</div>}
      </div>

      <aside className="wizard-summary">
        <div className="wizard-summary-title">現在の設定</div>
        <dl className="wizard-summary-list">
          <dt>動画</dt>
          <dd>{durationSeconds}秒</dd>
          <dt>比率</dt>
          <dd>{aspect}</dd>
          <dt>品質</dt>
          <dd>{QUALITY_PRESETS.find((q) => q.id === quality)?.label}</dd>
          <dt>出力</dt>
          <dd>
            {resolution.width}×{resolution.height} / {resolution.fps}fps
          </dd>
          <dt>AI</dt>
          <dd>{aiSettings?.mode === "manual" ? "Manual" : "Auto"}</dd>
          <dt>モデル</dt>
          <dd>{llmStatus?.model ?? "-"}</dd>
        </dl>

        <div className="wizard-summary-title">推定処理時間</div>
        {estimate ? (
          <div className="wizard-estimate">
            <div>
              企画: {formatSecondsRangeAsMinutes(estimate.planning.low_seconds, estimate.planning.high_seconds)}
            </div>
            <div>
              生成: {formatSecondsRangeAsMinutes(estimate.generation.low_seconds, estimate.generation.high_seconds)}
            </div>
            <div className="wizard-estimate-total">
              合計: {formatSecondsRangeAsMinutes(estimate.total.low_seconds, estimate.total.high_seconds)}
            </div>
            <div className="generation-engine-reason">{estimate.note}</div>
          </div>
        ) : (
          <div className="generation-engine-reason">計算中...</div>
        )}

        {missing.length > 0 && (
          <div className="wizard-missing">
            {missing.map((m) => (
              <div key={m}>⚠ {m}</div>
            ))}
          </div>
        )}

        <button
          className="primary wizard-submit-btn"
          onClick={handleSubmit}
          disabled={!canSubmit}
        >
          {submitting ? "作成中..." : "制作を開始"}
        </button>
        <button onClick={onCancel} className="wizard-cancel-btn">
          キャンセル
        </button>
      </aside>
    </div>
  );
}
