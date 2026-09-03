import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { MaterialMode, ModelPlan } from "../../types";
import { useMaterials } from "../../hooks/useMaterials";
import MaterialPanel from "./MaterialPanel";
import MaterialPlanPanel from "./MaterialPlanPanel";
import ModelPlanPanel from "./ModelPlanPanel";

/**
 * The start screen for a production (design doc sections 10/48, extended
 * for user material).
 *
 * The order on screen is the order the user thinks in:
 *
 *   ① 作りたい動画  - the one-line brief
 *   ② 素材          - their own photos and videos (optional)
 *   ③ 動画設定      - orientation and length
 *   ④ 制作開始      - the material plan, then go
 *
 * Material is second, not hidden in a settings screen, because handing
 * over photos is half of what this mode is for. It is also explicitly
 * optional at the point of asking, so a user with nothing to upload is not
 * left wondering whether the tool is for them.
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
  "この写真と動画を使って沖縄旅行の30秒Shortsを作って。",
  "猫が初めて雪を見る。1分の縦型ショート。可愛くて少し笑える動画。",
  "朝の5分でできる簡単ストレッチを紹介する30秒の縦型動画。",
];

export default function StudioLauncher({
  projectId,
  mode,
  onStart,
  busy,
  error,
}: {
  projectId: string;
  mode: "full_auto" | "co_creation";
  onStart: (opts: {
    instruction: string;
    targetDurationSeconds: number;
    orientation: string;
    mode: "full_auto" | "co_creation";
    materialMode: MaterialMode;
    selectedAssetIds: string[];
  }) => void;
  busy?: boolean;
  error?: string | null;
}) {
  const [instruction, setInstruction] = useState("");
  const [duration, setDuration] = useState(30);
  const [orientation, setOrientation] = useState("vertical");
  const [plan, setPlan] = useState<ModelPlan | null>(null);
  const [checking, setChecking] = useState(true);

  const material = useMaterials(projectId, duration);

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
  const noSelection =
    material.mode === "selected" && material.selectedIds.length === 0;
  const canStart = !!instruction.trim() && !busy && !blocked && !noSelection;

  const start = () =>
    onStart({
      instruction,
      targetDurationSeconds: duration,
      orientation,
      mode,
      materialMode: material.mode,
      selectedAssetIds: material.selectedIds,
    });

  return (
    <div className="launcher">
      <div className="launcher-main">
        <h1 className="launcher-title">
          {mode === "full_auto" ? "Full Auto で動画を作る" : "AIと相談しながら作る"}
        </h1>
        <p className="launcher-lead">
          {mode === "full_auto"
            ? "作りたい動画を一言で入力し、あれば写真・動画を渡してください。素材解析・企画・脚本・編集・字幕・音・書き出しまで、Kairoが最後まで進めます。"
            : "作りたい動画と素材を渡すとAIが制作を始めます。途中でチャットから「もっとテンポよく」のように指示できます。"}
        </p>

        <section className="launcher-step">
          <div className="launcher-step-head">
            <span className="launcher-step-no">①</span>
            <span className="launcher-step-title">作りたい動画</span>
          </div>
          <textarea
            className="launcher-instruction"
            rows={3}
            value={instruction}
            placeholder="例: この写真と動画を使って沖縄旅行の30秒Shortsを作って。"
            onChange={(e) => setInstruction(e.target.value)}
            disabled={busy}
          />
          <div className="launcher-examples">
            {EXAMPLES.map((ex) => (
              <button key={ex} onClick={() => setInstruction(ex)} disabled={busy}>
                {ex.slice(0, 22)}…
              </button>
            ))}
          </div>
        </section>

        <section className="launcher-step">
          <div className="launcher-step-head">
            <span className="launcher-step-no">②</span>
            <span className="launcher-step-title">素材</span>
            <span className="launcher-step-sub">写真・動画を追加（任意）</span>
          </div>
          <MaterialPanel
            projectId={projectId}
            materials={material.materials}
            loading={material.loading}
            visionAvailable={material.visionAvailable}
            mode={material.mode}
            selectedIds={material.selectedIds}
            onModeChange={material.setMode}
            onSelectionChange={material.setSelectedIds}
            onChanged={material.reload}
            busy={busy}
          />
          {material.error && <div className="wizard-error">{material.error}</div>}
        </section>

        <section className="launcher-step">
          <div className="launcher-step-head">
            <span className="launcher-step-no">③</span>
            <span className="launcher-step-title">動画設定</span>
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
        </section>

        <section className="launcher-step">
          <div className="launcher-step-head">
            <span className="launcher-step-no">④</span>
            <span className="launcher-step-title">
              {material.mode === "ai_auto" ? "AIにおまかせで制作" : "制作開始"}
            </span>
          </div>

          <MaterialPlanPanel plan={material.plan} />

          {error && <div className="wizard-error">{error}</div>}

          <button
            className="primary launcher-start"
            onClick={start}
            disabled={!canStart}
            title={
              blocked
                ? "AIの準備が完了していません"
                : noSelection
                  ? "「選択した素材だけ使う」を選んでいます。使う素材にチェックを入れてください。"
                  : undefined
            }
          >
            {busy
              ? "開始しています…"
              : material.materials.length > 0
                ? "この内容で制作開始"
                : mode === "full_auto"
                  ? "制作を開始"
                  : "AIと作り始める"}
          </button>

          {noSelection && (
            <div className="launcher-blocked">
              「選択した素材だけ使う」が選ばれています。使いたい素材にチェックを入れてください。
            </div>
          )}
          {blocked && (
            <div className="launcher-blocked">
              右のAI準備状況を確認してください。準備ができたら「再確認」を押すと開始できます。
            </div>
          )}
        </section>
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
