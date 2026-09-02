import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { SystemInfo } from "../types";

const LEVEL_DOT: Record<string, string> = {
  green: "🟢",
  yellow: "🟡",
  orange: "🟠",
  red: "🔴",
};

export default function SystemInfoPanel() {
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = () =>
    api
      .getSystemInfo()
      .then(setInfo)
      .catch((e) => setError(String(e)));

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (error) return <div style={{ color: "var(--danger)", padding: 16 }}>{error}</div>;
  if (!info) return <div style={{ padding: 16, color: "var(--text-dim)" }}>読み込み中...</div>;

  return (
    <div className="system-info-panel">
      <div className="panel-header">
        PC / AI環境
        <button onClick={refresh}>再取得</button>
      </div>

      <div className="system-info-grid">
        <div className="system-info-card">
          <h3>CPU</h3>
          <div>{info.cpu.name}</div>
          <div className="generation-engine-reason">
            物理コア {info.cpu.physical_cores ?? "?"} / 論理コア {info.cpu.logical_cores ?? "?"}
          </div>
        </div>

        <div className="system-info-card">
          <h3>RAM</h3>
          <div>
            {info.ram.total_gb} GB (空き {info.ram.available_gb} GB)
          </div>
        </div>

        <div className="system-info-card">
          <h3>GPU</h3>
          {info.gpu.names ? (
            info.gpu.names.map((name, i) => (
              <div key={name}>
                {name}
                <div className="generation-engine-reason">{info.gpu.vram_label?.[i] ?? ""}</div>
              </div>
            ))
          ) : (
            <div>取得できませんでした</div>
          )}
        </div>

        <div className="system-info-card">
          <h3>ストレージ</h3>
          <div>
            空き {info.disk.free_gb} GB / 全体 {info.disk.total_gb} GB
          </div>
          <div className="generation-engine-reason">{info.disk.data_root}</div>
        </div>

        <div className="system-info-card">
          <h3>OS</h3>
          <div>
            {info.os.name} {info.os.release}
          </div>
        </div>

        <div className="system-info-card">
          <h3>FFmpeg</h3>
          <div>{info.ffmpeg.available ? info.ffmpeg.version : "未検出"}</div>
        </div>

        <div className="system-info-card">
          <h3>AI実行環境</h3>
          <div>Python {info.ai_runtime.python_version}</div>
          <div>
            {info.ai_runtime.torch_installed
              ? `PyTorch ${info.ai_runtime.torch_version}`
              : "PyTorch未インストール(動画生成機能は利用できません)"}
          </div>
          <div className="generation-engine-reason">
            利用可能バックエンド: {info.ai_runtime.active_backends.join(", ") || "なし"}
          </div>
        </div>
      </div>

      <div className="panel-header">AI Pipeline</div>
      <div className="system-capability-list">
        {info.ai_pipeline.map((p) => (
          <div key={p.id} className="system-capability-row">
            <span>{p.ready ? "🟢" : "🔴"}</span>
            <span className="system-capability-label">
              {p.label}
              <span className="generation-engine-reason"> ({p.provider}{p.model ? ` / ${p.model}` : ""})</span>
            </span>
            <span className="generation-engine-reason">{p.detail}</span>
          </div>
        ))}
      </div>

      <div className="panel-header">このPCで何が実行可能か</div>
      <div className="system-capability-list">
        {info.capabilities.map((c) => (
          <div key={c.label} className="system-capability-row">
            <span>{LEVEL_DOT[c.level]}</span>
            <span className="system-capability-label">{c.label}</span>
            <span className="generation-engine-reason">{c.reason}</span>
          </div>
        ))}
      </div>

      <div className="panel-header">動画生成エンジン</div>
      <div className="system-capability-list">
        {info.video_generation_engines.map((e) => (
          <div key={e.id} className="system-capability-row">
            <span className="system-capability-label">{e.display_name}</span>
            <span className="generation-engine-reason">
              {e.commercial_use ? "商用利用可" : "非商用ライセンス"} / {e.notes}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
