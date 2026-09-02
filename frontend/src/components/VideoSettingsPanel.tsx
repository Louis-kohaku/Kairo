import { useState } from "react";
import { api } from "../api/client";
import type { Project, QualityPreset } from "../types";
import { formatBytes, formatSecondsRangeAsMinutes } from "../utils/format";
import { estimateFileSizeMB, estimateRenderSeconds } from "../utils/renderEstimate";
import { ASPECTS, QUALITY_PRESETS, aspectFromResolution, resolutionFor, type Aspect } from "../utils/videoPresets";

const FPS_OPTIONS = [24, 30, 60];

interface Props {
  project: Project;
  quality: QualityPreset;
  onQualityChange: (q: QualityPreset) => void;
  totalDurationSeconds: number;
  clipCount: number;
  cpuOnly: boolean;
  onUpdated: (project: Project) => void;
}

export default function VideoSettingsPanel({
  project,
  quality,
  onQualityChange,
  totalDurationSeconds,
  clipCount,
  cpuOnly,
  onUpdated,
}: Props) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const aspect = aspectFromResolution(project.width, project.height);

  const apply = async (patch: Partial<Pick<Project, "width" | "height" | "fps">>) => {
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateProject(project.id, patch);
      onUpdated(updated);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleAspect = (a: Aspect) => {
    const res = resolutionFor(a, quality);
    apply(res);
  };

  const handleQuality = (q: QualityPreset) => {
    onQualityChange(q);
    const currentAspect = aspectFromResolution(project.width, project.height);
    const res = resolutionFor(currentAspect, q);
    apply(res);
  };

  const sizeMB = estimateFileSizeMB(project.width, project.height, project.fps, quality, totalDurationSeconds);
  const time = estimateRenderSeconds(totalDurationSeconds, clipCount, quality, cpuOnly);

  return (
    <div className="video-settings-panel">
      <div className="panel-header">
        動画設定
        {saving && <span className="video-settings-saving">保存中...</span>}
      </div>

      <div className="video-settings-field">
        <span className="video-settings-label">アスペクト比</span>
        <div className="video-settings-radio-row">
          {ASPECTS.map((a) => (
            <label key={a.id} className={`video-settings-radio${aspect === a.id ? " video-settings-radio-selected" : ""}`}>
              <input
                type="radio"
                name="aspect"
                checked={aspect === a.id}
                onChange={() => handleAspect(a.id)}
              />
              {a.label}
            </label>
          ))}
        </div>
      </div>

      <div className="video-settings-field">
        <span className="video-settings-label">解像度</span>
        <select
          value={`${project.width}x${project.height}`}
          onChange={(e) => {
            const [w, h] = e.target.value.split("x").map(Number);
            apply({ width: w, height: h });
          }}
        >
          {[1, 0.75, 0.5].map((scale) => {
            const base = resolutionFor(aspect, quality);
            const w = Math.round((base.width * scale) / 2) * 2;
            const h = Math.round((base.height * scale) / 2) * 2;
            return (
              <option key={scale} value={`${w}x${h}`}>
                {w} × {h}
                {scale === 1 ? "" : scale === 0.75 ? " (軽量)" : " (最軽量)"}
              </option>
            );
          })}
        </select>
      </div>

      <div className="video-settings-field">
        <span className="video-settings-label">FPS</span>
        <select value={project.fps} onChange={(e) => apply({ fps: Number(e.target.value) })}>
          {FPS_OPTIONS.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
      </div>

      <div className="video-settings-field">
        <span className="video-settings-label">品質</span>
        <select value={quality} onChange={(e) => handleQuality(e.target.value as QualityPreset)}>
          {QUALITY_PRESETS.map((q) => (
            <option key={q.id} value={q.id}>
              {q.label}
            </option>
          ))}
        </select>
      </div>

      <div className="video-settings-estimates">
        <div>
          <span className="video-settings-label">推定ファイルサイズ</span>
          <span>約{formatBytes(sizeMB * 1024 * 1024)}</span>
        </div>
        <div>
          <span className="video-settings-label">推定生成時間</span>
          <span>{formatSecondsRangeAsMinutes(time.lowSeconds, time.highSeconds)}</span>
        </div>
        <div className="generation-engine-reason">
          目安です。内容(動きの量)やPC性能により前後します。
        </div>
      </div>

      {error && <div style={{ color: "var(--danger)", fontSize: 12 }}>{error}</div>}
    </div>
  );
}
