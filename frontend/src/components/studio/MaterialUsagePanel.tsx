import { api } from "../../api/client";
import type { Material, MaterialUsageEntry, MaterialUsageReport } from "../../types";
import { MATERIAL_ORIGIN_LABELS } from "../../types";
import { formatTime } from "../../utils/format";

/**
 * 使用素材: which material ended up where in the finished video, grouped by
 * where it came from (design requirement 11).
 *
 * Every row is clickable and seeks the preview to that moment, which is
 * what makes "タイムライン上から素材をクリックしたら、この素材はどこから
 * 来たのかを確認できる" work in both directions - from the list to the
 * video, and (via `highlightAt`) from the video back to the list.
 */
export default function MaterialUsagePanel({
  materials,
  usage,
  loading,
  error,
  playhead,
  onSeek,
}: {
  materials: Material[];
  usage: MaterialUsageReport | null;
  loading: boolean;
  error: string | null;
  playhead?: number;
  onSeek?: (seconds: number) => void;
}) {
  if (loading && usage == null) return <div className="studio-empty">読み込んでいます…</div>;
  if (error) return <div className="editor-error">{error}</div>;
  if (usage == null || usage.entries.length === 0) {
    return (
      <div className="studio-empty">
        まだ使用素材がありません。制作が進むとここに一覧が表示されます。
      </div>
    );
  }

  const groups: { origin: string; entries: MaterialUsageEntry[] }[] = [];
  for (const entry of usage.entries) {
    const found = groups.find((g) => g.origin === entry.origin);
    if (found) found.entries.push(entry);
    else groups.push({ origin: entry.origin, entries: [entry] });
  }
  // Group by origin, keeping the priority order rather than order of
  // appearance, so the user's own material is always the first block.
  const ORDER = ["user", "local", "web", "ai_generated", "procedural"];
  groups.sort((a, b) => ORDER.indexOf(a.origin) - ORDER.indexOf(b.origin));

  const byId: Record<string, Material> = {};
  for (const m of materials) byId[m.id] = m;

  return (
    <div className="material-usage">
      <div className="material-usage-head">
        使用素材 — 全{usage.entries.length}カット / {formatTime(usage.total_duration)}
      </div>

      {groups.map((group) => (
        <section key={group.origin} className="material-usage-group">
          <h4>
            <span className={`origin-badge origin-${group.origin}`}>
              {MATERIAL_ORIGIN_LABELS[
                group.origin as keyof typeof MATERIAL_ORIGIN_LABELS
              ] ?? group.origin}
            </span>
            <span className="material-usage-count">{group.entries.length}カット</span>
          </h4>
          <ul>
            {group.entries.map((entry) => {
              const active =
                playhead != null && playhead >= entry.start && playhead < entry.end;
              const asset = entry.asset_id ? byId[entry.asset_id] : undefined;
              return (
                <li
                  key={entry.scene_index}
                  className={active ? "material-usage-row active" : "material-usage-row"}
                  onClick={() => onSeek?.(entry.start)}
                  title="クリックするとこの位置から再生します"
                >
                  {entry.asset_id && (
                    <img
                      className="material-usage-thumb"
                      src={api.materialThumbnailUrl(entry.asset_id)}
                      alt=""
                      loading="lazy"
                      onError={(e) => {
                        (e.target as HTMLImageElement).style.visibility = "hidden";
                      }}
                    />
                  )}
                  <div className="material-usage-main">
                    <div className="material-usage-name">
                      {entry.filename || `Scene ${entry.scene_number}`}
                    </div>
                    <div className="material-usage-time">
                      {formatTime(entry.start)}〜{formatTime(entry.end)}
                      {entry.source_start != null &&
                        ` / 元素材 ${formatTime(entry.source_start)}〜`}
                    </div>
                    {entry.note && <div className="material-usage-note">{entry.note}</div>}
                    {asset?.origin_detail && !entry.note && (
                      <div className="material-usage-note">{asset.origin_detail}</div>
                    )}
                  </div>
                  <div className="material-usage-subtitle">{entry.subtitle}</div>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
