import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { Material, MaterialMode, MaterialPlan } from "../types";

/**
 * One project's material, its usage mode, and the plan derived from them.
 *
 * Lives in a hook rather than in the launcher because the same state is
 * needed after a production starts: adding photos to a finished video
 * (design requirement 12) is the same list, the same mode and the same
 * plan, just at a different point in time.
 */
export function useMaterials(projectId: string, targetSeconds: number) {
  const [materials, setMaterials] = useState<Material[]>([]);
  const [visionAvailable, setVisionAvailable] = useState(false);
  const [mode, setMode] = useState<MaterialMode>("ai_auto");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [plan, setPlan] = useState<MaterialPlan | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.listMaterials(projectId);
      setMaterials(data.materials);
      setVisionAvailable(data.vision_available);
      setError(null);
      return data.materials;
    } catch (e) {
      setError(String(e));
      return [];
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    setLoading(true);
    refresh();
  }, [refresh]);

  // The plan is derived, so it is refetched whenever anything it depends on
  // changes. Cheap on the backend (it is either a stored plan or a count),
  // and it means the start screen's 素材プラン is never stale relative to
  // the list right above it.
  const refreshPlan = useCallback(async () => {
    try {
      const next = await api.getMaterialPlan(projectId, {
        mode,
        targetSeconds,
        selected: selectedIds,
      });
      setPlan(next);
    } catch {
      setPlan(null);
    }
  }, [projectId, mode, targetSeconds, selectedIds]);

  useEffect(() => {
    refreshPlan();
  }, [refreshPlan, materials]);

  const reload = useCallback(async () => {
    await refresh();
    await refreshPlan();
  }, [refresh, refreshPlan]);

  return {
    materials,
    visionAvailable,
    mode,
    setMode,
    selectedIds,
    setSelectedIds,
    plan,
    loading,
    error,
    reload,
    refreshPlan,
  };
}
