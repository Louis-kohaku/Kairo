import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { MediaAsset, SilenceCutPlan } from "../types";
import { formatTime } from "../utils/format";

interface Props {
  asset: MediaAsset;
  videoTrackId: string;
  onApplied: () => void;
  onClose: () => void;
}

export default function CutPlanPanel({ asset, videoTrackId, onApplied, onClose }: Props) {
  const [plan, setPlan] = useState<SilenceCutPlan | null>(null);
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    api
      .detectSilence(asset.id)
      .then(setPlan)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [asset.id]);

  const handleApply = async () => {
    if (!plan) return;
    setApplying(true);
    setError(null);
    try {
      await api.applyCutPlan(videoTrackId, asset.id, plan.keep_segments);
      onApplied();
      onClose();
    } catch (e) {
      setError(String(e));
    } finally {
      setApplying(false);
    }
  };

  const removedDuration = plan
    ? plan.silence_segments.reduce((sum, s) => sum + (s.end - s.start), 0)
    : 0;

  return (
    <div className="cutplan-overlay" onClick={onClose}>
      <div className="cutplan-panel" onClick={(e) => e.stopPropagation()}>
        <div className="panel-header">
          <span>無音カット: {asset.original_filename}</span>
          <button onClick={onClose}>閉じる</button>
        </div>

        {loading && <div style={{ padding: 12, color: "var(--text-dim)" }}>解析中...</div>}
        {error && <div style={{ padding: 12, color: "var(--danger)" }}>{error}</div>}

        {plan && !loading && (
          <>
            <div style={{ padding: "8px 12px", fontSize: 13 }}>
              無音区間 {plan.silence_segments.length} 箇所 (
              {formatTime(removedDuration)} 分) を削除し、
              {plan.keep_segments.length} 個のクリップとして追加します。
            </div>
            <div className="cutplan-segments">
              {plan.keep_segments.map((s, i) => (
                <div key={i} className="cutplan-segment">
                  残す: {formatTime(s.start)} - {formatTime(s.end)}
                </div>
              ))}
            </div>
            <button
              className="primary"
              onClick={handleApply}
              disabled={applying || plan.keep_segments.length === 0}
              style={{ margin: 12 }}
            >
              {applying ? "適用中..." : "映像トラックに適用"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
