import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { SystemInfo } from "../types";

interface Props {
  onOpenDetail: () => void;
}

// A compact "現在の環境" card for the export step - the full breakdown
// still lives in SystemInfoPanel (PC診断), this just surfaces the handful
// of facts that matter right before rendering: can we use the GPU, and if
// not, say so plainly rather than let a slow CPU render look like a hang.
export default function SystemEnvSummary({ onOpenDetail }: Props) {
  const [info, setInfo] = useState<SystemInfo | null>(null);

  useEffect(() => {
    api.getSystemInfo().then(setInfo).catch(() => {});
  }, []);

  if (!info) return null;

  const gpuAvailable = !!info.gpu.names && info.gpu.names.length > 0 && info.ai_runtime.cuda_available;
  const renderCapability = info.capabilities.find((c) => c.label.includes("レンダリング"));

  return (
    <div className="system-env-summary">
      <div className="panel-header">
        現在の環境
        <button onClick={onOpenDetail}>詳細を見る</button>
      </div>
      <div className="system-env-grid">
        <div>
          <span className="video-settings-label">CPU</span>
          <span>{info.cpu.name}</span>
        </div>
        <div>
          <span className="video-settings-label">メモリ</span>
          <span>{info.ram.total_gb}GB</span>
        </div>
        <div>
          <span className="video-settings-label">GPU</span>
          <span className={gpuAvailable ? "ok" : "warn"}>
            {info.gpu.names ? info.gpu.names[0] : "利用不可"}
          </span>
        </div>
        <div>
          <span className="video-settings-label">FFmpeg</span>
          <span className={info.ffmpeg.available ? "ok" : "bad"}>
            {info.ffmpeg.available ? `● ${info.ffmpeg.version ?? "利用可能"}` : "● 未検出"}
          </span>
        </div>
      </div>
      {!gpuAvailable && (
        <div className="system-env-note">
          CPUレンダリングで処理します。通常より生成時間が長くなる可能性があります。
        </div>
      )}
      {renderCapability && renderCapability.level !== "green" && (
        <div className="system-env-note">{renderCapability.reason}</div>
      )}
    </div>
  );
}
