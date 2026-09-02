import { useEffect, useState } from "react";
import { api } from "../api/client";
import SelectCard from "../components/create/SelectCard";
import AIErrorPanel from "../components/AIErrorPanel";
import SystemInfoPanel from "../components/SystemInfoPanel";
import type {
  AppSettings,
  LLMStatus,
  ModelInfo,
  PerformanceProfile,
  QualityPreset,
  RecommendationOut,
  VideoSettingWarning,
} from "../types";
import { MODEL_SOURCE_LABELS } from "../utils/format";

type Tab = "ai" | "video" | "performance" | "general";

const TABS: { id: Tab; label: string }[] = [
  { id: "ai", label: "AI" },
  { id: "video", label: "動画" },
  { id: "performance", label: "パフォーマンス" },
  { id: "general", label: "一般 / ストレージ" },
];

const QUALITY_PRESETS: { id: QualityPreset; label: string; description: string }[] = [
  { id: "fast", label: "高速", description: "処理時間優先" },
  { id: "standard", label: "標準", description: "品質と速度のバランス" },
  { id: "high", label: "高品質", description: "映像品質優先" },
  { id: "ultra", label: "最高品質", description: "処理時間は最も長くなります" },
];

const PERFORMANCE_PROFILES: { id: PerformanceProfile; label: string; description: string }[] = [
  { id: "auto", label: "Auto", description: "PC性能に合わせて自動調整" },
  { id: "speed", label: "Speed", description: "処理速度優先" },
  { id: "balanced", label: "Balanced", description: "品質と速度のバランス" },
  { id: "quality", label: "Quality", description: "品質優先" },
  { id: "custom", label: "Custom", description: "解像度・FPS等を個別に指定" },
];

const STARS = (n: number) => "★".repeat(n) + "☆".repeat(5 - n);

export default function SettingsPage({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<Tab>("ai");
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [llmStatus, setLlmStatus] = useState<LLMStatus | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [recommendation, setRecommendation] = useState<RecommendationOut | null>(null);
  const [showWhy, setShowWhy] = useState(false);
  const [showSetup, setShowSetup] = useState(false);
  const [videoWarning, setVideoWarning] = useState<VideoSettingWarning | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshAll = () => {
    api.getSettings().then(setSettings).catch((e) => setError(String(e)));
    api.llmStatus().then(setLlmStatus).catch(() => {});
    api.getAiModels().then((r) => setModels(r.models)).catch(() => {});
    api.getAiRecommendation().then(setRecommendation).catch(() => {});
  };

  useEffect(refreshAll, []);

  useEffect(() => {
    if (!settings) return;
    api
      .checkVideoSetting(settings.video.width, settings.video.height, settings.video.fps)
      .then(setVideoWarning)
      .catch(() => setVideoWarning(null));
  }, [settings?.video.width, settings?.video.height, settings?.video.fps]);

  const applyPatch = async (patch: Parameters<typeof api.updateSettings>[0]) => {
    try {
      const updated = await api.updateSettings(patch);
      setSettings(updated);
      if (patch.ai) {
        api.llmStatus().then(setLlmStatus).catch(() => {});
      }
    } catch (e) {
      setError(String(e));
    }
  };

  const handleReset = async () => {
    try {
      const defaults = await api.resetSettings();
      setSettings(defaults);
      refreshAll();
    } catch (e) {
      setError(String(e));
    }
  };

  if (!settings) {
    return <div className="settings-page">読み込み中...</div>;
  }

  return (
    <div className="settings-page">
      <div className="settings-topbar">
        <button onClick={onClose}>&larr; 戻る</button>
        <span className="settings-title">設定</span>
        <span style={{ flex: 1 }} />
        <button onClick={handleReset}>デフォルトに戻す</button>
      </div>

      <div className="settings-body">
        <nav className="settings-tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={tab === t.id ? "settings-tab-active" : ""}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>

        <div className="settings-content">
          {error && <div className="wizard-error">{error}</div>}

          {tab === "ai" && (
            <div className="settings-section">
              <h2>AI Provider: LM Studio</h2>
              <div className="llm-status-grid">
                <div className="llm-status-row">
                  <span className="llm-status-key">接続</span>
                  <span className={llmStatus?.server_reachable ? "ok" : "bad"}>
                    {llmStatus?.server_reachable ? "● Connected" : "● Disconnected"}
                  </span>
                </div>
                <div className="llm-status-row">
                  <span className="llm-status-key">Endpoint</span>
                  <span className="llm-status-value">{llmStatus?.base_url}</span>
                </div>
                <div className="llm-status-row">
                  <span className="llm-status-key">Model</span>
                  <span className={llmStatus?.ready ? "ok" : "warn"}>
                    {llmStatus?.model
                      ? `${llmStatus.model} (${MODEL_SOURCE_LABELS[llmStatus.model_source] ?? llmStatus.model_source})`
                      : "未解決"}
                  </span>
                </div>
              </div>

              {llmStatus && !llmStatus.ready && llmStatus.diagnosis && (
                <AIErrorPanel diagnosis={llmStatus.diagnosis} onRecheck={refreshAll} />
              )}

              <h3>モデル選択</h3>
              <div className="select-card-grid select-card-grid-2">
                <SelectCard
                  title="Auto"
                  description="KairoがPC性能と用途から自動選択"
                  selected={settings.ai.mode === "auto"}
                  onSelect={() => applyPatch({ ai: { mode: "auto" } })}
                />
                <SelectCard
                  title="Manual"
                  description="自分でモデルを選択"
                  selected={settings.ai.mode === "manual"}
                  onSelect={() => applyPatch({ ai: { mode: "manual" } })}
                />
              </div>

              {settings.ai.mode === "auto" && (
                <div className="settings-ai-auto-box">
                  <div>
                    現在: <strong>{llmStatus?.model ?? "-"}</strong>
                  </div>
                  <button onClick={() => setShowWhy((v) => !v)}>{showWhy ? "理由を隠す" : "なぜ？"}</button>
                  {showWhy && recommendation && (
                    <ul className="settings-reasons-list">
                      {recommendation.reasons.map((r) => (
                        <li key={r}>{r}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              {settings.ai.mode === "manual" && (
                <>
                  <div className="settings-row-with-button">
                    <span>LM Studio利用可能モデル</span>
                    <button onClick={refreshAll}>LM Studioから再取得</button>
                  </div>
                  <div className="select-card-grid select-card-grid-3">
                    {models.map((m) => (
                      <SelectCard
                        key={m.id}
                        title={m.id}
                        description={m.recommended ? `推奨(${m.catalog_tier_label})` : "Available"}
                        selected={m.is_current}
                        onSelect={() => applyPatch({ ai: { mode: "manual", selected_model: m.id } })}
                      />
                    ))}
                    {models.length === 0 && (
                      <div className="generation-engine-reason">
                        LM Studioに接続できないか、利用可能なモデルがありません。
                      </div>
                    )}
                  </div>
                </>
              )}

              <h3>AI環境診断</h3>
              {recommendation && (
                <div className="settings-diagnosis-box">
                  <div>RAM: {recommendation.ram_gb.toFixed(0)}GB</div>
                  <div>GPU: {recommendation.gpu_names.join(", ") || "検出できませんでした"}</div>
                  <div>推奨tier: {recommendation.recommended_tier_label}</div>
                  <div>
                    AI適性: {STARS(recommendation.gpu_dedicated ? 5 : recommendation.ram_gb >= 24 ? 4 : recommendation.ram_gb >= 12 ? 3 : 2)}
                  </div>
                </div>
              )}

              <button onClick={() => setShowSetup((v) => !v)}>
                {showSetup ? "セットアップ案内を隠す" : "モデルをセットアップ"}
              </button>
              {showSetup && recommendation && (
                <div className="settings-setup-candidates">
                  <p className="generation-engine-reason">
                    Kairoはモデルを自動ダウンロードしません。以下を参考にLM Studio内で検索してダウンロードしてください。
                  </p>
                  {recommendation.setup_candidates.map((c) => (
                    <div key={c.id} className="settings-setup-card">
                      <div className="settings-setup-card-header">
                        <strong>{c.display_name}</strong>
                        <span>{STARS(c.recommendation_stars)}</span>
                      </div>
                      <div className="generation-engine-reason">{c.purpose}</div>
                      <div className="settings-setup-card-meta">
                        <span>サイズ: 約{c.size_gb}GB</span>
                        <span>必要空き容量: 約{c.required_free_gb}GB</span>
                        <span className={c.enough_disk_space ? "ok" : "bad"}>
                          空き容量: {c.current_free_gb}GB {c.enough_disk_space ? "(十分)" : "(不足)"}
                        </span>
                        <span>
                          推定ダウンロード時間: 約{c.estimated_download_minutes_low}〜
                          {c.estimated_download_minutes_high}分
                        </span>
                      </div>
                      {c.already_available && <div className="ok">✓ 既に利用可能なモデルがあります</div>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {tab === "video" && (
            <div className="settings-section">
              <h2>動画設定</h2>
              <div className="wizard-section-label">品質プリセット</div>
              <div className="select-card-grid select-card-grid-4">
                {QUALITY_PRESETS.map((q) => (
                  <SelectCard
                    key={q.id}
                    title={q.label}
                    description={q.description}
                    selected={settings.video.quality_preset === q.id}
                    onSelect={() => applyPatch({ video: { quality_preset: q.id } })}
                  />
                ))}
              </div>

              <div className="wizard-output-row" style={{ marginTop: 16 }}>
                <label className="scene-field">
                  解像度(幅)
                  <input
                    type="number"
                    value={settings.video.width}
                    onChange={(e) => applyPatch({ video: { width: Number(e.target.value) } })}
                  />
                </label>
                <label className="scene-field">
                  解像度(高さ)
                  <input
                    type="number"
                    value={settings.video.height}
                    onChange={(e) => applyPatch({ video: { height: Number(e.target.value) } })}
                  />
                </label>
                <label className="scene-field">
                  FPS
                  <input
                    type="number"
                    value={settings.video.fps}
                    onChange={(e) => applyPatch({ video: { fps: Number(e.target.value) } })}
                  />
                </label>
              </div>

              {videoWarning && (
                <div
                  className={
                    videoWarning.level === "recommended"
                      ? "ok"
                      : videoWarning.level === "caution"
                        ? "warn"
                        : "bad"
                  }
                  style={{ marginTop: 8 }}
                >
                  {videoWarning.level === "recommended" ? "●" : "⚠"} {videoWarning.reason}
                </div>
              )}
            </div>
          )}

          {tab === "performance" && (
            <div className="settings-section">
              <h2>パフォーマンス</h2>
              <div className="select-card-grid select-card-grid-3">
                {PERFORMANCE_PROFILES.map((p) => (
                  <SelectCard
                    key={p.id}
                    title={p.label}
                    description={p.description}
                    selected={settings.performance.profile === p.id}
                    onSelect={() => applyPatch({ performance: { profile: p.id } })}
                  />
                ))}
              </div>

              {settings.performance.profile === "custom" &&
                (() => {
                  const custom = {
                    width: settings.performance.custom?.width ?? settings.video.width,
                    height: settings.performance.custom?.height ?? settings.video.height,
                    fps: settings.performance.custom?.fps ?? settings.video.fps,
                    num_inference_steps: settings.performance.custom?.num_inference_steps ?? null,
                  };
                  return (
                    <div className="wizard-output-row" style={{ marginTop: 16 }}>
                      <label className="scene-field">
                        解像度(幅)
                        <input
                          type="number"
                          value={custom.width}
                          onChange={(e) =>
                            applyPatch({
                              performance: {
                                profile: "custom",
                                custom: { ...custom, width: Number(e.target.value) },
                              },
                            })
                          }
                        />
                      </label>
                      <label className="scene-field">
                        FPS
                        <input
                          type="number"
                          value={custom.fps}
                          onChange={(e) =>
                            applyPatch({
                              performance: {
                                profile: "custom",
                                custom: { ...custom, fps: Number(e.target.value) },
                              },
                            })
                          }
                        />
                      </label>
                    </div>
                  );
                })()}
            </div>
          )}

          {tab === "general" && (
            <div className="settings-section">
              <h2>一般 / ストレージ</h2>
              <p className="generation-engine-reason">
                言語・テーマ・出力先フォルダ変更などは今後対応予定です。現在のPC・ストレージ状態は下記で確認できます。
              </p>
              <SystemInfoPanel />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
