import { useState } from "react";
import { api } from "../../api/client";
import type { LMModel, ModelPlan } from "../../types";

/**
 * "今回使用するAI" (design doc sections 9-15).
 *
 * Every row is resolved live from LM Studio and the machine - there are no
 * hardcoded model names anywhere in this component, which is the point:
 * showing a plausible-looking model that isn't the one Kairo will call is
 * worse than showing nothing.
 *
 * It also distinguishes downloaded from loaded. LM Studio's /v1/models
 * lists everything on disk, so a machine with six models and none in
 * memory used to read as "Loaded"; the backend reads LM Studio's own API
 * for the real state and this surfaces it, including the "first request
 * will be slow while it loads" consequence.
 */

const STATUS_LABEL: Record<string, string> = {
  ready: "利用可能",
  not_ready: "準備が必要",
  unavailable: "利用不可",
  optional: "任意(未導入)",
  skipped: "今回は不使用",
  degraded: "制限あり",
};

export default function ModelPlanPanel({
  plan,
  onRefresh,
  compact = false,
}: {
  plan: ModelPlan | null;
  onRefresh?: () => void;
  compact?: boolean;
}) {
  const [expanded, setExpanded] = useState(!compact);
  const [showPicker, setShowPicker] = useState(false);

  if (!plan) {
    return <div className="model-plan model-plan-loading">AIモデルを確認しています…</div>;
  }

  const visible = expanded ? plan.roles : plan.roles.filter((r) => r.status !== "optional");

  return (
    <div className="model-plan">
      <div className="model-plan-head">
        <span className="model-plan-title">今回使用するAI</span>
        <span style={{ flex: 1 }} />
        {onRefresh && (
          <button onClick={onRefresh} className="model-plan-btn">
            再確認
          </button>
        )}
        <button onClick={() => setShowPicker(true)} className="model-plan-btn">
          モデルを選ぶ
        </button>
        {compact && (
          <button onClick={() => setExpanded((v) => !v)} className="model-plan-btn">
            {expanded ? "簡易表示" : "すべて表示"}
          </button>
        )}
      </div>

      {plan.blocking.length > 0 && (
        <div className="model-plan-blocking">
          <div className="model-plan-blocking-title">⚠ このままでは制作を開始できません</div>
          {plan.blocking.map((b, i) => (
            <div key={i} className="model-plan-blocking-item">
              {b}
            </div>
          ))}
        </div>
      )}

      {plan.warnings.map((w, i) => (
        <div key={i} className="model-plan-warning">
          {w}
        </div>
      ))}

      <div className="model-role-list">
        {visible.map((role) => (
          <div key={role.id} className={`model-role model-role-${role.status}`}>
            <div className="model-role-label">{role.label}</div>
            <div className="model-role-model">{role.model ?? "(未解決)"}</div>
            <div className="model-role-provider">{role.provider}</div>
            <div className={`model-role-status model-role-status-${role.status}`}>
              {STATUS_LABEL[role.status] ?? role.status}
            </div>
            <div className="model-role-detail">{role.detail}</div>
            {role.remedy.length > 0 && (
              <ul className="model-role-remedy">
                {role.remedy.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>

      {showPicker && (
        <ModelPicker
          models={plan.available_models}
          currentId={plan.llm_model}
          onClose={() => setShowPicker(false)}
          onChanged={() => {
            setShowPicker(false);
            onRefresh?.();
          }}
        />
      )}
    </div>
  );
}

/**
 * Model chooser (section 13), written for someone who does not know what a
 * quantisation is: each option leads with what it is good for and what it
 * costs, and the technical id is secondary.
 */
function ModelPicker({
  models,
  currentId,
  onClose,
  onChanged,
}: {
  models: LMModel[];
  currentId: string | null;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [selected, setSelected] = useState<string | null>(currentId);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const chat = models.filter((m) => m.chat_capable);
  const other = models.filter((m) => !m.chat_capable);

  const apply = async () => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await api.updateSettings({ ai: { mode: "manual", selected_model: selected } });
      setMessage("このモデルを使用するよう設定しました。");
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const preload = async () => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    setMessage("モデルを読み込んでいます。数分かかることがあります…");
    try {
      const res = await api.loadModel(selected);
      setMessage(res.detail);
      onChanged();
    } catch (e) {
      setError(String(e));
      setMessage(null);
    } finally {
      setBusy(false);
    }
  };

  const useAuto = async () => {
    setBusy(true);
    try {
      await api.updateSettings({ ai: { mode: "auto", clear_selected_model: true } });
      setMessage("PCに合わせてKairoが自動で選びます。");
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel modal-panel-wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-title">AIモデル</div>

        {models.length === 0 && (
          <div className="model-picker-empty">
            LM Studioに利用できるモデルがありません。LM Studioを起動し、
            チャット用モデルをダウンロードしてから「再確認」を押してください。
          </div>
        )}

        <div className="model-picker-list">
          {chat.map((m) => (
            <label
              key={m.id}
              className={`model-picker-item${selected === m.id ? " selected" : ""}`}
            >
              <input
                type="radio"
                name="model"
                checked={selected === m.id}
                onChange={() => setSelected(m.id)}
              />
              <div className="model-picker-body">
                <div className="model-picker-name">
                  {m.id}
                  {m.recommended && <span className="model-picker-tag">おすすめ</span>}
                  {m.id === currentId && <span className="model-picker-tag current">使用中</span>}
                </div>
                <div className="model-picker-meta">
                  {m.tier_label ?? (m.kind === "vlm" ? "画像も扱えるモデル" : "テキストモデル")}
                  {m.quantization && ` · ${m.quantization}`}
                  {m.size_gb != null && ` · 約${m.size_gb.toFixed(1)}GB`}
                  {m.max_context_length != null &&
                    ` · 最大${Math.round(m.max_context_length / 1000)}k文脈`}
                </div>
                <div className="model-picker-state">
                  {m.state === "loaded"
                    ? "● メモリに読み込み済み(すぐ使えます)"
                    : m.state === "downloaded"
                      ? "○ ダウンロード済み(初回リクエスト時に読み込みます)"
                      : "状態不明"}
                </div>
              </div>
            </label>
          ))}
        </div>

        {other.length > 0 && (
          <div className="model-picker-note">
            チャットに使えないモデル({other.map((m) => m.id).join(", ")})は選択できません。
          </div>
        )}

        {message && <div className="model-picker-message">{message}</div>}
        {error && <div className="wizard-error">{error}</div>}

        <div className="modal-actions">
          <button onClick={useAuto} disabled={busy}>
            自動選択に戻す
          </button>
          <button onClick={preload} disabled={busy || !selected}>
            今すぐ読み込む
          </button>
          <span style={{ flex: 1 }} />
          <button onClick={onClose} disabled={busy}>
            閉じる
          </button>
          <button className="primary" onClick={apply} disabled={busy || !selected}>
            このモデルを使う
          </button>
        </div>
      </div>
    </div>
  );
}
