import { useCallback, useRef, useState } from "react";
import { api } from "../../api/client";
import type { Material, MaterialMode, MaterialUploadError } from "../../types";
import { formatTime } from "../../utils/format";

/**
 * The material area: drop files in, see what Kairo made of them, and say
 * how they should be used.
 *
 * It sits directly under the instruction box on the start screen rather
 * than behind a settings menu, because "写真を渡すだけで編集される" is only
 * true if the place to hand over the photos is the second thing on the
 * screen (design requirement 13).
 *
 * The panel is explicit that material is optional. A user who has no
 * photos should not have to work out whether Kairo is usable to them, so
 * the drop zone says so in as many words.
 */

const ACCEPT = "image/*,video/*";
const MODES: { id: MaterialMode; label: string; hint: string }[] = [
  {
    id: "ai_auto",
    label: "AIにおまかせ",
    hint: "内容に合う素材をAIが選び、順番と使う長さを決めます",
  },
  {
    id: "use_all",
    label: "できるだけ全部使う",
    hint: "アップロードした素材をできる限りすべて登場させます",
  },
  {
    id: "selected",
    label: "選択した素材だけ使う",
    hint: "チェックを入れた素材だけを使います",
  },
];

export default function MaterialPanel({
  projectId,
  materials,
  loading,
  visionAvailable,
  mode,
  selectedIds,
  onModeChange,
  onSelectionChange,
  onChanged,
  busy,
  compact,
}: {
  projectId: string;
  materials: Material[];
  loading: boolean;
  visionAvailable: boolean;
  mode: MaterialMode;
  selectedIds: string[];
  onModeChange: (mode: MaterialMode) => void;
  onSelectionChange: (ids: string[]) => void;
  onChanged: () => void;
  busy?: boolean;
  compact?: boolean;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [errors, setErrors] = useState<MaterialUploadError[]>([]);
  const [analyzing, setAnalyzing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const photos = materials.filter((m) => m.kind === "image");
  const videos = materials.filter((m) => m.kind === "video");
  const unanalyzed = materials.filter((m) => m.analysis_status !== "done");

  const upload = useCallback(
    async (files: File[]) => {
      if (files.length === 0) return;
      setUploading(true);
      setErrors([]);
      setNotice(null);
      try {
        const result = await api.uploadMaterials(projectId, files);
        setErrors(result.errors);
        if (result.imported.length > 0) {
          setNotice(`${result.imported.length}点の素材を追加しました。`);
        }
        onChanged();
      } catch (e) {
        // The backend returns per-file reasons in the detail body; a
        // single "エラーが発生しました" here would throw them away.
        const detail = (e as Error).message ?? String(e);
        try {
          const parsed = JSON.parse(detail.replace(/^Error: /, ""));
          setErrors(parsed.errors ?? []);
        } catch {
          setErrors([
            {
              filename: files.map((f) => f.name).join(", "),
              message: "素材を読み込めませんでした。",
              cause: detail,
              hint: "ファイル形式を確認して、もう一度お試しください。",
              raw: detail,
            },
          ]);
        }
      } finally {
        setUploading(false);
        if (fileInput.current) fileInput.current.value = "";
      }
    },
    [projectId, onChanged],
  );

  const analyze = async () => {
    setAnalyzing(true);
    setNotice(null);
    try {
      const result = await api.analyzeMaterials(projectId);
      if (result.failed.length > 0) {
        setErrors(
          result.failed.map((f) => ({
            filename: f.filename,
            message: `「${f.filename}」を解析できませんでした。`,
            cause: f.error ?? "原因を特定できませんでした。",
            hint: "別の形式に変換するか、この素材を削除してから制作してください。",
            raw: f.error ?? "",
          })),
        );
      } else {
        setNotice("素材の解析が完了しました。");
      }
      onChanged();
    } catch (e) {
      setNotice(null);
      setErrors([
        {
          filename: "",
          message: "素材の解析に失敗しました。",
          cause: String(e),
          hint: "LM Studioの状態を確認してから、もう一度お試しください。",
          raw: String(e),
        },
      ]);
    } finally {
      setAnalyzing(false);
    }
  };

  const remove = async (asset: Material) => {
    await api.deleteMaterial(asset.id);
    onSelectionChange(selectedIds.filter((id) => id !== asset.id));
    onChanged();
  };

  const toggle = (asset: Material) => {
    onSelectionChange(
      selectedIds.includes(asset.id)
        ? selectedIds.filter((id) => id !== asset.id)
        : [...selectedIds, asset.id],
    );
  };

  return (
    <div className={`material-panel${compact ? " material-panel-compact" : ""}`}>
      <div
        className={`material-drop${dragging ? " material-drop-on" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          upload(Array.from(e.dataTransfer.files ?? []));
        }}
        onClick={() => fileInput.current?.click()}
      >
        <div className="material-drop-icon">📁</div>
        <div className="material-drop-title">素材を追加</div>
        <div className="material-drop-line">写真・動画をここにドラッグ＆ドロップ</div>
        <div className="material-drop-formats">JPG / PNG / WEBP / MP4 / MOV など</div>
        <button className="primary material-drop-button" disabled={uploading || busy}>
          {uploading ? "読み込んでいます…" : "写真・動画を選ぶ"}
        </button>
        <div className="material-drop-optional">
          素材がなくても制作できます。
          <br />
          Kairoが必要な素材を自動で用意します。
        </div>
        <input
          ref={fileInput}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          onChange={(e) => upload(Array.from(e.target.files ?? []))}
        />
      </div>

      {errors.length > 0 && (
        <div className="material-errors">
          {errors.map((err, i) => (
            <div key={`${err.filename}-${i}`} className="material-error">
              <div className="material-error-head">{err.message}</div>
              {err.cause && <div className="material-error-cause">原因: {err.cause}</div>}
              {err.hint && <div className="material-error-hint">対処: {err.hint}</div>}
            </div>
          ))}
          <button className="material-error-dismiss" onClick={() => setErrors([])}>
            閉じる
          </button>
        </div>
      )}

      {notice && <div className="material-notice">{notice}</div>}

      {materials.length > 0 && (
        <>
          <div className="material-usage-mode">
            <div className="launcher-label">素材の使い方</div>
            <div className="launcher-chips">
              {MODES.map((m) => (
                <button
                  key={m.id}
                  className={mode === m.id ? "chip chip-on" : "chip"}
                  onClick={() => onModeChange(m.id)}
                  title={m.hint}
                  disabled={busy}
                >
                  {m.label}
                </button>
              ))}
            </div>
            <div className="material-mode-hint">
              {MODES.find((m) => m.id === mode)?.hint}
            </div>
          </div>

          <div className="material-list-head">
            <span>
              使用素材 — 写真{photos.length}枚 / 動画{videos.length}本
            </span>
            <span className="material-list-actions">
              {unanalyzed.length > 0 && (
                <button onClick={analyze} disabled={analyzing || busy}>
                  {analyzing ? "解析中…" : `未解析の${unanalyzed.length}点を解析`}
                </button>
              )}
              {unanalyzed.length === 0 && (
                <button onClick={analyze} disabled={analyzing || busy}>
                  {analyzing ? "解析中…" : "解析し直す"}
                </button>
              )}
            </span>
          </div>

          {!visionAvailable && (
            <div className="material-vision-note">
              画像を解析できるAIモデル（Vision対応）がLM Studioにロードされていないため、
              写っているものの自動認識は行いません。ファイル名・解像度・明るさから推定します。
            </div>
          )}

          <div className="material-grid">
            {materials.map((asset) => (
              <MaterialCard
                key={asset.id}
                asset={asset}
                selectable={mode === "selected"}
                selected={selectedIds.includes(asset.id)}
                onToggle={() => toggle(asset)}
                onRemove={() => remove(asset)}
                busy={busy}
              />
            ))}
          </div>
        </>
      )}

      {loading && materials.length === 0 && (
        <div className="material-empty">素材を読み込んでいます…</div>
      )}
    </div>
  );
}

function MaterialCard({
  asset,
  selectable,
  selected,
  onToggle,
  onRemove,
  busy,
}: {
  asset: Material;
  selectable: boolean;
  selected: boolean;
  onToggle: () => void;
  onRemove: () => void;
  busy?: boolean;
}) {
  const analysis = asset.analysis;
  const planned = asset.planned_use;
  const spec =
    asset.kind === "video"
      ? `${formatTime(asset.duration)}${asset.width ? ` · ${asset.width}×${asset.height}` : ""}`
      : asset.width
        ? `${asset.width}×${asset.height}`
        : "";

  return (
    <div className={`material-card${selected ? " material-card-on" : ""}`}>
      <div className="material-thumb">
        <img
          src={api.materialThumbnailUrl(asset.id)}
          alt={asset.original_filename}
          loading="lazy"
          onError={(e) => {
            (e.target as HTMLImageElement).style.visibility = "hidden";
          }}
        />
        <span className="material-kind">{asset.kind === "video" ? "🎬 動画" : "🖼 写真"}</span>
      </div>

      <div className="material-card-body">
        <div className="material-name" title={asset.original_filename}>
          {asset.original_filename}
        </div>
        <div className="material-spec">{spec}</div>

        {analysis && analysis.tags.length > 0 && (
          <div className="material-tags">
            {analysis.tags.slice(0, 6).map((tag) => (
              <span key={tag} className="material-tag">
                {tag}
              </span>
            ))}
          </div>
        )}

        {asset.analysis_status === "failed" && (
          <div className="material-card-error">
            解析できませんでした: {asset.analysis_error ?? "原因不明"}
          </div>
        )}
        {asset.analysis_status === "pending" && (
          <div className="material-card-pending">未解析</div>
        )}
        {analysis && (
          <div className="material-analyzed-by">
            {analysis.analyzed_by === "vision_ai"
              ? "AI画像解析"
              : "ファイル名・画像情報から推定"}
          </div>
        )}

        <div className={`material-use${planned ? " material-use-on" : ""}`}>
          {planned
            ? `使用予定: Scene ${planned.scene_number}（${formatTime(planned.start_time)}〜）`
            : "未使用"}
        </div>
      </div>

      <div className="material-card-actions">
        {selectable && (
          <label className="material-check">
            <input type="checkbox" checked={selected} onChange={onToggle} disabled={busy} />
            使う
          </label>
        )}
        <button className="material-remove" onClick={onRemove} disabled={busy}>
          削除
        </button>
      </div>
    </div>
  );
}
