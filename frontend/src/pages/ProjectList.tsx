import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Project } from "../types";

export default function ProjectList({
  onOpen,
}: {
  onOpen: (id: string) => void;
}) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [newName, setNewName] = useState("");
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

  const handleCreate = async () => {
    const name = newName.trim();
    if (!name) return;
    try {
      const project = await api.createProject(name);
      setNewName("");
      setProjects((prev) => [project, ...prev]);
      onOpen(project.id);
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: 32 }}>
      <h1 style={{ fontWeight: 600 }}>Kairo</h1>
      <p style={{ color: "var(--text-dim)" }}>
        ローカル完結型 AI 動画制作・編集システム
      </p>

      <div style={{ display: "flex", gap: 8, margin: "24px 0" }}>
        <input
          type="text"
          placeholder="新しいプロジェクト名"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          style={{ flex: 1 }}
        />
        <button className="primary" onClick={handleCreate}>
          作成
        </button>
      </div>

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
            プロジェクトがありません。上のフォームから作成してください。
          </div>
        )}
      </div>
    </div>
  );
}
