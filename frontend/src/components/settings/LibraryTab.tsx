import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type {
  AppSettingsPatch,
  FontCatalogEntry,
  LibraryAsset,
  LibraryOverview,
} from "../../types";

/**
 * The Creative Asset Library and its licence manager.
 *
 * The licence column is the reason this screen exists. Kairo will not use an
 * asset in an automatic production unless its terms are known, so the user
 * needs to see which of their files are blocked and be able to declare a
 * licence for the ones they have rights to. "自動制作で使用可" is therefore
 * shown per asset, not implied.
 */

const KIND_LABEL: Record<string, string> = {
  font: "フォント",
  music: "BGM",
  sfx: "効果音",
};

const STATUS_TONE: Record<string, string> = {
  usable: "ok",
  attribution_required: "warn",
  conditional: "warn",
  non_commercial: "bad",
  not_usable: "bad",
  unknown: "bad",
};

export default function LibraryTab({
  settings,
  applyPatch,
}: {
  settings: { auto_download_fonts: boolean; prefer_commercial_safe: boolean };
  applyPatch: (patch: AppSettingsPatch) => Promise<void>;
}) {
  const [overview, setOverview] = useState<LibraryOverview | null>(null);
  const [kind, setKind] = useState<"font" | "music" | "sfx">("music");
  const [assets, setAssets] = useState<LibraryAsset[]>([]);
  const [total, setTotal] = useState(0);
  const [catalog, setCatalog] = useState<FontCatalogEntry[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadAssets = useCallback(async (target: "font" | "music" | "sfx") => {
    const result = await api.listLibraryAssets({
      kind: target,
      japaneseOnly: target === "font",
      limit: 60,
    });
    setAssets(result.assets);
    setTotal(result.total);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [ov, cat] = await Promise.all([api.getLibrary(), api.getFontCatalog()]);
      setOverview(ov);
      setCatalog(cat.catalog);
      await loadAssets(kind);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, [kind, loadAssets]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    setMessage(null);
    setError(null);
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  const summary = overview?.summary ?? {};

  return (
    <div className="settings-section">
      <h2>素材ライブラリ</h2>
      <p className="settings-lead">
        Kairoが自動制作で使えるフォント・BGM・効果音の一覧です。ライセンスが確認できない素材は、
        自動制作では使用されません。
      </p>

      {error && <div className="settings-error">{error}</div>}
      {message && <div className="settings-note">{message}</div>}

      <div className="library-summary">
        {(["font", "music", "sfx"] as const).map((k) => (
          <div key={k} className="library-summary-card">
            <span>{KIND_LABEL[k]}</span>
            <strong>{summary[k]?.available ?? 0}</strong>
            <span className="library-summary-sub">
              うち自動制作で使用可 {summary[k]?.auto_usable ?? 0}
            </span>
          </div>
        ))}
      </div>

      {overview && (
        <div className="settings-paths">
          <div>フォント: <code>{overview.roots.fonts}</code></div>
          <div>BGM: <code>{overview.roots.music}</code></div>
          <div>効果音: <code>{overview.roots.sfx}</code></div>
          <div className="settings-hint">
            これらのフォルダにファイルを置いて「再スキャン」すると取り込まれます。
            取り込んだ直後のライセンスは「不明」で、自動制作には使われません。
          </div>
        </div>
      )}

      <label className="settings-toggle">
        <input
          type="checkbox"
          checked={settings.prefer_commercial_safe}
          onChange={(e) =>
            applyPatch({ library: { prefer_commercial_safe: e.target.checked } })
          }
        />
        商用利用可能と確認できた素材のみ自動選択する
      </label>

      <div className="settings-actions">
        <button onClick={() => run("scan", () => api.scanLibrary(true, false))} disabled={!!busy}>
          {busy === "scan" ? "スキャン中…" : "再スキャン"}
        </button>
        <button
          onClick={() =>
            run("bootstrap", async () => {
              await api.bootstrapLibrary(false);
              setMessage("Kairo内蔵のBGM・効果音を生成し、ライブラリに登録しました。");
            })
          }
          disabled={!!busy}
        >
          {busy === "bootstrap" ? "生成中…" : "内蔵BGM/効果音を生成"}
        </button>
      </div>

      <h3>フォントの追加取得</h3>
      <p className="settings-hint">
        Google Fonts公式リポジトリから、ライセンスファイルと一緒にダウンロードします。
        ライセンスファイルが取得できないフォントはダウンロードしません。
      </p>
      <div className="font-catalog">
        {catalog.map((entry) => (
          <div key={entry.id} className="font-catalog-item">
            <div className="font-catalog-head">
              <span className="font-catalog-family">{entry.family}</span>
              <span className="settings-state settings-state-ok">{entry.license_id}</span>
              {entry.installed && (
                <span className="settings-state settings-state-ok">取得済み</span>
              )}
            </div>
            <div className="font-catalog-note">{entry.note}</div>
            {entry.variable_only && (
              <div className="font-catalog-warn">
                バリアブルフォントのみ配布。字幕描画では既定のウェイトで表示されます。
              </div>
            )}
            <div className="font-catalog-actions">
              <a href={entry.source_url} target="_blank" rel="noreferrer noopener">
                配布元
              </a>
              <button
                onClick={() =>
                  run(`font-${entry.id}`, async () => {
                    const result = await api.downloadFont(entry.id);
                    setMessage(
                      `${result.downloaded.family} を取得しました（${result.downloaded.license_id} / ` +
                        `${result.downloaded.files.length}ファイル）。`,
                    );
                  })
                }
                disabled={!!busy}
              >
                {busy === `font-${entry.id}` ? "取得中…" : "ダウンロード"}
              </button>
            </div>
          </div>
        ))}
      </div>

      <h3>登録済みの素材</h3>
      <div className="settings-tabs settings-tabs-inline">
        {(["music", "sfx", "font"] as const).map((k) => (
          <button
            key={k}
            className={kind === k ? "settings-tab-active" : ""}
            onClick={() => {
              setKind(k);
              void loadAssets(k);
            }}
          >
            {KIND_LABEL[k]}
          </button>
        ))}
      </div>
      <div className="settings-hint">
        {kind === "font"
          ? `日本語対応フォントのみ表示しています（全${total}件中）。`
          : `全${total}件。`}
      </div>

      <table className="settings-table">
        <thead>
          <tr>
            <th>名前</th>
            <th>{kind === "font" ? "可読性 / 特徴" : "実測値"}</th>
            <th>取得元</th>
            <th>ライセンス</th>
          </tr>
        </thead>
        <tbody>
          {assets.map((asset) => (
            <tr key={asset.id}>
              <td>
                <div className="settings-table-name">{asset.family || asset.name}</div>
                <div className="settings-table-sub">{asset.category}</div>
              </td>
              <td>
                {asset.kind === "font" ? (
                  <>
                    <div>{asset.readability ?? "—"} / 100（推定）</div>
                    <div className="settings-table-sub">
                      {asset.styles.slice(0, 4).join(", ")}
                    </div>
                  </>
                ) : (
                  <>
                    <div>
                      {asset.bpm ? `${asset.bpm.toFixed(0)} BPM` : "テンポ検出なし"}
                      {asset.duration ? ` / ${asset.duration.toFixed(1)}秒` : ""}
                    </div>
                    <div className="settings-table-sub">
                      {asset.loudness_lufs != null
                        ? `${asset.loudness_lufs.toFixed(1)} LUFS`
                        : "音量未測定"}
                    </div>
                  </>
                )}
              </td>
              <td className="settings-table-sub">{asset.source || "—"}</td>
              <td>
                <span
                  className={`settings-state settings-state-${
                    STATUS_TONE[asset.license.status] ?? "bad"
                  }`}
                >
                  {asset.license.status_label}
                </span>
                <div className="settings-table-sub">{asset.license.name}</div>
                {!asset.auto_usable && overview && (
                  <select
                    defaultValue=""
                    onChange={(e) => {
                      const value = e.target.value;
                      if (!value) return;
                      void run(`license-${asset.id}`, () =>
                        api.setAssetLicense(asset.id, value),
                      );
                    }}
                  >
                    <option value="">ライセンスを設定…</option>
                    {overview.licenses
                      .filter((l) => l.id !== "unknown")
                      .map((l) => (
                        <option key={l.id} value={l.id}>
                          {l.name}
                        </option>
                      ))}
                  </select>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
