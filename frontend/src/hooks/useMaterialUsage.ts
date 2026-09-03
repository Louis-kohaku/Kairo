import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { MaterialUsageReport } from "../types";

/**
 * The finished video's material credits, kept in one place.
 *
 * Shared rather than fetched per component because two views need the same
 * answer at the same time: the 使用素材 list, and the source bar under the
 * timeline that says where the shot at the playhead came from. Fetching it
 * twice would let the two disagree after a rebuild.
 */
export function useMaterialUsage(projectId: string, refreshKey: string | number) {
  const [usage, setUsage] = useState<MaterialUsageReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    try {
      const report = await api.getMaterialUsage(projectId);
      setUsage(report);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    reload();
  }, [reload, refreshKey]);

  const entryAt = useCallback(
    (seconds: number) =>
      usage?.entries.find((e) => seconds >= e.start && seconds < e.end) ?? null,
    [usage],
  );

  const entryForIndex = useCallback(
    (index: number) => usage?.entries.find((e) => e.scene_index === index) ?? null,
    [usage],
  );

  return { usage, error, loading, reload, entryAt, entryForIndex };
}
