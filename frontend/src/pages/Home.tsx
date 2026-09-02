import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Project } from "../types";
import { aspectRatioLabel, formatRelativeDate } from "../utils/format";

/**
 * The first screen (design doc section 48).
 *
 * Its one job is that opening Kairo never leaves you wondering what to do.
 * Three ways to make a video, each with what it actually means, and the
 * existing projects underneath. Everything else - settings, models,
 * diagnostics - lives inside the same app rather than a separate admin
 * area (section 49).
 */

type Mode = "full_auto" | "co_creation" | "manual";

const MODES: {
  id: Mode;
  icon: string;
  title: string;
  lead: string;
  detail: string;
}[] = [
  {
    id: "full_auto",
    icon: "⚡",
    title: "Full Auto",
    lead: "最初の指示だけで完成",
    detail:
      "調査・企画・脚本・素材・音声・字幕・編集・品質チェック・書き出しまで、Kairoが最後まで進めます。待っているだけでMP4ができます。",
  },
  {
    id: "co_creation",
    icon: "💬",
    title: "AI Co-Creation",
    lead: "AIと相談しながら作る",
    detail:
      "AIが制作を進めながら、「もっとテンポよく」「字幕を大きく」のような指示を受け付けます。指示は実際のプロジェクトに反映されます。",
  },
  {
    id: "manual",
    icon: "✂",
    title: "Manual",
    lead: "自分で編集する",
    detail:
      "素材の読み込み、タイムライン編集、字幕、無音カット、書き出しを自分で行います。AI生成と自由に組み合わせられます。",
  },
];

export default function Home({
  onCreate,
  onOpenProject,
  onOpenSettings,
}: {
  onCreate: (mode: Mode) => void;
  onOpenProject: (projectId: string, mode: Mode) => void;
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
    <div className="home-page">
      <header className="home-header">
        <div>
          <h1 className="home-title">Kairo</h1>
          <p className="home-subtitle">ローカルAI動画制作スタジオ</p>
        </div>
        <button onClick={onOpenSettings}>⚙ 設定</button>
      </header>

      <section className="home-modes">
        <h2 className="home-section-title">新しい動画を作る</h2>
        <div className="mode-grid">
          {MODES.map((m) => (
            <button key={m.id} className="mode-card" onClick={() => onCreate(m.id)}>
              <span className="mode-icon" aria-hidden>
                {m.icon}
              </span>
              <span className="mode-title">{m.title}</span>
              <span className="mode-lead">{m.lead}</span>
              <span className="mode-detail">{m.detail}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="home-projects">
        <h2 className="home-section-title">続きから</h2>

        {error && <div className="wizard-error">{error}</div>}
        {loading && <div className="project-list-empty">読み込み中…</div>}

        {!loading && projects.length === 0 && (
          <div className="project-list-empty">
            まだプロジェクトがありません。上から作り方を選んでください。
          </div>
        )}

        <div className="project-card-grid">
          {projects.map((p) => (
            <div key={p.id} className="project-card">
              <button className="project-card-open" onClick={() => onOpenProject(p.id, "full_auto")}>
                <div className="project-card-name">{p.name}</div>
                <div className="project-card-meta">
                  {aspectRatioLabel(p.width, p.height)} · {p.width}×{p.height} · {p.fps}fps
                </div>
                <div className="project-card-meta project-card-updated">
                  更新: {formatRelativeDate(p.updated_at)}
                </div>
              </button>

              <div className="project-card-actions">
                <button onClick={() => onOpenProject(p.id, "full_auto")}>制作を開く</button>
                <button onClick={() => onOpenProject(p.id, "manual")}>手動編集</button>
                <div
                  className="project-card-menu-wrap"
                  ref={menuOpenId === p.id ? menuRef : undefined}
                >
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
                          onOpenProject(p.id, "co_creation");
                        }}
                      >
                        AIと相談して編集
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
      </section>

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
                {deleting ? "削除中…" : "削除"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
