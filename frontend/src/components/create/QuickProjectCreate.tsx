import { useState } from "react";
import { api } from "../../api/client";

/**
 * The whole "new project" step for an AI production: a name, or not even
 * that.
 *
 * Full Auto and Co-Creation decide resolution, fps, length and content from
 * the instruction on the studio launcher, so the multi-step wizard the
 * manual path uses would be pure friction here - and section 1 is explicit
 * that the AI path must not ask unnecessary questions.
 */
export default function QuickProjectCreate({
  mode,
  onCreated,
  onCancel,
}: {
  mode: "full_auto" | "co_creation";
  onCreated: (projectId: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const fallback = `${mode === "full_auto" ? "Full Auto" : "AI Co-Creation"} ${new Date().toLocaleDateString()}`;
      // Vertical by default; the launcher's orientation choice updates the
      // project before the run starts.
      const project = await api.createProject(name.trim() || fallback, 30, 1080, 1920);
      onCreated(project.id);
    } catch (e) {
      setError(String(e));
      setBusy(false);
    }
  };

  return (
    <div className="quick-create">
      <div className="quick-create-card">
        <h1>{mode === "full_auto" ? "⚡ Full Auto" : "💬 AI Co-Creation"}</h1>
        <p className="quick-create-lead">
          プロジェクト名だけ決めてください。動画の内容・長さ・画面の形は次の画面で指定します。
        </p>

        <label className="quick-create-field">
          プロジェクト名（省略可）
          <input
            autoFocus
            value={name}
            placeholder="例: 猫と初雪"
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !busy && create()}
            disabled={busy}
          />
        </label>

        {error && <div className="wizard-error">{error}</div>}

        <div className="quick-create-actions">
          <button onClick={onCancel} disabled={busy}>
            戻る
          </button>
          <button className="primary" onClick={create} disabled={busy}>
            {busy ? "作成中…" : "次へ"}
          </button>
        </div>
      </div>
    </div>
  );
}
