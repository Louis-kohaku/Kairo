import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { AppSettingsPatch, GenreBreakdown, TrendOverview } from "../../types";

/**
 * Trend Intelligence, as the user sees it: what has been collected, from
 * where, how often, and what it means per genre.
 *
 * The source list shows connected *and* deliberately-unconnected platforms
 * with the reason. A UI that quietly omitted TikTok would read as an
 * oversight; naming it and saying "no public trends API, and scraping would
 * breach the terms" is the honest version of the same fact.
 */

const REGIONS = [
  { id: "JP", label: "日本 (JP)" },
  { id: "US", label: "アメリカ (US)" },
  { id: "GB", label: "イギリス (GB)" },
];

const INTERVALS = [
  { value: 60, label: "1時間" },
  { value: 180, label: "3時間（推奨）" },
  { value: 360, label: "6時間" },
  { value: 1440, label: "1日" },
];

function formatTime(value: string | null): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString("ja-JP");
  } catch {
    return value;
  }
}

export default function TrendSettingsTab({
  settings,
  applyPatch,
}: {
  settings: {
    enabled: boolean;
    region: string;
    interval_minutes: number;
    use_in_production: boolean;
    sources: string[];
  };
  applyPatch: (patch: AppSettingsPatch) => Promise<void>;
}) {
  const [overview, setOverview] = useState<TrendOverview | null>(null);
  const [genres, setGenres] = useState<GenreBreakdown[]>([]);
  const [unavailable, setUnavailable] = useState<
    { id: string; label: string; reason: string; docs: string }[]
  >([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [ov, gs, srcs] = await Promise.all([
        api.getTrendOverview(),
        api.getTrendGenres(),
        api.getTrendSources(),
      ]);
      setOverview(ov);
      setGenres(gs.filter((g) => g.count > 0));
      setUnavailable(srcs.unavailable);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const collectNow = async () => {
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      const result = await api.collectTrends();
      const ok = result.sources.filter((s) => s.ok);
      const failed = result.sources.filter((s) => !s.ok);
      setMessage(
        `取得完了（${result.status}）: ${result.collected}件を収集、` +
          `新規${result.inserted}件 / 更新${result.updated}件。` +
          (ok.length ? ` 成功: ${ok.map((s) => s.id).join(", ")}。` : "") +
          (failed.length
            ? ` 未取得: ${failed.map((s) => `${s.id}(${s.error})`).join(", ")}`
            : ""),
      );
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const refreshProfiles = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const result = await api.refreshTrendProfiles(false);
      setMessage(
        result.labels.length
          ? `ジャンル傾向を再分析しました: ${result.labels.join(", ")}`
          : "十分なトレンドデータが集まっているジャンルがまだありません（組み込みの定石を使用します）。",
      );
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="settings-section">
      <h2>トレンド収集</h2>
      <p className="settings-lead">
        Kairoは制作のたびに検索するのではなく、バックグラウンドでトレンドを収集して蓄積します。
        企画・構成・BGM・字幕の判断は、ここに溜まったデータを参照します。
      </p>

      {error && <div className="settings-error">{error}</div>}
      {message && <div className="settings-note">{message}</div>}

      <label className="settings-toggle">
        <input
          type="checkbox"
          checked={settings.enabled}
          onChange={(e) => applyPatch({ trends: { enabled: e.target.checked } })}
        />
        バックグラウンドでトレンドを収集する
      </label>

      <label className="settings-toggle">
        <input
          type="checkbox"
          checked={settings.use_in_production}
          onChange={(e) => applyPatch({ trends: { use_in_production: e.target.checked } })}
        />
        制作時にトレンドデータを使用する
        <span className="settings-hint">
          オフにすると、収集は続けたままジャンルの定石だけで制作します。
        </span>
      </label>

      <div className="settings-field">
        <span className="settings-field-label">対象地域</span>
        <select
          value={settings.region}
          onChange={(e) => applyPatch({ trends: { region: e.target.value } })}
        >
          {REGIONS.map((r) => (
            <option key={r.id} value={r.id}>
              {r.label}
            </option>
          ))}
        </select>
      </div>

      <div className="settings-field">
        <span className="settings-field-label">更新頻度</span>
        <select
          value={settings.interval_minutes}
          onChange={(e) =>
            applyPatch({ trends: { interval_minutes: Number(e.target.value) } })
          }
        >
          {INTERVALS.map((i) => (
            <option key={i.value} value={i.value}>
              {i.label}
            </option>
          ))}
        </select>
        <span className="settings-hint">
          取得元は他社のサーバーです。30分未満には設定できません。
        </span>
      </div>

      <div className="settings-actions">
        <button onClick={collectNow} disabled={busy}>
          {busy ? "処理中…" : "今すぐ更新"}
        </button>
        <button onClick={refreshProfiles} disabled={busy}>
          ジャンル傾向を再分析
        </button>
      </div>

      {overview && (
        <>
          <div className="trend-stats">
            <div>
              <span>蓄積件数</span>
              <strong>{overview.total_signals}</strong>
            </div>
            <div>
              <span>有効（期限内）</span>
              <strong>{overview.fresh_signals}</strong>
            </div>
            <div>
              <span>最終取得</span>
              <strong>{formatTime(overview.last_run_at)}</strong>
            </div>
            <div>
              <span>次回取得</span>
              <strong>{formatTime(overview.next_run_at)}</strong>
            </div>
          </div>

          <h3>取得元</h3>
          <table className="settings-table">
            <thead>
              <tr>
                <th>サービス</th>
                <th>種別</th>
                <th>認証</th>
                <th>状態</th>
              </tr>
            </thead>
            <tbody>
              {overview.sources.map((source) => (
                <tr key={source.id}>
                  <td>
                    <div className="settings-table-name">{source.label}</div>
                    <div className="settings-table-sub">{source.note}</div>
                    {source.terms_url && (
                      <a href={source.terms_url} target="_blank" rel="noreferrer noopener">
                        利用規約
                      </a>
                    )}
                  </td>
                  <td>{source.kind === "public_feed" ? "公開フィード" : "公式API"}</td>
                  <td>
                    {source.requires_key ? `APIキー (${source.key_env})` : "不要"}
                  </td>
                  <td>
                    {!source.enabled ? (
                      <span className="settings-state settings-state-off">無効</span>
                    ) : !source.configured ? (
                      <span className="settings-state settings-state-warn">未設定</span>
                    ) : source.last_ok ? (
                      <span className="settings-state settings-state-ok">
                        接続済み（{source.last_count}件）
                      </span>
                    ) : source.last_error ? (
                      <span className="settings-state settings-state-bad">
                        {source.last_error}
                      </span>
                    ) : (
                      <span className="settings-state">未取得</span>
                    )}
                  </td>
                </tr>
              ))}
              {unavailable.map((platform) => (
                <tr key={platform.id} className="settings-table-muted">
                  <td>
                    <div className="settings-table-name">{platform.label}</div>
                    <div className="settings-table-sub">{platform.reason}</div>
                    {platform.docs && (
                      <a href={platform.docs} target="_blank" rel="noreferrer noopener">
                        公式ドキュメント
                      </a>
                    )}
                  </td>
                  <td>公式API</td>
                  <td>審査申請が必要</td>
                  <td>
                    <span className="settings-state settings-state-off">未接続</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {overview.top.length > 0 && (
            <>
              <h3>現在のトレンド（上位）</h3>
              <ul className="trend-list">
                {overview.top.slice(0, 12).map((signal) => (
                  <li key={signal.id}>
                    <span className="trend-keyword">{signal.keyword}</span>
                    <span className="trend-meta">
                      {signal.category_label} / {signal.platform} /{" "}
                      {signal.effective_score.toFixed(0)}
                    </span>
                    {signal.source_url && (
                      <a href={signal.source_url} target="_blank" rel="noreferrer noopener">
                        出典
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}

          {genres.length > 0 && (
            <>
              <h3>ジャンル別の傾向</h3>
              <table className="settings-table">
                <thead>
                  <tr>
                    <th>ジャンル</th>
                    <th>件数</th>
                    <th>想定尺</th>
                    <th>1カット</th>
                    <th>BGM</th>
                    <th>根拠</th>
                  </tr>
                </thead>
                <tbody>
                  {genres.map((genre) => (
                    <tr key={genre.genre}>
                      <td>{genre.label}</td>
                      <td>{genre.count}</td>
                      <td>{genre.profile.duration_seconds ?? "—"}秒</td>
                      <td>{genre.profile.scene_seconds ?? "—"}秒</td>
                      <td>{genre.profile.bgm_mood || "—"}</td>
                      <td>
                        {genre.derived_from === "llm" ? (
                          <span className="settings-state settings-state-ok">
                            トレンド{genre.sample_size}件から分析
                          </span>
                        ) : (
                          <span className="settings-state">
                            組み込みの定石（実測値ではありません）
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}
    </div>
  );
}
