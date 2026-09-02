import type { ImprovementReport, QualityReport } from "../../types";

/**
 * Quality check and automatic improvement (design doc sections 27/28).
 *
 * Shows three things separately, because they mean different things: what
 * was checked, what was found, and what Kairo actually changed as a result
 * - each change with the reason, which is what section 28 asks for. Issues
 * the improvement pass could not fix stay visible rather than disappearing
 * behind a score.
 */

const AXIS_LABEL: Record<string, string> = {
  structure: "構成",
  pacing: "テンポ",
  hook: "冒頭(Hook)",
  visual_quality: "映像",
  continuity: "つながり",
  subtitle: "字幕",
  audio: "音声",
  bgm: "BGM",
  sfx: "効果音",
  narration: "ナレーション",
  short_form_fit: "ショート適性",
  ending: "終わり方",
  loop: "ループ性",
};

const SEVERITY_LABEL: Record<string, string> = {
  major: "要改善",
  minor: "改善余地",
  info: "参考",
};

export default function QualityPanel({
  report,
  improvement,
  onRecheck,
  busy,
}: {
  report: QualityReport | null;
  improvement: ImprovementReport | null;
  onRecheck?: () => void;
  busy?: boolean;
}) {
  if (!report) {
    return (
      <div className="quality-panel quality-panel-empty">
        まだ品質チェックを実行していません。
        {onRecheck && (
          <button onClick={onRecheck} disabled={busy}>
            {busy ? "チェック中…" : "今すぐチェック"}
          </button>
        )}
      </div>
    );
  }

  const scoreClass =
    report.score >= 80 ? "good" : report.score >= 60 ? "ok" : "poor";

  return (
    <div className="quality-panel">
      <div className="quality-head">
        <div className={`quality-score quality-score-${scoreClass}`}>
          <span className="quality-score-value">{report.score.toFixed(0)}</span>
          <span className="quality-score-unit">点</span>
        </div>
        <div className="quality-head-text">
          <div className="quality-summary">{report.summary}</div>
          <div className="quality-method">
            チェック方法:{" "}
            {report.checked_by === "rules+ai"
              ? "ルール検査 + AIレビュー"
              : "ルール検査のみ(AIレビューは実行できませんでした)"}
          </div>
        </div>
        {onRecheck && (
          <button onClick={onRecheck} disabled={busy}>
            {busy ? "チェック中…" : "再チェック"}
          </button>
        )}
      </div>

      {report.strengths.length > 0 && (
        <div className="quality-strengths">
          {report.strengths.map((s, i) => (
            <div key={i}>◎ {s}</div>
          ))}
        </div>
      )}

      {improvement && improvement.applied.length > 0 && (
        <div className="quality-improvements">
          <div className="quality-section-title">
            自動改善で変更した内容
            {improvement.score_after > 0 && (
              <span className="quality-delta">
                {improvement.score_before.toFixed(0)} → {improvement.score_after.toFixed(0)}点
              </span>
            )}
          </div>
          {improvement.applied.map((change, i) => (
            <div key={i} className="quality-change">
              <div className="quality-change-head">
                <span className="quality-change-what">{change.what}</span>
                <span className="quality-change-values">
                  {change.before} <span className="quality-arrow">→</span> {change.after}
                </span>
              </div>
              {change.reason && (
                <div className="quality-change-reason">理由: {change.reason}</div>
              )}
            </div>
          ))}
        </div>
      )}

      {report.issues.length > 0 && (
        <div className="quality-issues">
          <div className="quality-section-title">チェック結果</div>
          {report.issues.map((issue, i) => (
            <div key={i} className={`quality-issue quality-issue-${issue.severity}`}>
              <div className="quality-issue-head">
                <span className="quality-issue-axis">
                  {AXIS_LABEL[issue.axis] ?? issue.axis}
                </span>
                <span className="quality-issue-sev">
                  {SEVERITY_LABEL[issue.severity] ?? issue.severity}
                </span>
                {issue.scene_index != null && (
                  <span className="quality-issue-scene">Scene {issue.scene_index + 1}</span>
                )}
                {issue.fix === null && (
                  <span className="quality-issue-manual">自動修正不可</span>
                )}
              </div>
              <div className="quality-issue-detail">{issue.detail}</div>
              {issue.suggestion && (
                <div className="quality-issue-suggestion">→ {issue.suggestion}</div>
              )}
            </div>
          ))}
        </div>
      )}

      {improvement && improvement.skipped.length > 0 && (
        <div className="quality-skipped">
          <div className="quality-section-title">自動では直せなかった指摘</div>
          {improvement.skipped.map((s, i) => (
            <div key={i}>・{s}</div>
          ))}
        </div>
      )}
    </div>
  );
}
