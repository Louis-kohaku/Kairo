import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Project } from "../types";

export default function ProjectList({
  onOpen,
  onCreateNew,
  onOpenSettings,
}: {
  onOpen: (id: string) => void;
  onCreateNew: () => void;
  onOpenSettings: () => void;
}) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    api
      .listProjects()
      .then(setProjects)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(refresh, []);

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: 32 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <h1 style={{ fontWeight: 600, margin: 0 }}>Kairo</h1>
          <p style={{ color: "var(--text-dim)", margin: "4px 0 0" }}>
            ローカル完結型 AI 動画制作・編集システム
          </p>
        </div>
        <button onClick={onOpenSettings}>⚙ 設定</button>
      </div>

      <button className="primary" onClick={onCreateNew} style={{ width: "100%", padding: 16, margin: "24px 0", fontSize: 15 }}>
        + 新しい動画を作成
      </button>

      {error && <div style={{ color: "var(--danger)" }}>{error}</div>}
      {loading && <div style={{ color: "var(--text-dim)" }}>読み込み中...</div>}

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {projects.map((p) => (
          <button
            key={p.id}
            onClick={() => onOpen(p.id)}
            style={{
              textAlign: "left",
              padding: "12px 16px",
              display: "flex",
              justifyContent: "space-between",
            }}
          >
            <span>{p.name}</span>
            <span style={{ color: "var(--text-dim)" }}>
              {p.width}x{p.height} · {p.fps}fps
            </span>
          </button>
        ))}
        {!loading && projects.length === 0 && (
          <div style={{ color: "var(--text-dim)" }}>
            プロジェクトがありません。上のボタンから作成してください。
          </div>
        )}
      </div>
    </div>
  );
}
