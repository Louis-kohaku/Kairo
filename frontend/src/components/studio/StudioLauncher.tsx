import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { ModelPlan } from "../../types";
import ModelPlanPanel from "./ModelPlanPanel";

/**
 * The start screen for a production (design doc sections 10/48).
 *
 * The order here is the order section 10 specifies: say what you want,
 * see what will be used to make it, confirm those things are ready, then
 * start. The AI preparation checklist is the thing that turns "it failed"
 * into "here is what is missing and how to get it" *before* any work
 * begins.
 */

const DURATION_PRESETS = [
  { label: "15秒", value: 15 },
  { label: "30秒", value: 30 },
  { label: "60秒", value: 60 },
  { label: "90秒", value: 90 },
  { label: "3分", value: 180 },
];

const ORIENTATIONS = [
  { id: "vertical", label: "縦型 9:16", hint: "TikTok / Shorts / Reels" },
  { id: "horizontal", label: "横型 16:9", hint: "YouTube / PC" },
  { id: "square", label: "正方形 1:1", hint: "フィード投稿" },
];

const EXAMPLES = [
  "猫が初めて雪を見る。1分の縦型ショート。可愛くて少し笑える動画。",
  "朝の5分でできる簡単ストレッチを紹介する30秒の縦型動画。",
  "コーヒーの淹れ方のコツを3つ紹介する、落ち着いたトーンの60秒動画。",
];

export default function StudioLauncher({
  mode,
  onStart,
  busy,
  error,
}: {
  mode: "full_auto" | "co_creation";
  onStart: (opts: {
    instruction: string;
    targetDurationSeconds: number;
    orientation: string;
    mode: "full_auto" | "co_creation";
  }) => void;
  busy?: boolean;
  error?: string | null;
}) {
  const [instruction, setInstruction] = useState("");
  const [duration, setDuration] = useState(60);
  const [orientation, setOrientation] = useState("vertical");
  const [plan, setPlan] = useState<ModelPlan | null>(null);
  const [checking, setChecking] = useState(true);

  const refreshPlan = () => {
    setChecking(true);
    api
      .getModelPlan()
      .then(setPlan)
      .catch(() => setPlan(null))
      .finally(() => setChecking(false));
  };

  useEffect(refreshPlan, []);

  const blocked = plan != null && plan.blocking.length > 0;
  const canStart = !!instruction.trim() && !busy && !blocked;

  return (
    <div className="launcher">
      <div className="launcher-main">
        <h1 className="launcher-title">
          {mode === "full_auto" ? "Full Auto で動画を作る" : "AIと相談しながら作る"}
        </h1>
        <p className="launcher-lead">
          {mode === "full_auto"
            ? "作りたい動画を一言で入力してください。企画・調査・脚本・素材・音声・字幕・編集・品質チェック・書き出しまで、Kairoが最後まで進めます。"
            : "作りたい動画を入力すると、AIが制作を始めます。途中でチャットから「もっとテンポよく」のように指示できます。"}
        </p>

        <label className="launcher-field">
          <span className="launcher-label">どんな動画を作りますか？</span>
          <textarea
            className="launcher-instruction"
            rows={3}
            value={instruction}
            placeholder="例: 猫が初めて雪を見る。1分の縦型ショート。可愛くて少し笑える動画。"
            onChange={(e) => setInstruction(e.target.value)}
            disabled={busy}
          />
        </label>

        <div className="launcher-examples">
          {EXAMPLES.map((ex) => (
            <button key={ex} onClick={() => setInstruction(ex)} disabled={busy}>
              {ex.slice(0, 22)}…
            </button>
          ))}
        </div>

        <div className="launcher-options">
          <div className="launcher-option-group">
            <span className="launcher-label">長さ</span>
            <div className="launcher-chips">
              {DURATION_PRESETS.map((p) => (
                <button
                  key={p.value}
                  className={duration === p.value ? "chip chip-on" : "chip"}
                  onClick={() => setDuration(p.value)}
                  disabled={busy}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          <div className="launcher-option-group">
            <span className="launcher-label">画面の形</span>
            <div className="launcher-chips">
              {ORIENTATIONS.map((o) => (
                <button
                  key={o.id}
                  className={orientation === o.id ? "chip chip-on" : "chip"}
                  onClick={() => setOrientation(o.id)}
                  disabled={busy}
                  title={o.hint}
                >
                  {o.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {error && <div className="wizard-error">{error}</div>}

        <button
          className="primary launcher-start"
          onClick={() =>
            onStart({
              instruction,
              targetDurationSeconds: duration,
              orientation,
              mode,
            })
          }
          disabled={!canStart}
          title={blocked ? "AIの準備が完了していません" : undefined}
        >
          {busy ? "開始しています…" : mode === "full_auto" ? "制作を開始" : "AIと作り始める"}
        </button>

        {blocked && (
          <div className="launcher-blocked">
            右のAI準備状況を確認してください。準備ができたら「再確認」を押すと開始できます。
          </div>
        )}
      </div>

      <aside className="launcher-side">
        <PreparationChecklist plan={plan} checking={checking} />
        <ModelPlanPanel plan={plan} onRefresh={refreshPlan} compact />
      </aside>
    </div>
  );
}

/**
 * Section 10's explicit preparation phase, shown before anything runs so a
 * missing model is a checklist item rather than a mid-production failure.
 */
function PreparationChecklist({
  plan,
  checking,
}: {
  plan: ModelPlan | null;
  checking: boolean;
}) {
  const steps = [
    {
      label: "LM Studio確認",
      done: plan != null && plan.llm_error_code !== "LM_STUDIO_CONNECTION_FAILED",
    },
    {
      label: "API接続確認",
      done:
        plan != null &&
        !["LM_STUDIO_CONNECTION_FAILED", "MODELS_FETCH_FAILED"].includes(plan.llm_error_code),
    },
    { label: "AIモデル確認", done: plan != null && plan.llm_ready },
    {
      label: "映像・音声・書き出しの確認",
      done:
        plan != null &&
        plan.roles
          .filter((r) => ["visual", "editor"].includes(r.id))
          .every((r) => r.ready),
    },
    { label: "制作開始", done: plan != null && plan.blocking.length === 0 },
  ];

  return (
    <div className="prep-checklist">
      <div className="prep-title">AI制作準備</div>
      {checking && <div className="prep-checking">確認しています…</div>}
      <ul>
        {steps.map((s, i) => {
          const active = !s.done && steps.slice(0, i).every((p) => p.done);
          return (
            <li key={s.label} className={s.done ? "done" : active ? "active" : "pending"}>
              <span className="prep-mark">{s.done ? "✓" : active ? "●" : "○"}</span>
              {s.label}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
