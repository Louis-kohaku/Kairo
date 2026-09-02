import type { ProductionStrategy, ResearchResult } from "../../types";

/**
 * What the research found, and what Kairo decided to do about it
 * (design doc sections 16-19).
 *
 * Trends and differentiation are shown as two separate lists, deliberately
 * (section 18): the first is what this format expects, the second is what
 * this video will do that the sources did not. Merging them is how
 * "research-informed" quietly becomes "copied from the top result".
 *
 * Sources are listed with whether the page was actually fetched, so the
 * analysis is attributable rather than an unsourced summary.
 */
export default function ResearchPanel({
  research,
  strategy,
}: {
  research: ResearchResult | null;
  strategy: ProductionStrategy | null;
}) {
  if (!research && !strategy) {
    return (
      <div className="research-panel research-empty">
        まだ調査・戦略が作られていません。制作を開始すると表示されます。
      </div>
    );
  }

  const trends = research?.trends;

  return (
    <div className="research-panel">
      {strategy && (
        <section className="research-section">
          <h3>制作戦略</h3>
          <dl className="strategy-grid">
            <dt>タイトル</dt>
            <dd>{strategy.title}</dd>
            <dt>狙い</dt>
            <dd>{strategy.concept}</dd>
            <dt>Hook</dt>
            <dd className="strategy-hook">{strategy.hook}</dd>
            <dt>テンポ</dt>
            <dd>
              {strategy.pacing}
              <span className="strategy-note">
                （1シーン {strategy.scene_seconds_min.toFixed(1)}〜
                {strategy.scene_seconds_max.toFixed(1)}秒）
              </span>
            </dd>
            <dt>字幕方針</dt>
            <dd>{strategy.subtitle_policy}</dd>
            <dt>音</dt>
            <dd>
              {strategy.audio_policy}
              <span className="strategy-note">（BGM: {strategy.bgm_mood}）</span>
            </dd>
            <dt>終わり方</dt>
            <dd>{strategy.ending}</dd>
            <dt>差別化</dt>
            <dd className="strategy-diff">{strategy.differentiation}</dd>
            {strategy.emotional_arc.length > 0 && (
              <>
                <dt>感情の流れ</dt>
                <dd>{strategy.emotional_arc.join(" → ")}</dd>
              </>
            )}
          </dl>
        </section>
      )}

      {research && (
        <section className="research-section">
          <h3>Webリサーチ</h3>
          {!research.performed ? (
            <div className="research-skipped">
              このリサーチは実行できませんでした（{research.skipped_reason}）。
              一般的なショート動画の定石を使って制作しています。
            </div>
          ) : (
            <>
              <div className="research-queries">
                検索した内容: {research.queries.join(" / ")}
              </div>
              <div className="research-sources">
                {research.sources.map((s, i) => (
                  <div key={i} className="research-source">
                    <span className={s.fetched ? "ok" : "dim"}>
                      {s.fetched ? "✓" : "–"}
                    </span>
                    <a href={s.url} target="_blank" rel="noreferrer noopener">
                      {s.title || s.url}
                    </a>
                  </div>
                ))}
              </div>
            </>
          )}
          {trends?.notes && <div className="research-notes">{trends.notes}</div>}
        </section>
      )}

      {trends && (
        <div className="trend-columns">
          <section className="research-section trend-column">
            <h3>共通トレンド</h3>
            <p className="trend-caption">このテーマの動画によくある作り方</p>
            <ul>
              {trends.common_patterns.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
            {trends.hook_patterns.length > 0 && (
              <>
                <h4>冒頭の傾向</h4>
                <ul>
                  {trends.hook_patterns.map((p, i) => (
                    <li key={i}>{p}</li>
                  ))}
                </ul>
              </>
            )}
          </section>

          <section className="research-section trend-column trend-column-diff">
            <h3>差別化機会</h3>
            <p className="trend-caption">この動画で他と差をつけられるところ</p>
            <ul>
              {trends.differentiation.map((d, i) => (
                <li key={i}>{d}</li>
              ))}
            </ul>
            {trends.ending_patterns.length > 0 && (
              <>
                <h4>終わり方の傾向</h4>
                <ul>
                  {trends.ending_patterns.map((p, i) => (
                    <li key={i}>{p}</li>
                  ))}
                </ul>
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
