import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import SelectCard from "../components/create/SelectCard";
import AIErrorPanel from "../components/AIErrorPanel";
import SystemInfoPanel from "../components/SystemInfoPanel";
import TrendSettingsTab from "../components/settings/TrendSettingsTab";
import LibraryTab from "../components/settings/LibraryTab";
import ConnectedServicesTab from "../components/settings/ConnectedServicesTab";
import type {
  AppSettings,
  EngineCapabilities,
  LLMStatus,
  ModelInfo,
  ParallelismWarning,
  PerformanceProfile,
  QualityPreset,
  RecommendationOut,
  SubtitlePosition,
  SubtitleStyleT,
  TTSVoicesOut,
  VideoSettingWarning,
} from "../types";
import { MODEL_SOURCE_LABELS } from "../utils/format";

type Tab =
  | "ai"
  | "video"
  | "performance"
  | "tts"
  | "subtitle"
  | "generation"
  | "trends"
  | "library"
  | "services"
  | "general";

const TABS: { id: Tab; label: string }[] = [
  { id: "ai", label: "AI" },
  { id: "video", label: "動画" },
  { id: "performance", label: "パフォーマンス" },
  { id: "tts", label: "音声(TTS)" },
  { id: "subtitle", label: "字幕" },
  { id: "generation", label: "生成" },
  { id: "trends", label: "トレンド" },
  { id: "library", label: "素材ライブラリ" },
  { id: "services", label: "接続サービス" },
  { id: "general", label: "一般 / ストレージ" },
];

const SUBTITLE_POSITIONS: { id: SubtitlePosition; label: string }[] = [
  { id: "top", label: "上" },
  { id: "middle", label: "中央" },
  { id: "bottom", label: "下" },
];

const SUBTITLE_STYLES: { id: SubtitleStyleT; label: string; description: string }[] = [
  { id: "outline", label: "縁取り", description: "文字に輪郭線を付けて読みやすくします" },
  { id: "box", label: "背景ボックス", description: "文字の背景に半透明の帯を敷きます" },
  { id: "plain", label: "プレーン", description: "装飾なしの文字のみ" },
];

const PARALLELISM_OPTIONS: { id: number; label: string; description: string }[] = [
  { id: 0, label: "Auto", description: "PCのCPUコア数から自動選択" },
  { id: 1, label: "1", description: "同時に1件ずつ処理" },
  { id: 2, label: "2", description: "同時に2件まで処理" },
  { id: 3, label: "3", description: "同時に3件まで処理" },
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

  const [ttsVoices, setTtsVoices] = useState<TTSVoicesOut | null>(null);
  const [ttsPreviewText, setTtsPreviewText] = useState("こんにちは、Kairoの読み上げテストです。");
  const [ttsPreviewBusy, setTtsPreviewBusy] = useState(false);
  const [ttsPreviewError, setTtsPreviewError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const [engines, setEngines] = useState<EngineCapabilities[]>([]);
  const [parallelismWarning, setParallelismWarning] = useState<ParallelismWarning | null>(null);

  const refreshAll = () => {
    api.getSettings().then(setSettings).catch((e) => setError(String(e)));
    api.llmStatus().then(setLlmStatus).catch(() => {});
    api.getAiModels().then((r) => setModels(r.models)).catch(() => {});
    api.getAiRecommendation().then(setRecommendation).catch(() => {});
    api.getTtsVoices().then(setTtsVoices).catch(() => {});
    api.listGenerationEngines().then(setEngines).catch(() => {});
  };

  useEffect(refreshAll, []);

  useEffect(() => {
    if (!settings) return;
    api.checkParallelism(settings.generation.parallelism).then(setParallelismWarning).catch(() => {});
  }, [settings?.generation.parallelism]);

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
        // Refresh the model list too - its `is_current` flags are only as
        // fresh as the last fetch, so without this the selected card's
        // checkmark never moves after picking a different Manual model.
        api.getAiModels().then((r) => setModels(r.models)).catch(() => {});
      }
    } catch (e) {
      setError(String(e));
    }
  };

  const handleTtsPreview = async () => {
    setTtsPreviewError(null);
    setTtsPreviewBusy(true);
    try {
      const blob = await api.ttsPreview(ttsPreviewText, settings?.tts.selected_voice ?? null);
      const url = URL.createObjectURL(blob);
      if (audioRef.current) {
        audioRef.current.src = url;
        await audioRef.current.play();
      }
    } catch (e) {
      setTtsPreviewError(String(e));
    } finally {
      setTtsPreviewBusy(false);
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
                  {llmStatus === null ? (
                    <span>… 確認中</span>
                  ) : (
                    <span className={llmStatus.server_reachable ? "ok" : "bad"}>
                      {llmStatus.server_reachable ? "● Connected" : "● Disconnected"}
                    </span>
                  )}
                </div>
                <div className="llm-status-row">
                  <span className="llm-status-key">Endpoint</span>
                  <span className="llm-status-value">{llmStatus?.base_url ?? "-"}</span>
                </div>
                <div className="llm-status-row">
                  <span className="llm-status-key">Model</span>
                  {llmStatus === null ? (
                    <span>… 確認中</span>
                  ) : (
                    <span className={llmStatus.ready ? "ok" : "warn"}>
                      {llmStatus.model
                        ? `${llmStatus.model} (${MODEL_SOURCE_LABELS[llmStatus.model_source] ?? llmStatus.model_source})`
                        : "未解決"}
                    </span>
                  )}
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

          {tab === "tts" && (
            <div className="settings-section">
              <h2>音声(TTS)</h2>
              <p className="generation-engine-reason">
                ナレーションなどのテキストを、WindowsにインストールされているTTS(音声合成)エンジンで読み上げます。
              </p>

              <div className="select-card-grid select-card-grid-3">
                <SelectCard
                  title="Auto"
                  description="利用可能な音声から自動選択"
                  selected={settings.tts.mode === "auto"}
                  disabled={!ttsVoices?.available}
                  onSelect={() => applyPatch({ tts: { mode: "auto" } })}
                />
                <SelectCard
                  title="Off"
                  description="TTSを使用しない"
                  selected={settings.tts.mode === "off"}
                  onSelect={() => applyPatch({ tts: { mode: "off" } })}
                />
                <SelectCard
                  title="Manual"
                  description="自分で音声を選択"
                  selected={settings.tts.mode === "manual"}
                  disabled={!ttsVoices?.available}
                  onSelect={() => applyPatch({ tts: { mode: "manual" } })}
                />
              </div>

              <h3>利用可能な音声エンジン</h3>
              {ttsVoices === null && <div className="generation-engine-reason">確認中...</div>}
              {ttsVoices && !ttsVoices.available && (
                <div className="settings-diagnosis-box">
                  <div className="warn">現在利用可能なTTSエンジンがありません。</div>
                  <div className="generation-engine-reason">{ttsVoices.note}</div>
                </div>
              )}
              {ttsVoices?.available && settings.tts.mode === "manual" && (
                <div className="select-card-grid select-card-grid-3">
                  {ttsVoices.voices.map((v) => (
                    <SelectCard
                      key={v.id}
                      title={v.name}
                      description={`${v.culture} / ${v.gender === "Female" ? "女性" : v.gender === "Male" ? "男性" : v.gender}`}
                      selected={settings.tts.selected_voice === v.id}
                      onSelect={() => applyPatch({ tts: { mode: "manual", selected_voice: v.id } })}
                    />
                  ))}
                </div>
              )}
              {ttsVoices?.available && settings.tts.mode !== "manual" && (
                <div className="generation-engine-reason">{ttsVoices.note}</div>
              )}

              <h3>現在の音声</h3>
              <div className="settings-ai-auto-box">
                <div>
                  {settings.tts.mode === "off"
                    ? "TTSは無効です。"
                    : settings.tts.mode === "manual"
                      ? `選択中: ${ttsVoices?.voices.find((v) => v.id === settings.tts.selected_voice)?.name ?? "未選択"}`
                      : `Auto: ${ttsVoices?.voices[0]?.name ?? "利用可能な音声がありません"}`}
                </div>
                {settings.tts.mode !== "off" && ttsVoices?.available && (
                  <>
                    <textarea
                      className="wizard-content-input"
                      style={{ marginTop: 10 }}
                      rows={2}
                      value={ttsPreviewText}
                      onChange={(e) => setTtsPreviewText(e.target.value)}
                    />
                    <button style={{ marginTop: 8 }} onClick={handleTtsPreview} disabled={ttsPreviewBusy}>
                      {ttsPreviewBusy ? "生成中..." : "▶ 試聴する"}
                    </button>
                    {ttsPreviewError && <div className="wizard-error">{ttsPreviewError}</div>}
                    {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
                    <audio ref={audioRef} style={{ display: "none" }} />
                  </>
                )}
              </div>
            </div>
          )}

          {tab === "subtitle" && (
            <div className="settings-section">
              <h2>字幕</h2>
              <div className="select-card-grid select-card-grid-2">
                <SelectCard
                  title="ON"
                  description="書き出し時に字幕を焼き込み可能にする"
                  selected={settings.subtitle.enabled}
                  onSelect={() => applyPatch({ subtitle: { enabled: true } })}
                />
                <SelectCard
                  title="OFF"
                  description="字幕を焼き込まない"
                  selected={!settings.subtitle.enabled}
                  onSelect={() => applyPatch({ subtitle: { enabled: false } })}
                />
              </div>

              <div className="wizard-output-row" style={{ marginTop: 16 }}>
                <label className="scene-field">
                  フォント
                  <input
                    type="text"
                    value={settings.subtitle.font}
                    onChange={(e) => applyPatch({ subtitle: { font: e.target.value } })}
                  />
                </label>
                <label className="scene-field">
                  サイズ (px)
                  <input
                    type="number"
                    min={12}
                    max={200}
                    step={4}
                    value={settings.subtitle.size}
                    onChange={(e) => applyPatch({ subtitle: { size: Number(e.target.value) } })}
                  />
                  <span className="field-hint">
                    書き出す動画での実際の高さです。縦型ショートは 80〜100px が目安
                    （1行あたり約{Math.max(6, Math.round((1080 * 0.85) / (settings.subtitle.size * 1.02)))}文字）。
                  </span>
                </label>
                <label className="scene-field">
                  色
                  <input
                    type="color"
                    value={settings.subtitle.color}
                    onChange={(e) => applyPatch({ subtitle: { color: e.target.value } })}
                  />
                </label>
              </div>

              <div className="wizard-section-label" style={{ marginTop: 16 }}>
                位置
              </div>
              <div className="select-card-grid select-card-grid-3">
                {SUBTITLE_POSITIONS.map((p) => (
                  <SelectCard
                    key={p.id}
                    title={p.label}
                    selected={settings.subtitle.position === p.id}
                    onSelect={() => applyPatch({ subtitle: { position: p.id } })}
                  />
                ))}
              </div>

              <div className="wizard-section-label" style={{ marginTop: 16 }}>
                スタイル
              </div>
              <div className="select-card-grid select-card-grid-3">
                {SUBTITLE_STYLES.map((s) => (
                  <SelectCard
                    key={s.id}
                    title={s.label}
                    description={s.description}
                    selected={settings.subtitle.style === s.id}
                    onSelect={() => applyPatch({ subtitle: { style: s.id } })}
                  />
                ))}
              </div>

              <p className="generation-engine-reason" style={{ marginTop: 12 }}>
                これらの設定は、編集画面の「書き出し」で字幕を焼き込む際に実際に反映されます。
              </p>
            </div>
          )}

          {tab === "generation" && (
            <div className="settings-section">
              <h2>生成</h2>

              <div className="wizard-section-label">並列数</div>
              <div className="select-card-grid select-card-grid-4">
                {PARALLELISM_OPTIONS.map((p) => (
                  <SelectCard
                    key={p.id}
                    title={p.label}
                    description={p.description}
                    selected={settings.generation.parallelism === p.id}
                    onSelect={() => applyPatch({ generation: { parallelism: p.id } })}
                  />
                ))}
              </div>
              {parallelismWarning && (
                <div
                  className={
                    parallelismWarning.level === "recommended"
                      ? "ok"
                      : parallelismWarning.level === "caution"
                        ? "warn"
                        : "bad"
                  }
                  style={{ marginTop: 8 }}
                >
                  {parallelismWarning.level === "recommended" ? "●" : "⚠"} {parallelismWarning.reason}
                </div>
              )}

              <div className="wizard-section-label" style={{ marginTop: 20 }}>
                キャッシュ
              </div>
              <div className="select-card-grid select-card-grid-2">
                <SelectCard
                  title="有効"
                  description="変更していないクリップの書き出しキャッシュを再利用します(高速)"
                  selected={settings.generation.cache_enabled}
                  onSelect={() => applyPatch({ generation: { cache_enabled: true } })}
                />
                <SelectCard
                  title="無効"
                  description="毎回すべて再生成します(低速・トラブル時の切り分け用)"
                  selected={!settings.generation.cache_enabled}
                  onSelect={() => applyPatch({ generation: { cache_enabled: false } })}
                />
              </div>

              <div className="wizard-section-label" style={{ marginTop: 20 }}>
                既定の生成エンジン
              </div>
              <div className="select-card-grid select-card-grid-3">
                {engines.map((eng) => (
                  <SelectCard
                    key={eng.id}
                    title={eng.display_name}
                    description={eng.status === "ready" ? "準備完了" : eng.status_reason}
                    selected={settings.generation.default_engine_id === eng.id}
                    onSelect={() => applyPatch({ generation: { default_engine_id: eng.id } })}
                  />
                ))}
              </div>
            </div>
          )}

          {tab === "trends" && settings && (
            <TrendSettingsTab settings={settings.trends} applyPatch={applyPatch} />
          )}

          {tab === "library" && settings && (
            <LibraryTab settings={settings.library} applyPatch={applyPatch} />
          )}

          {tab === "services" && settings && (
            <ConnectedServicesTab
              refinement={settings.refinement}
              applyPatch={applyPatch}
            />
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
