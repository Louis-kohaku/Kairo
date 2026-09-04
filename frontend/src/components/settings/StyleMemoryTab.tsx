import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { StyleMemory } from "../../types";

/**
 * Kairo Style Memory - what the agent has noticed about how this user likes
 * their videos, and what it does with it.
 *
 * Two lists, deliberately kept apart on screen because they mean opposite
 * things:
 *
 * - **設定した好み** is what the user changed by hand. It is a standing
 *   preference and the next production starts from it.
 * - **これまでの選択** is what Kairo itself chose. It exists so the next
 *   video does not use the same font again, and it is *not* treated as a
 *   preference - an agent that learned from its own habits would just
 *   reinforce them.
 *
 * Tendencies are shown as counts, never as "your favourite": three videos
 * with the same font is not a preference, and saying it is would be the
 * same kind of overclaim as an unlabelled AI score.
 */

export default function StyleMemoryTab() {
  const [memory, setMemory] = useState<StyleMemory | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    setError(null);
    api
      .getStyleMemory()
      .then(setMemory)
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(reload, [reload]);

  const clear = async () => {
    setBusy(true);
    try {
      setMemory(await api.clearStyleMemory());
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  if (error) return <div className="settings-error">{error}</div>;
  if (!memory) return <div className="settings-hint">読み込み中…</div>;

  const preferences = Object.entries(memory.preferences);
  const hasTendencies = Object.values(memory.tendencies).some((t) => t.length > 0);

  return (
    <div className="settings-section">
      <h3>Kairo Style Memory</h3>
      <p className="settings-hint">
        制作のたびに、あなたが変更した設定とKairoが選んだ素材を記録し、次の制作に反映します。
        記録は <code>{memory.path}</code> にローカル保存され、外部には送信されません。
        <br />
        これまでに記録した制作: {memory.production_count}件
        {memory.updated_at && `（最終更新 ${new Date(memory.updated_at).toLocaleString()}）`}
      </p>

      <h4>設定した好み</h4>
      <p className="settings-hint">
        あなたが明示的に変更した設定です。次回の制作はここから始まります。
        変更するたびに最新の値が優先されます。
      </p>
      {preferences.length === 0 ? (
        <p className="settings-hint">
          まだ記録がありません。字幕の設定などを変更すると、ここに記録されます。
        </p>
      ) : (
        <div className="memory-list">
          {preferences.map(([key, entry]) => (
            <div key={key} className="memory-row">
              <span className="memory-key">{entry.label}</span>
              <span className="memory-value">{String(entry.value)}</span>
              <span className="memory-meta">
                {entry.source === "user" ? "あなたの設定" : "Kairoの推定"}
                {entry.at && ` / ${new Date(entry.at).toLocaleDateString()}`}
              </span>
            </div>
          ))}
        </div>
      )}

      <h4>これまでの選択</h4>
      <p className="settings-hint">
        Kairoが選んだ書体・BGM・色味の履歴です。<strong>好みとしては扱いません</strong>。
        毎回同じフォントにならないよう、直近で使ったものの優先度を下げるためだけに使います。
      </p>
      {memory.recent_fonts.length > 0 && (
        <p className="settings-hint">
          直近で使った書体: {memory.recent_fonts.join("、")}
        </p>
      )}
      {hasTendencies ? (
        <div className="memory-tendencies">
          {(
            [
              ["font", "書体"],
              ["edit_style", "編集スタイル"],
              ["color_grade", "色味"],
              ["music", "BGM"],
            ] as const
          ).map(([key, label]) =>
            memory.tendencies[key].length ? (
              <div key={key} className="memory-tendency">
                <span className="memory-key">{label}</span>
                <span className="memory-value">
                  {memory.tendencies[key]
                    .map((t) => `${t.value}（${t.count}件）`)
                    .join(" / ")}
                </span>
              </div>
            ) : null,
          )}
        </div>
      ) : (
        <p className="settings-hint">
          まだ制作履歴がありません。動画を1本作ると記録が始まります。
        </p>
      )}

      <div className="settings-row">
        <button onClick={clear} disabled={busy || !memory.exists}>
          {busy ? "削除中…" : "記録を削除"}
        </button>
        <span className="settings-hint">
          削除しても制作物は残ります。次回の制作が初期設定から始まるだけです。
        </span>
      </div>
    </div>
  );
}
