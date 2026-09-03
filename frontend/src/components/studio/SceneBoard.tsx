import { useMemo, useState } from "react";
import { api } from "../../api/client";
import type { MediaAsset, ProductionEvent, Scene } from "../../types";
import { MATERIAL_ORIGIN_LABELS, VISUAL_TYPE_LABELS } from "../../types";
import { formatTime } from "../../utils/format";

/**
 * The scene board: every designed beat with its purpose, emotion, camera,
 * caption and audio (design doc section 20).
 *
 * Each card shows the *design decisions*, not just the text, because those
 * are what the user needs in order to judge or change a scene - "3.2秒 /
 * 驚き / close-up / 小さな驚き音" says more about what will be on screen
 * than the narration does.
 *
 * A card is also live: while a run is generating, the scene currently being
 * worked on is highlighted from the event stream, so the board doubles as
 * a progress view.
 */
export default function SceneBoard({
  scenes,
  events,
  assets,
  isRunning,
  onChanged,
}: {
  scenes: Scene[];
  events: ProductionEvent[];
  assets: MediaAsset[];
  isRunning: boolean;
  onChanged: () => void;
}) {
  const activeSceneId = useMemo(() => {
    // Only while a run is actually in flight: the last scene the pipeline
    // touched stays in the event log forever, and marking it "生成中" on a
    // finished video is a claim about the present that isn't true.
    if (!isRunning) return null;
    for (let i = events.length - 1; i >= 0; i--) {
      if (events[i].scene_id && events[i].status === "running") return events[i].scene_id;
    }
    return null;
  }, [events, isRunning]);

  // Running start offsets, so each card can show where it sits on the
  // finished timeline rather than only its own length.
  const startTimes = useMemo(
    () =>
      scenes.reduce<number[]>((acc, _scene, i) => {
        acc.push(i === 0 ? 0 : acc[i - 1] + scenes[i - 1].estimated_duration);
        return acc;
      }, []),
    [scenes],
  );

  if (scenes.length === 0) {
    return (
      <div className="scene-board-empty">
        まだシーンがありません。制作を開始すると、ここにシーン設計が並びます。
      </div>
    );
  }

  const total = scenes.reduce((n, s) => n + s.estimated_duration, 0);

  return (
    <div className="scene-board">
      <div className="scene-board-head">
        {scenes.length}シーン / 合計 {formatTime(total)}
      </div>
      <div className="scene-board-grid">
        {scenes.map((scene, i) => (
          <SceneDetailCard
            key={scene.id}
            scene={scene}
            index={i}
            startTime={startTimes[i]}
            active={scene.id === activeSceneId}
            assets={assets}
            onChanged={onChanged}
          />
        ))}
      </div>
    </div>
  );
}

function SceneDetailCard({
  scene,
  index,
  startTime,
  active,
  assets,
  onChanged,
}: {
  scene: Scene;
  index: number;
  startTime: number;
  active: boolean;
  assets: MediaAsset[];
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [subtitle, setSubtitle] = useState(scene.subtitle_text);
  const [narration, setNarration] = useState(scene.narration);
  const [saving, setSaving] = useState(false);

  // Anything with a picture can stand in for a scene's visual - the
  // user's photos as much as their footage. Audio assets (the generated
  // BGM among them) are excluded because they would produce a black frame.
  // Clips Kairo rendered are excluded too: pinning a scene to its own
  // output would re-wrap the previous render on every rebuild.
  const pinnableAssets = assets.filter(
    (a) => (a.kind === "video" || a.kind === "image") && (a.origin ?? "user") === "user",
  );

  const save = async (patch: Parameters<typeof api.updateScene>[1]) => {
    setSaving(true);
    try {
      await api.updateScene(scene.id, patch);
      onChanged();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className={`scene-detail${active ? " scene-detail-active" : ""}${
        scene.is_hook ? " scene-detail-hook" : ""
      }`}
    >
      <div className="scene-detail-head">
        <span className="scene-detail-no">Scene {String(index + 1).padStart(2, "0")}</span>
        {scene.is_hook && <span className="scene-detail-badge">Hook</span>}
        {active && <span className="scene-detail-badge live">生成中</span>}
        <span style={{ flex: 1 }} />
        <span className={`scene-status scene-status-${scene.status}`}>{scene.status}</span>
      </div>

      <div className="scene-detail-time">
        {formatTime(startTime)} – {formatTime(startTime + scene.estimated_duration)}
        <span className="scene-detail-dur">{scene.estimated_duration.toFixed(1)}秒</span>
      </div>

      <div className="scene-detail-caption">「{scene.subtitle_text || "（字幕なし）"}」</div>

      <dl className="scene-detail-meta">
        {scene.purpose && (
          <>
            <dt>目的</dt>
            <dd>{scene.purpose}</dd>
          </>
        )}
        {scene.emotion && (
          <>
            <dt>感情</dt>
            <dd>{scene.emotion}</dd>
          </>
        )}
        <dt>映像</dt>
        <dd>
          {VISUAL_TYPE_LABELS[scene.visual_type] ?? scene.visual_type}
          {scene.camera ? ` · ${scene.camera}` : ""}
        </dd>
        <dd className="scene-detail-visual">{scene.visual_prompt}</dd>
        {scene.sfx && (
          <>
            <dt>効果音</dt>
            <dd>{scene.sfx}</dd>
          </>
        )}
        {scene.narration && (
          <>
            <dt>ナレーション</dt>
            <dd className="scene-detail-narration">
              {scene.narration}
              {scene.narration_duration != null && (
                <span className="scene-detail-dur">
                  {scene.narration_duration.toFixed(1)}秒
                </span>
              )}
            </dd>
          </>
        )}
        <dt>素材</dt>
        <dd>
          {MATERIAL_ORIGIN_LABELS[
            (scene.material_origin || "") as keyof typeof MATERIAL_ORIGIN_LABELS
          ] ??
            (scene.asset_source === "user"
              ? "ユーザー素材を使用"
              : scene.media_asset_id
                ? "生成済み"
                : "未生成")}
          {scene.material_note && (
            <span className="scene-detail-dur">{scene.material_note}</span>
          )}
        </dd>
      </dl>

      <div className="scene-detail-actions">
        <button onClick={() => setEditing((v) => !v)}>
          {editing ? "閉じる" : "編集"}
        </button>
      </div>

      {editing && (
        <div className="scene-detail-edit">
          <label>
            字幕
            <input
              value={subtitle}
              onChange={(e) => setSubtitle(e.target.value)}
              onBlur={() => subtitle !== scene.subtitle_text && save({ subtitle_text: subtitle })}
              disabled={saving}
            />
          </label>
          <label>
            ナレーション
            <textarea
              rows={2}
              value={narration}
              onChange={(e) => setNarration(e.target.value)}
              onBlur={() => narration !== scene.narration && save({ narration })}
              disabled={saving}
            />
          </label>
          <label>
            長さ(秒)
            <input
              type="number"
              min={0.5}
              step={0.1}
              value={scene.estimated_duration}
              onChange={(e) => save({ estimated_duration: Number(e.target.value) })}
              disabled={saving}
            />
          </label>
          <label>
            このシーンの素材
            <select
              value={scene.asset_source === "user" ? (scene.user_asset_id ?? "") : "__ai__"}
              onChange={(e) =>
                save(
                  e.target.value === "__ai__"
                    ? { asset_source: "auto" }
                    : { asset_source: "user", user_asset_id: e.target.value },
                )
              }
              disabled={saving}
            >
              <option value="__ai__">AIが生成する</option>
              {pinnableAssets.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.kind === "image" ? "🖼 " : "🎬 "}
                  {a.original_filename}
                </option>
              ))}
            </select>
          </label>
          <div className="scene-detail-hint">
            ここでの変更は台本に反映されます。映像へ反映するにはAIチャットから
            「Scene {index + 1}を作り直して」と指示してください。自分の素材を選んだ場合、
            AIが再生成してもその素材は置き換えられません。
          </div>
        </div>
      )}
    </div>
  );
}
