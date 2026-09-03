import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { ProductionRun, Project } from "../../types";
import { formatTime } from "../../utils/format";

/**
 * The completion screen (design doc section 44).
 *
 * States plainly what was produced and what was actually done to it -
 * quality check, automatic improvement, render - and then offers the four
 * things a user wants next. The download is a real MP4 written by FFmpeg,
 * not a placeholder.
 */
export default function StudioCompletion({
  run,
  project,
  durationSeconds,
  onOpenEditor,
  onPreview,
  onImproveMore,
  onShowMaterials,
}: {
  run: ProductionRun;
  project: Project;
  durationSeconds: number;
  onOpenEditor: () => void;
  onPreview: () => void;
  onImproveMore: () => void;
  onShowMaterials?: () => void;
}) {
  const [filename, setFilename] = useState<string | null>(null);

  const jobId = run.render_job_id;

  useEffect(() => {
    if (!jobId) return;
    // The backend names the file kairo_<project>_<date>.mp4 and sends it in
    // Content-Disposition; a HEAD lets us show that name before the user
    // commits to the download.
    fetch(api.downloadUrl(jobId), { method: "HEAD" })
      .then((res) => {
        const cd = res.headers.get("Content-Disposition") ?? "";
        const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
        if (match) setFilename(decodeURIComponent(match[1]));
      })
      .catch(() => {});
  }, [jobId]);

  const improvedCount = run.improvement?.applied.length ?? 0;
  // Stated on the completion screen rather than only in the 使用素材 tab:
  // "自分の写真がちゃんと使われたのか" is the first thing a user who
  // uploaded material wants to know, and making them go looking for it
  // invites the suspicion that it was quietly replaced.
  const plan = run.material_plan;
  const userCuts = plan ? plan.used_photo_count + plan.used_video_count : 0;

  return (
    <div className="studio-complete">
      <div className="studio-complete-title">🎉 動画が完成しました</div>

      <div className="studio-complete-meta">
        <span>{formatTime(durationSeconds)}</span>
        <span>
          {project.width}×{project.height}
        </span>
        <span>{project.fps}fps</span>
        {run.quality && <span>品質スコア {run.quality.score.toFixed(0)}点</span>}
      </div>

      <ul className="studio-complete-checks">
        <li>✓ 品質チェック完了{run.quality ? `（指摘 ${run.quality.issues.length}件）` : ""}</li>
        <li>
          {improvedCount > 0 ? "✓" : "–"} 自動改善
          {improvedCount > 0 ? `（${improvedCount}件を修正）` : "（修正の必要はありませんでした）"}
        </li>
        <li>✓ FFmpegでMP4を書き出し完了</li>
        {plan && (plan.user_photo_count > 0 || plan.user_video_count > 0) && (
          <li>
            ✓ ユーザー素材を{userCuts}カットで使用
            {plan.shortages.length > 0
              ? `（不足${plan.shortages.length}カットを補完）`
              : "（補完なし）"}
          </li>
        )}
      </ul>

      {filename && <div className="studio-complete-file">ファイル名: {filename}</div>}

      <div className="studio-complete-actions">
        <button className="primary" onClick={onPreview}>
          ▶ 動画を再生
        </button>
        {jobId && (
          <a className="button-link" href={api.downloadUrl(jobId)} download>
            ⬇ MP4を保存
          </a>
        )}
        {onShowMaterials && (
          <button onClick={onShowMaterials}>🖼 使用素材を見る</button>
        )}
        <button onClick={onOpenEditor}>✂ 手動で編集</button>
        <button onClick={onImproveMore}>💬 AIにもう一度改善させる</button>
      </div>
    </div>
  );
}
