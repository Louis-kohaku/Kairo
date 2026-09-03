import type { MaterialPlan } from "../../types";
import { MATERIAL_ORIGIN_LABELS } from "../../types";
import { formatTime } from "../../utils/format";

/**
 * The 素材プラン: what the user has, what is missing, and how the gaps will
 * be filled (design requirement 9).
 *
 * Shown before production starts so "この内容で制作開始" is an informed
 * decision. Two states, and the difference is stated rather than implied:
 * before a script exists the plan is an *estimate* (`provisional`), and
 * after the matching stage has run it is the actual decision, scene by
 * scene.
 */
export default function MaterialPlanPanel({
  plan,
  onStart,
  startLabel,
  busy,
  disabled,
  disabledReason,
}: {
  plan: MaterialPlan | null;
  onStart?: () => void;
  startLabel?: string;
  busy?: boolean;
  disabled?: boolean;
  disabledReason?: string;
}) {
  if (plan == null) return null;

  const fillEntries = Object.entries(plan.fill_counts).filter(([, n]) => n > 0);
  const hasMaterial = plan.user_photo_count + plan.user_video_count > 0;

  return (
    <div className="material-plan">
      <div className="material-plan-title">
        素材プラン
        {plan.provisional && <span className="material-plan-badge">開始前の見込み</span>}
      </div>

      <div className="material-plan-grid">
        <section>
          <h4>ユーザー素材</h4>
          {hasMaterial ? (
            <ul>
              <li>写真：{plan.user_photo_count}枚</li>
              <li>動画：{plan.user_video_count}本</li>
              {!plan.provisional && (
                <li className="material-plan-dim">
                  うち使用：写真{plan.used_photo_count}枚 / 動画{plan.used_video_count}本
                </li>
              )}
            </ul>
          ) : (
            <p className="material-plan-dim">
              なし（Kairoが必要な素材をすべて用意します）
            </p>
          )}
        </section>

        <section>
          <h4>不足素材</h4>
          {plan.provisional ? (
            plan.estimated_scene_count > 0 ? (
              <p className="material-plan-dim">
                約{plan.estimated_scene_count}シーンの想定。
                {fillEntries.length > 0
                  ? `およそ${fillEntries.reduce((n, [, v]) => n + v, 0)}カットを補完する見込みです。`
                  : "ユーザー素材でまかなえる見込みです。"}
              </p>
            ) : (
              <p className="material-plan-dim">—</p>
            )
          ) : plan.shortages.length === 0 ? (
            <p className="material-plan-dim">なし</p>
          ) : (
            <ul>
              {plan.shortages.slice(0, 8).map((s) => (
                <li key={s.scene_index}>
                  {s.need}（Scene {s.scene_number}）
                </li>
              ))}
              {plan.shortages.length > 8 && (
                <li className="material-plan-dim">ほか{plan.shortages.length - 8}件</li>
              )}
            </ul>
          )}
        </section>

        <section>
          <h4>補完方法</h4>
          {fillEntries.length === 0 ? (
            <p className="material-plan-dim">補完は不要です</p>
          ) : (
            <ul>
              {fillEntries.map(([origin, count]) => (
                <li key={origin}>
                  {MATERIAL_ORIGIN_LABELS[origin as keyof typeof MATERIAL_ORIGIN_LABELS] ??
                    origin}
                  ：{count}
                </li>
              ))}
            </ul>
          )}
          <div className="material-plan-sources">
            利用可能な補完元:{" "}
            {plan.available_fill_sources.length === 0
              ? "なし"
              : plan.available_fill_sources
                  .map(
                    (s) =>
                      MATERIAL_ORIGIN_LABELS[s as keyof typeof MATERIAL_ORIGIN_LABELS] ?? s,
                  )
                  .join(" / ")}
          </div>
        </section>
      </div>

      {plan.notes.length > 0 && (
        <ul className="material-plan-notes">
          {plan.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}

      {!plan.provisional && plan.assignments.length > 0 && (
        <details className="material-plan-details">
          <summary>シーンごとの割り当てを見る（{plan.assignments.length}シーン）</summary>
          <table className="material-plan-table">
            <thead>
              <tr>
                <th>Scene</th>
                <th>時間</th>
                <th>素材</th>
                <th>理由</th>
              </tr>
            </thead>
            <tbody>
              {plan.assignments.map((a) => (
                <tr key={a.scene_index}>
                  <td>{a.scene_number}</td>
                  <td>
                    {formatTime(a.start_time)}〜{formatTime(a.start_time + a.duration)}
                  </td>
                  <td>
                    <span className={`origin-badge origin-${a.origin}`}>
                      {MATERIAL_ORIGIN_LABELS[a.origin]}
                    </span>{" "}
                    {a.filename || a.visual_prompt.slice(0, 24)}
                  </td>
                  <td className="material-plan-dim">{a.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      {onStart && (
        <div className="material-plan-start">
          <button
            className="primary"
            onClick={onStart}
            disabled={busy || disabled}
            title={disabled ? disabledReason : undefined}
          >
            {busy ? "開始しています…" : (startLabel ?? "この内容で制作開始")}
          </button>
          {disabled && disabledReason && (
            <span className="material-plan-dim">{disabledReason}</span>
          )}
        </div>
      )}
    </div>
  );
}
