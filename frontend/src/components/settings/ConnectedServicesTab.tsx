import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { AppSettingsPatch, ConnectedServices } from "../../types";

/**
 * "何に繋がっているのか" - every service Kairo uses, checked live.
 *
 * The backend re-checks each row on every request (runs the binary, calls
 * the endpoint, reads the environment) rather than listing what the code
 * could in principle reach, so a row saying 接続済み means a connection was
 * just made. Rows that are deliberately not connected are shown with the
 * reason, and every failing row carries what to do about it - design rule 29
 * applies to this screen as much as to a failed render.
 */

const STATE_LABEL: Record<string, string> = {
  connected: "接続済み",
  not_connected: "未接続",
  not_configured: "未設定",
  unavailable: "利用不可",
  disabled: "無効",
};

const STATE_TONE: Record<string, string> = {
  connected: "ok",
  not_connected: "bad",
  not_configured: "warn",
  unavailable: "off",
  disabled: "off",
};

export default function ConnectedServicesTab({
  refinement,
  applyPatch,
}: {
  refinement: { enabled: boolean; max_iterations: number; target_score: number };
  applyPatch: (patch: AppSettingsPatch) => Promise<void>;
}) {
  const [data, setData] = useState<ConnectedServices | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setBusy(true);
    try {
      setData(await api.getConnectedServices());
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <div className="settings-section">
      <h2>接続中のサービス</h2>
      <p className="settings-lead">
        {data?.note ??
          "この一覧は表示のたびに実際に接続・実行して確認しています。"}
      </p>

      {error && <div className="settings-error">{error}</div>}

      <div className="settings-actions">
        <button onClick={refresh} disabled={busy}>
          {busy ? "確認中…" : "再確認"}
        </button>
        {data && (
          <span className="settings-hint">
            {data.counts.connected} / {data.counts.total} が接続済み
          </span>
        )}
      </div>

      {data &&
        Object.entries(data.by_category).map(([category, services]) => (
          <div key={category} className="services-group">
            <h3>{category}</h3>
            <table className="settings-table">
              <thead>
                <tr>
                  <th>サービス</th>
                  <th>用途 / 接続方法</th>
                  <th>モデル・Endpoint</th>
                  <th>認証 / 費用</th>
                  <th>状態</th>
                </tr>
              </thead>
              <tbody>
                {services.map((service) => (
                  <tr key={service.id}>
                    <td>
                      <div className="settings-table-name">{service.label}</div>
                      {service.files.length > 0 && (
                        <div className="settings-table-sub">
                          <code>{service.files[0]}</code>
                        </div>
                      )}
                    </td>
                    <td>
                      <div>{service.purpose}</div>
                      <div className="settings-table-sub">
                        {
                          {
                            local: "ローカル実行",
                            local_http: "ローカルHTTP API",
                            official_api: "公式API",
                            public_feed: "公開フィード",
                          }[service.connection] ?? service.connection
                        }
                      </div>
                    </td>
                    <td className="settings-table-sub">
                      {service.model && <div>{service.model}</div>}
                      {service.endpoint && <code>{service.endpoint}</code>}
                    </td>
                    <td className="settings-table-sub">
                      <div>{service.auth}</div>
                      <div>{service.cost}</div>
                    </td>
                    <td>
                      <span
                        className={`settings-state settings-state-${
                          STATE_TONE[service.state] ?? "bad"
                        }`}
                      >
                        {STATE_LABEL[service.state] ?? service.state}
                      </span>
                      <div className="settings-table-sub">{service.detail}</div>
                      {service.remedy && (
                        <div className="settings-remedy">→ {service.remedy}</div>
                      )}
                      {service.terms_url && (
                        <a href={service.terms_url} target="_blank" rel="noreferrer noopener">
                          規約 / ドキュメント
                        </a>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}

      <h2>自動改善ループ</h2>
      <p className="settings-lead">
        書き出したMP4をAIが採点し、指摘を反映して作り直します。1回ごとに再レンダリングが走るため、
        回数の上限は必ず適用されます。最終的には最もスコアの高い版が採用されます。
      </p>

      <label className="settings-toggle">
        <input
          type="checkbox"
          checked={refinement.enabled}
          onChange={(e) => applyPatch({ refinement: { enabled: e.target.checked } })}
        />
        レビュー結果をもとに自動改善する
      </label>

      <div className="settings-field">
        <span className="settings-field-label">最大反復回数</span>
        <select
          value={refinement.max_iterations}
          onChange={(e) =>
            applyPatch({ refinement: { max_iterations: Number(e.target.value) } })
          }
        >
          {[1, 2, 3, 4, 5].map((n) => (
            <option key={n} value={n}>
              {n}回{n === 2 ? "（推奨）" : ""}
            </option>
          ))}
        </select>
        <span className="settings-hint">
          1回 = チェックのみ。2回以上で「改善して再書き出し」が動きます。
        </span>
      </div>

      <div className="settings-field">
        <span className="settings-field-label">目標スコア</span>
        <input
          type="number"
          min={0}
          max={100}
          value={refinement.target_score}
          onChange={(e) =>
            applyPatch({ refinement: { target_score: Number(e.target.value) } })
          }
        />
        <span className="settings-hint">
          このスコアに達したら、上限に届いていなくても改善を打ち切ります。
        </span>
      </div>
    </div>
  );
}
