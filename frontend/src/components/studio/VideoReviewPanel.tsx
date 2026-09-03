import type { ProductionReport, VariantResult, VideoReview } from "../../types";

/**
 * The AI Video Reviewer's verdict on the rendered file, and the refinement
 * history that followed from it.
 *
 * Deliberately separate from `QualityPanel`, which reviews the *plan*. The
 * two answer different questions and can disagree - a sound scene design can
 * still render dark or too quiet - so showing them as one score would hide
 * exactly the case worth seeing.
 *
 * Every axis shows its basis. "実測" means the number came out of the MP4;
 * "構成から" means it came from the scene design because the file cannot
 * answer that question. A user who cannot tell those apart cannot tell which
 * numbers to trust.
 */

const BASIS_LABEL: Record<string, string> = {
  measured: "実測",
  planned: "構成から",
  ai: "AI判断",
};

const SEVERITY_LABEL: Record<string, string> = {
  major: "要改善",
  minor: "改善余地",
  info: "参考",
};

function scoreTone(score: number): string {
  if (score >= 80) return "good";
  if (score >= 60) return "ok";
  return "poor";
}

function VariantSection({
  variants,
  onGenerate,
  busy,
}: {
  variants: VariantResult | null;
  onGenerate?: () => void;
  busy?: boolean;
}) {
  return (
    <div className="review-variants">
      <div className="review-section-title">A/B/C バリエーション</div>
      <div className="settings-hint">
        同じ構成を「情感重視 / テンポ重視 / トレンド寄せ」の3通りで作り直し、
        レビュー点で比較します。1本ごとに書き出しが走るため、実行には時間がかかります。
      </div>
      {onGenerate && (
        <div className="settings-actions">
          <button onClick={onGenerate} disabled={busy}>
            {busy ? "作成中…" : "3パターンを作成して比較"}
          </button>
        </div>
      )}
      {variants?.error && <div className="review-error">{variants.error}</div>}
      {variants && variants.variants.length > 0 && (
        <div className="review-variant-list">
          {variants.variants.map((variant) => (
            <div
              key={variant.id}
              className={`review-variant ${variant.best ? "review-variant-best" : ""}`}
            >
              <div className="review-variant-head">
                <span className="review-variant-id">{variant.id}</span>
                <span className="review-variant-label">{variant.label}</span>
                <span
                  className={`review-iteration-score review-iteration-score-${scoreTone(
                    variant.score,
                  )}`}
                >
                  {variant.score.toFixed(0)}点
                </span>
                {variant.best && <span className="review-iteration-badge">採用</span>}
              </div>
              <div className="review-variant-note">{variant.strategy_note}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function VideoReviewPanel({
  review,
  report,
  iteration,
  bestScore,
  variants,
  onGenerateVariants,
  variantBusy,
}: {
  review: VideoReview | null;
  report: ProductionReport | null;
  iteration: number;
  bestScore: number | null;
  variants?: VariantResult | null;
  onGenerateVariants?: () => void;
  variantBusy?: boolean;
}) {
  if (!review) {
    return (
      <div className="review-panel review-panel-empty">
        完成動画のレビューはまだ実行されていません。書き出しが終わると自動で採点されます。
      </div>
    );
  }

  if (!review.performed) {
    return (
      <div className="review-panel review-panel-empty">
        <div>完成動画を解析できませんでした。</div>
        {review.error && <div className="review-error">理由: {review.error}</div>}
      </div>
    );
  }

  const measured = review.measured as Record<string, unknown>;
  const frames = (measured.frames ?? {}) as Record<string, unknown>;
  const iterations = report?.iterations ?? [];

  return (
    <div className="review-panel">
      <div className="review-head">
        <div className={`review-score review-score-${scoreTone(review.overall_score)}`}>
          <span className="review-score-value">{review.overall_score.toFixed(0)}</span>
          <span className="review-score-unit">点</span>
        </div>
        <div className="review-head-text">
          <div className="review-summary">{review.summary}</div>
          <div className="review-method">
            採点方法:{" "}
            {review.reviewed_by === "rules+ai"
              ? "実測 + ルール検査 + AIレビュー"
              : "実測 + ルール検査のみ（AIレビューは実行できませんでした）"}
            {iteration > 0 && ` / 自動改善 ${iteration}回`}
            {bestScore != null && ` / 最良スコア ${bestScore.toFixed(0)}点`}
          </div>
        </div>
      </div>

      <div className="review-axes">
        {review.axes.map((axis) => (
          <div key={axis.axis} className="review-axis">
            <div className="review-axis-head">
              <span className="review-axis-label">{axis.label}</span>
              <span className={`review-axis-basis review-axis-basis-${axis.basis}`}>
                {BASIS_LABEL[axis.basis] ?? axis.basis}
              </span>
              <span className={`review-axis-score review-axis-score-${scoreTone(axis.score)}`}>
                {axis.score.toFixed(0)}
              </span>
            </div>
            <div className="review-axis-bar">
              <div
                className={`review-axis-fill review-axis-fill-${scoreTone(axis.score)}`}
                style={{ width: `${Math.max(0, Math.min(100, axis.score))}%` }}
              />
            </div>
            <div className="review-axis-detail">{axis.detail}</div>
          </div>
        ))}
      </div>

      <div className="review-measured">
        <div className="review-section-title">完成ファイルの実測値</div>
        <div className="review-measured-grid">
          <div>
            <span>尺</span>
            <strong>
              {typeof measured.duration === "number"
                ? `${(measured.duration as number).toFixed(1)}秒`
                : "—"}
            </strong>
          </div>
          <div>
            <span>解像度</span>
            <strong>
              {measured.width && measured.height
                ? `${measured.width}x${measured.height}`
                : "—"}
            </strong>
          </div>
          <div>
            <span>fps</span>
            <strong>{(measured.fps as number | undefined)?.toString() ?? "—"}</strong>
          </div>
          <div>
            <span>音量</span>
            <strong>
              {typeof measured.loudness_lufs === "number"
                ? `${(measured.loudness_lufs as number).toFixed(1)} LUFS`
                : "測定不可"}
            </strong>
          </div>
          <div>
            <span>平均輝度</span>
            <strong>
              {typeof frames.mean_luma === "number"
                ? `${(frames.mean_luma as number).toFixed(0)} / 255`
                : "—"}
            </strong>
          </div>
          <div>
            <span>フレーム間変化</span>
            <strong>
              {typeof frames.frame_variation === "number"
                ? (frames.frame_variation as number).toFixed(1)
                : "—"}
            </strong>
          </div>
        </div>
      </div>

      {review.strengths.length > 0 && (
        <div className="review-strengths">
          {review.strengths.map((s, i) => (
            <div key={i}>◎ {s}</div>
          ))}
        </div>
      )}

      {review.findings.length > 0 && (
        <div className="review-findings">
          <div className="review-section-title">
            指摘（問題 → 原因 → 改善案）
          </div>
          {review.findings.map((finding, i) => (
            <div key={i} className={`review-finding review-finding-${finding.severity}`}>
              <div className="review-finding-head">
                <span className="review-finding-axis">{finding.axis}</span>
                <span className="review-finding-sev">
                  {SEVERITY_LABEL[finding.severity] ?? finding.severity}
                </span>
                {finding.scene_index != null && (
                  <span className="review-finding-scene">
                    Scene {finding.scene_index + 1}
                  </span>
                )}
                <span
                  className={`review-finding-fix ${
                    finding.fix ? "review-finding-fix-auto" : "review-finding-fix-manual"
                  }`}
                >
                  {finding.fix ? "自動修正可" : "自動修正不可"}
                </span>
              </div>
              <div className="review-finding-problem">{finding.problem}</div>
              {finding.cause && (
                <div className="review-finding-cause">原因: {finding.cause}</div>
              )}
              {finding.suggestion && (
                <div className="review-finding-suggestion">→ {finding.suggestion}</div>
              )}
            </div>
          ))}
        </div>
      )}

      {iterations.length > 1 && (
        <div className="review-iterations">
          <div className="review-section-title">自動改善の履歴</div>
          {iterations.map((record) => (
            <div
              key={record.iteration}
              className={`review-iteration ${
                record.adopted ? "review-iteration-adopted" : ""
              }`}
            >
              <div className="review-iteration-head">
                <span>{record.iteration === 0 ? "初回書き出し" : `${record.iteration}回目`}</span>
                <span className={`review-iteration-score review-iteration-score-${scoreTone(record.score)}`}>
                  {record.score.toFixed(0)}点
                </span>
                {record.adopted && <span className="review-iteration-badge">採用</span>}
              </div>
              {record.changes.length > 0 && (
                <ul className="review-iteration-changes">
                  {record.changes.map((change, i) => (
                    <li key={i}>{change}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}

      <VariantSection
        variants={variants ?? null}
        onGenerate={onGenerateVariants}
        busy={variantBusy}
      />

      {report && (
        <div className="review-report">
          <div className="review-section-title">制作レポート</div>
          <div className="review-report-grid">
            <div>
              <span>ジャンル</span>
              <strong>{report.genre_label || "—"}</strong>
            </div>
            <div>
              <span>LLM</span>
              <strong>{report.llm_model || "—"}</strong>
            </div>
            <div>
              <span>Endpoint</span>
              <strong>{report.llm_endpoint}</strong>
            </div>
            <div>
              <span>書き出し</span>
              <strong>{report.rendering_engine}</strong>
            </div>
            <div>
              <span>文字起こし</span>
              <strong>{report.transcription_engine}</strong>
            </div>
            <div>
              <span>音声合成</span>
              <strong>{report.tts_engine}</strong>
            </div>
            <div>
              <span>フォント</span>
              <strong>
                {report.font || "—"}
                {report.font_license && `（${report.font_license}）`}
              </strong>
            </div>
            <div>
              <span>BGM</span>
              <strong>
                {report.music || "—"}
                {report.music_license && `（${report.music_license}）`}
              </strong>
            </div>
            <div>
              <span>最終スコア</span>
              <strong>{report.final_score.toFixed(0)}点</strong>
            </div>
          </div>
          {report.attribution.length > 0 && (
            <div className="review-attribution">
              <div className="review-section-title">クレジット表記が必要な素材</div>
              {report.attribution.map((line, i) => (
                <div key={i}>{line}</div>
              ))}
            </div>
          )}
          {report.assets_used_path && (
            <div className="review-report-path">
              使用素材の台帳: <code>{report.assets_used_path}</code>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
