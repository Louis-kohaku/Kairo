import type { AssetDecisions, TrendContext } from "../../types";

/**
 * What the agent knew and what it chose, with the reason for each choice.
 *
 * The design rule this panel exists for is that nothing may run invisibly:
 * for a finished video the user must be able to see which trend data it was
 * planned against, which font and BGM were picked, under what licence, and
 * why. So every row here carries its own justification, and a choice that
 * could *not* be made says so rather than being omitted - an empty row reads
 * as "nothing to report", which is the one thing it must never mean.
 */

const LICENSE_TONE: Record<string, string> = {
  usable: "ok",
  attribution_required: "warn",
  conditional: "warn",
  non_commercial: "bad",
  not_usable: "bad",
  unknown: "bad",
};

function LicenseBadge({
  license,
}: {
  license: { status: string; status_label: string; name: string; url: string };
}) {
  const tone = LICENSE_TONE[license.status] ?? "bad";
  return (
    <span className={`agent-license agent-license-${tone}`} title={license.name}>
      {license.status_label}
      {license.name ? `・${license.name}` : ""}
      {license.url && (
        <a href={license.url} target="_blank" rel="noreferrer noopener">
          条件
        </a>
      )}
    </span>
  );
}

export default function AgentDecisionsPanel({
  trend,
  assets,
}: {
  trend: TrendContext | null;
  assets: AssetDecisions | null;
}) {
  if (!trend && !assets) {
    return (
      <div className="agent-panel agent-panel-empty">
        まだ制作を実行していないため、AIの判断内容はありません。
      </div>
    );
  }

  const beat = assets?.beat_sync;

  return (
    <div className="agent-panel">
      {trend && (
        <section className="agent-section">
          <h3>使用したトレンド情報</h3>
          <div className="agent-row">
            <span className="agent-key">ジャンル判定</span>
            <span className="agent-value">{trend.genre_label || trend.genre}</span>
          </div>
          <div className="agent-row">
            <span className="agent-key">利用状況</span>
            <span className="agent-value">
              {trend.used ? "蓄積したトレンドデータを使用" : "未使用"}
              <span className="agent-reason">{trend.reason}</span>
            </span>
          </div>
          {trend.signals.length > 0 && (
            <ul className="agent-signals">
              {trend.signals.slice(0, 8).map((signal) => (
                <li key={signal.id}>
                  <span className="agent-signal-keyword">{signal.keyword}</span>
                  <span className="agent-signal-meta">
                    {signal.platform} / スコア{signal.effective_score.toFixed(0)}
                    {signal.growth_rate !== 0 &&
                      ` / 前回比 ${signal.growth_rate > 0 ? "+" : ""}${signal.growth_rate.toFixed(0)}`}
                  </span>
                  {signal.source_url && (
                    <a href={signal.source_url} target="_blank" rel="noreferrer noopener">
                      出典
                    </a>
                  )}
                </li>
              ))}
            </ul>
          )}
          {trend.profile && (
            <div className="agent-profile">
              <div className="agent-profile-head">
                ジャンル傾向
                <span
                  className={`agent-badge agent-badge-${
                    trend.profile_source === "llm" ? "ok" : "neutral"
                  }`}
                >
                  {trend.profile_source === "llm"
                    ? "収集したトレンドをAIが分析"
                    : "Kairo組み込みの定石（実測値ではありません）"}
                </span>
              </div>
              <div className="agent-profile-grid">
                <div>
                  <span>想定尺</span>
                  <strong>{trend.profile.duration_seconds ?? "—"}秒</strong>
                </div>
                <div>
                  <span>1カット</span>
                  <strong>{trend.profile.scene_seconds ?? "—"}秒</strong>
                </div>
                <div>
                  <span>カットテンポ</span>
                  <strong>{trend.profile.cut_tempo || "—"}</strong>
                </div>
                <div>
                  <span>字幕量</span>
                  <strong>{trend.profile.subtitle_density || "—"}</strong>
                </div>
                <div>
                  <span>BGM</span>
                  <strong>{trend.profile.bgm_mood || "—"}</strong>
                </div>
                <div>
                  <span>BPM目安</span>
                  <strong>
                    {trend.profile.bgm_bpm_range.length === 2
                      ? `${trend.profile.bgm_bpm_range[0]}–${trend.profile.bgm_bpm_range[1]}`
                      : "—"}
                  </strong>
                </div>
              </div>
              {trend.profile.hook_patterns.length > 0 && (
                <div className="agent-profile-list">
                  Hookの型: {trend.profile.hook_patterns.join(" / ")}
                </div>
              )}
              {trend.profile.notes && (
                <div className="agent-note">{trend.profile.notes}</div>
              )}
            </div>
          )}
        </section>
      )}

      {assets && (
        <section className="agent-section">
          <h3>AIが選んだ素材</h3>

          <div className="agent-choice">
            <div className="agent-choice-head">
              <span className="agent-choice-kind">フォント</span>
              {assets.font?.found ? (
                <>
                  <span className="agent-choice-name">
                    {assets.font.family || assets.font.name}
                  </span>
                  <LicenseBadge license={assets.font.license} />
                </>
              ) : (
                <span className="agent-choice-missing">選定できませんでした</span>
              )}
            </div>
            <div className="agent-choice-reason">
              {assets.font?.reason || assets.font?.unavailable_reason}
            </div>
            {assets.font?.found && (
              <div className="agent-choice-meta">
                取得元: {assets.font.source || "—"} / 候補{assets.font.considered}件
                {assets.font.rejected_for_license > 0 &&
                  ` / ライセンス条件で${assets.font.rejected_for_license}件を除外`}
              </div>
            )}
          </div>

          <div className="agent-choice">
            <div className="agent-choice-head">
              <span className="agent-choice-kind">BGM</span>
              {assets.music?.found ? (
                <>
                  <span className="agent-choice-name">{assets.music.name}</span>
                  <LicenseBadge license={assets.music.license} />
                </>
              ) : (
                <span className="agent-choice-missing">選定できませんでした</span>
              )}
            </div>
            <div className="agent-choice-reason">
              {assets.music?.reason || assets.music?.unavailable_reason}
            </div>
            {assets.music?.found && (
              <div className="agent-choice-meta">
                {assets.music.bpm ? `${assets.music.bpm.toFixed(0)} BPM / ` : ""}
                {assets.music.duration ? `${assets.music.duration.toFixed(0)}秒 / ` : ""}
                {assets.music.loudness_lufs != null
                  ? `${assets.music.loudness_lufs.toFixed(1)} LUFS / `
                  : ""}
                取得元: {assets.music.source || "—"}
              </div>
            )}
          </div>

          {beat && (
            <div className="agent-choice">
              <div className="agent-choice-head">
                <span className="agent-choice-kind">ビート同期</span>
                <span
                  className={`agent-badge agent-badge-${beat.applied ? "ok" : "neutral"}`}
                >
                  {beat.applied ? "適用" : "未適用"}
                </span>
              </div>
              <div className="agent-choice-reason">{beat.reason}</div>
              {beat.bpm != null && (
                <div className="agent-choice-meta">
                  {beat.bpm.toFixed(0)} BPM（
                  {beat.bpm_source === "declared" ? "生成時に指定した値" : "音源から実測"}）/
                  {beat.beats_per_cut}拍ごとにカット / {beat.adjusted_scenes}シーンを調整
                </div>
              )}
            </div>
          )}

          <div className="agent-choice">
            <div className="agent-choice-head">
              <span className="agent-choice-kind">効果音</span>
              <span className="agent-choice-name">{assets.sfx.length}箇所</span>
            </div>
            {assets.sfx.length > 0 ? (
              <ul className="agent-sfx-list">
                {assets.sfx.map((placement, i) => (
                  <li key={`${placement.at}-${i}`}>
                    <span className="agent-sfx-time">{placement.at.toFixed(1)}s</span>
                    <span className="agent-sfx-name">{placement.name}</span>
                    <span className="agent-sfx-reason">{placement.reason}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="agent-choice-reason">
                効果音は配置されていません。
              </div>
            )}
          </div>

          {assets.subtitle && (
            <div className="agent-choice">
              <div className="agent-choice-head">
                <span className="agent-choice-kind">字幕スタイル</span>
                <span className="agent-choice-name">
                  {assets.subtitle.font} / {assets.subtitle.size}px /{" "}
                  {assets.subtitle.position} / {assets.subtitle.style}
                </span>
              </div>
              <div className="agent-choice-reason">{assets.subtitle.reason}</div>
              <div className="agent-choice-meta">
                1行あたり最大{assets.subtitle.max_chars_per_line}文字
                {assets.subtitle.from_trend_profile && " / ジャンル傾向を反映"}
              </div>
            </div>
          )}

          {assets.notes.length > 0 && (
            <div className="agent-notes">
              {assets.notes.map((note, i) => (
                <div key={i}>※ {note}</div>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
