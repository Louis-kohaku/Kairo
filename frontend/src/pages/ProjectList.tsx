import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Project } from "../types";
import { aspectRatioLabel, formatRelativeDate } from "../utils/format";

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
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Project | null>(null);
  const [deleting, setDeleting] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const refresh = () => {
    setLoading(true);
    api
      .listProjects()
      .then(setProjects)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(refresh, []);

  useEffect(() => {
    if (!menuOpenId) return;
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpenId(null);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [menuOpenId]);

  const handleConfirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.deleteProject(deleteTarget.id);
      setProjects((prev) => prev.filter((p) => p.id !== deleteTarget.id));
      setDeleteTarget(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="project-list-page">
      <div className="project-list-header">
        <div>
          <h1 className="project-list-title">Kairo</h1>
          <p className="project-list-subtitle">ローカル完結型 AI 動画制作・編集システム</p>
        </div>
        <button onClick={onOpenSettings}>⚙ 設定</button>
      </div>

      <button className="primary project-list-create-btn" onClick={onCreateNew}>
        + 新しい動画を作成
      </button>

      {error && <div className="wizard-error">{error}</div>}
      {loading && <div className="project-list-empty">読み込み中...</div>}

      {!loading && projects.length === 0 && (
        <div className="project-list-empty">
          プロジェクトがありません。上のボタンから作成してください。
        </div>
      )}

      <div className="project-card-grid">
        {projects.map((p) => (
          <div key={p.id} className="project-card">
            <button className="project-card-open" onClick={() => onOpen(p.id)}>
              <div className="project-card-name">{p.name}</div>
              <div className="project-card-meta">
                {aspectRatioLabel(p.width, p.height)} · {p.width}×{p.height} · {p.fps}fps
              </div>
              <div className="project-card-meta project-card-updated">
                更新: {formatRelativeDate(p.updated_at)}
              </div>
            </button>

            <div className="project-card-actions">
              <button onClick={() => onOpen(p.id)}>開く</button>
              <div className="project-card-menu-wrap" ref={menuOpenId === p.id ? menuRef : undefined}>
                <button
                  aria-label="その他の操作"
                  className="project-card-menu-btn"
                  onClick={() => setMenuOpenId((cur) => (cur === p.id ? null : p.id))}
                >
                  •••
                </button>
                {menuOpenId === p.id && (
                  <div className="project-card-menu">
                    <button
                      onClick={() => {
                        setMenuOpenId(null);
                        onOpen(p.id);
                      }}
                    >
                      開く
                    </button>
                    <button
                      className="danger"
                      onClick={() => {
                        setMenuOpenId(null);
                        setDeleteTarget(p);
                      }}
                    >
                      削除
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {deleteTarget && (
        <div className="modal-overlay" onClick={() => !deleting && setDeleteTarget(null)}>
          <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
            <div className="modal-title">このプロジェクトを削除しますか？</div>
            <div className="modal-body">
              <div className="modal-project-name">プロジェクト: {deleteTarget.name}</div>
              <div className="modal-warning">この操作は元に戻せません。</div>
            </div>
            <div className="modal-actions">
              <button onClick={() => setDeleteTarget(null)} disabled={deleting}>
                キャンセル
              </button>
              <button className="danger primary" onClick={handleConfirmDelete} disabled={deleting}>
                {deleting ? "削除中..." : "削除"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
