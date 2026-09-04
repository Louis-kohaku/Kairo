import type {
  AssetDecisions,
  EditDirective,
  SubtitleDesignPlan,
  TransitionPlan,
} from "../../types";

/**
 * 今回のKairo編集方針 - what the agent decided before it started editing.
 *
 * The rule this panel exists for (requirement 17) is that none of these
 * judgements may be a black box. So every row carries its reason, the
 * provenance badge says how much evidence actually went into the directive,
 * and a decision that could not be made says so rather than being omitted -
 * an empty row reads as "nothing to report", which is the one thing it must
 * never mean.
 */

const DECIDED_BY_LABEL: Record<string, { text: string; tone: string }> = {
  defaults: {
    text: "Kairo組み込みの定石のみ（AI判断なし）",
    tone: "neutral",
  },
  "defaults+profile": {
    text: "ジャンル傾向を反映",
    tone: "neutral",
  },
  "defaults+ai": { text: "AIが調整", tone: "ok" },
  "defaults+profile+ai": {
    text: "ジャンル傾向 + AIが調整",
    tone: "ok",
  },
};

const TEMPO_LABEL: Record<string, string> = {
  slow: "ゆっくり",
  medium: "標準",
  fast: "速い",
};

const DENSITY_LABEL: Record<string, string> = {
  minimal: "最小限",
  low: "少なめ",
  medium: "標準",
  high: "多め",
};

const ANIMATION_LABEL: Record<string, string> = {
  none: "なし",
  fade: "フェード",
  pop: "ポップ",
  slide_up: "下から出す",
};

function Row({
  label,
  value,
  reason,
}: {
  label: string;
  value: React.ReactNode;
  reason?: string;
}) {
  return (
    <div className="agent-row">
      <span className="agent-key">{label}</span>
      <span className="agent-value">
        {value}
        {reason ? <span className="agent-reason">{reason}</span> : null}
      </span>
    </div>
  );
}

export default function EditDirectivePanel({
  directive,
  transitions,
  subtitleDesign,
  assets,
}: {
  directive: EditDirective | null;
  transitions: TransitionPlan | null;
  subtitleDesign: SubtitleDesignPlan | null;
  assets: AssetDecisions | null;
}) {
  if (!directive || !directive.style_label) {
    return (
      <div className="agent-panel agent-panel-empty">
        まだ編集方針が決まっていません。制作を開始すると、
        ジャンル・スタイル・テンポ・構成・字幕・フォント・画面切り替え・BGM・色味を
        AIが決定し、その理由とあわせてここに表示します。
      </div>
    );
  }

  const provenance =
    DECIDED_BY_LABEL[directive.decided_by] ?? DECIDED_BY_LABEL.defaults;
  const ranking = assets?.font_ranking ?? null;
  const font = assets?.font ?? null;

  return (
    <div className="agent-panel">
      <section className="agent-section">
        <div className="agent-profile-head">
          今回のKairo編集方針
          <span className={`agent-badge agent-badge-${provenance.tone}`}>
            {provenance.text}
          </span>
        </div>

        <Row
          label="ジャンル"
          value={directive.genre_label || directive.genre}
        />
        <Row
          label="編集スタイル"
          value={`${directive.style_label}（${directive.mood}）`}
          reason={directive.notes[0]}
        />
        <Row label="配信先" value={directive.platform_label} />
        <Row
          label="動画尺 / 画面"
          value={`${directive.duration_seconds.toFixed(0)}秒 / ${directive.width}x${directive.height}`}
        />
        <Row
          label="テンポ"
          value={`${TEMPO_LABEL[directive.tempo] ?? directive.tempo}（1カット約${directive.scene_seconds.toFixed(1)}秒）`}
        />
        <Row
          label="ストーリー構成"
          value={
            <span className="agent-story">
              {directive.story.map((beat) => beat.label).join(" → ") || "—"}
            </span>
          }
          reason={directive.story.map((b) => b.purpose).slice(0, 2).join(" / ")}
        />
        <Row
          label="冒頭で見せるもの"
          value={directive.hook_direction || "—"}
          reason={`最初の${directive.hook_seconds.toFixed(1)}秒で判断されます`}
        />
      </section>

      <section className="agent-section">
        <h3>フォント</h3>
        {font && font.found ? (
          <>
            <Row
              label="使用する書体"
              value={font.family || font.name}
              reason={font.reason}
            />
            <Row
              label="求めた印象"
              value={directive.font.reason || "—"}
              reason={
                `可読性${directive.font.min_readability}以上 / ` +
                `ウェイト${directive.font.weight_min}〜${directive.font.weight_max}`
              }
            />
            {ranking && (
              <>
                <Row
                  label="選定の内訳"
                  value={
                    `${ranking.eligible}書体を採点` +
                    `（ライセンスで${ranking.rejected_for_license}件、` +
                    `可読性${ranking.readability_floor}未満で${ranking.below_readability_floor}件を除外）`
                  }
                />
                {ranking.candidates.length > 1 && (
                  <div className="agent-font-candidates">
                    {ranking.candidates.slice(0, 5).map((candidate, index) => (
                      <div
                        key={candidate.asset_id}
                        className={
                          index === 0
                            ? "agent-font-candidate agent-font-candidate-best"
                            : "agent-font-candidate"
                        }
                      >
                        <span className="agent-font-rank">{index + 1}</span>
                        <span className="agent-font-family">{candidate.family}</span>
                        <span className="agent-font-score">
                          {candidate.score.toFixed(0)}点
                        </span>
                        <span className="agent-font-why">
                          {candidate.reasons.slice(0, 2).join(" / ")}
                          {candidate.recently_used ? "（直近で使用済み）" : ""}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
                {ranking.recent_families.length > 0 && (
                  <p className="agent-note">
                    直近の動画で使った書体（{ranking.recent_families.slice(0, 3).join("・")}
                    ）は、毎回同じにならないよう優先度を下げています。
                  </p>
                )}
                {!ranking.profiled && (
                  <p className="agent-warning">
                    フォントの印象プロファイルが未算出のため、可読性中心で選んでいます。
                    設定 &gt; ライブラリでフォントを再スキャンすると、
                    スタイルに合わせた選定ができます。
                  </p>
                )}
              </>
            )}
          </>
        ) : (
          <p className="agent-warning">
            フォントを自動選択できませんでした。
            {font?.reason ??
              "ライセンス条件を満たす日本語フォントが見つかりませんでした。"}
          </p>
        )}
      </section>

      <section className="agent-section">
        <h3>字幕</h3>
        <Row
          label="字幕量"
          value={`${DENSITY_LABEL[directive.subtitle.density] ?? directive.subtitle.density}（全カットの約${(directive.subtitle.coverage * 100).toFixed(0)}%）`}
          reason={directive.subtitle.reason}
        />
        <Row
          label="位置 / 縁取り"
          value={`${directive.subtitle.position} / ${directive.subtitle.style}`}
        />
        <Row
          label="アニメーション"
          value={
            ANIMATION_LABEL[directive.subtitle.animation] ??
            directive.subtitle.animation
          }
        />
        <Row
          label="重要語の強調"
          value={
            directive.subtitle.emphasis
              ? `あり（${directive.subtitle.emphasis_scale.toFixed(2)}倍）`
              : "なし"
          }
        />
        {subtitleDesign && (
          <>
            <Row label="実際の字幕" value={subtitleDesign.summary} />
            {subtitleDesign.cues.filter((c) => c.emphasis.length > 0).length > 0 && (
              <p className="agent-note">
                強調表示する語:{" "}
                {subtitleDesign.cues
                  .filter((c) => c.emphasis.length > 0)
                  .slice(0, 6)
                  .map((c) => c.emphasis.join("・"))
                  .join(" / ")}
              </p>
            )}
          </>
        )}
      </section>

      <section className="agent-section">
        <h3>画面切り替え</h3>
        <Row
          label="方針"
          value={`基本はカット。最大${(directive.transitions.max_ratio * 100).toFixed(0)}%のカット間のみ切り替え`}
          reason={directive.transitions.reason}
        />
        {transitions ? (
          <>
            <Row label="実際の適用" value={transitions.summary} />
            {transitions.choices.filter((c) => c.transition !== "cut").length > 0 && (
              <ul className="agent-transitions">
                {transitions.choices
                  .filter((c) => c.transition !== "cut")
                  .map((choice) => (
                    <li key={choice.index}>
                      <span className="agent-transition-where">
                        Scene {choice.index} → {choice.index + 1}
                      </span>
                      <span className="agent-transition-kind">
                        {choice.label}（{choice.duration.toFixed(2)}秒）
                      </span>
                      <span className="agent-reason">
                        {choice.reason_label}：{choice.detail}
                      </span>
                    </li>
                  ))}
              </ul>
            )}
          </>
        ) : (
          <p className="agent-note">
            切り替えの計画は編集フェーズで決まります。
          </p>
        )}
      </section>

      <section className="agent-section">
        <h3>映像と音</h3>
        <Row
          label="色味"
          value={directive.color.label || directive.color.id}
          reason={directive.color.reason}
        />
        <Row
          label="写真の動き"
          value={`強さ${directive.photo_motion.intensity.toFixed(2)}（${directive.photo_motion.prefer.join(" / ")}）`}
          reason={directive.photo_motion.reason}
        />
        <Row
          label="BGM"
          value={
            `${directive.audio.bgm_mood}` +
            (directive.audio.bgm_bpm_range.length === 2
              ? `（${directive.audio.bgm_bpm_range[0].toFixed(0)}〜${directive.audio.bgm_bpm_range[1].toFixed(0)} BPM）`
              : "")
          }
          reason={directive.audio.reason}
        />
        <Row
          label="効果音"
          value={
            directive.audio.sfx_per_minute <= 0.01
              ? "使用しません"
              : `1分あたり最大${directive.audio.sfx_per_minute.toFixed(0)}個`
          }
        />
        <Row
          label="音量"
          value={
            directive.audio.normalize
              ? `${directive.audio.target_lufs.toFixed(0)} LUFSに揃えます`
              : "調整しません"
          }
          reason={
            directive.audio.duck_narration
              ? "ナレーション中はBGMを自動で下げます"
              : undefined
          }
        />
        {directive.audio.narration_rate !== 0 && (
          <Row
            label="ナレーション"
            value={`読み上げ速度 ${directive.audio.narration_rate > 0 ? "+" : ""}${directive.audio.narration_rate}`}
            reason={directive.audio.narration_style || undefined}
          />
        )}
      </section>

      {(directive.notes.length > 1 || directive.ai_note) && (
        <section className="agent-section">
          <h3>この方針にした理由</h3>
          {directive.material_summary && (
            <p className="agent-note">素材: {directive.material_summary}</p>
          )}
          <ul className="agent-notes">
            {directive.notes.slice(1).map((note, index) => (
              <li key={index}>{note}</li>
            ))}
          </ul>
          {directive.ai_note && <p className="agent-ai-note">{directive.ai_note}</p>}
        </section>
      )}
    </div>
  );
}
