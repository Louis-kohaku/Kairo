import type {
  Clip,
  Job,
  MediaAsset,
  Project,
  ProductionData,
  Scene,
  Segment,
  SilenceCutPlan,
  SubtitleCue,
  Timeline,
} from "../types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8756";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers:
      init?.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : undefined,
    ...init,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail ?? `Request failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listProjects: () => request<Project[]>("/api/projects"),

  createProject: (name: string, fps = 30, width = 1920, height = 1080) =>
    request<Project>("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name, fps, width, height }),
    }),

  getProject: (id: string) => request<Project>(`/api/projects/${id}`),

  listMedia: (projectId: string) =>
    request<MediaAsset[]>(`/api/projects/${projectId}/media`),

  uploadMedia: (projectId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<MediaAsset>(`/api/projects/${projectId}/media`, {
      method: "POST",
      body: form,
    });
  },

  mediaFileUrl: (assetId: string) => `${API_BASE}/api/media/${assetId}/file`,

  getTimeline: (projectId: string) =>
    request<Timeline>(`/api/projects/${projectId}/timeline`),

  addClip: (
    trackId: string,
    mediaAssetId: string,
    inPoint = 0,
    outPoint?: number,
    index?: number,
  ) =>
    request<Clip>(`/api/tracks/${trackId}/clips`, {
      method: "POST",
      body: JSON.stringify({
        media_asset_id: mediaAssetId,
        in_point: inPoint,
        out_point: outPoint ?? null,
        index: index ?? null,
      }),
    }),

  updateClip: (
    clipId: string,
    patch: Partial<Pick<Clip, "in_point" | "out_point" | "volume">>,
  ) =>
    request<Clip>(`/api/clips/${clipId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  deleteClip: (clipId: string) =>
    request<{ ok: boolean }>(`/api/clips/${clipId}`, { method: "DELETE" }),

  splitClip: (trackId: string, time: number) =>
    request<Clip[]>(`/api/tracks/${trackId}/split`, {
      method: "POST",
      body: JSON.stringify({ time }),
    }),

  startRender: (projectId: string, burnSubtitles = false) =>
    request<Job>(
      `/api/projects/${projectId}/render?burn_subtitles=${burnSubtitles}`,
      { method: "POST" },
    ),

  getJob: (jobId: string) => request<Job>(`/api/jobs/${jobId}`),

  listJobs: (projectId: string) =>
    request<Job[]>(`/api/projects/${projectId}/jobs`),

  downloadUrl: (jobId: string) => `${API_BASE}/api/jobs/${jobId}/download`,

  generateSubtitles: (projectId: string) =>
    request<Job>(`/api/projects/${projectId}/subtitles/generate`, {
      method: "POST",
    }),

  listSubtitles: (projectId: string) =>
    request<SubtitleCue[]>(`/api/projects/${projectId}/subtitles`),

  updateSubtitle: (
    cueId: string,
    patch: Partial<Pick<SubtitleCue, "start" | "end" | "text">>,
  ) =>
    request<SubtitleCue>(`/api/subtitles/${cueId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  deleteSubtitle: (cueId: string) =>
    request<{ ok: boolean }>(`/api/subtitles/${cueId}`, { method: "DELETE" }),

  srtUrl: (projectId: string) =>
    `${API_BASE}/api/projects/${projectId}/subtitles/srt`,

  detectSilence: (
    assetId: string,
    opts?: { noise_db?: number; min_duration?: number; padding?: number; min_keep?: number },
  ) =>
    request<SilenceCutPlan>(`/api/media/${assetId}/detect-silence`, {
      method: "POST",
      body: JSON.stringify(opts ?? {}),
    }),

  applyCutPlan: (
    trackId: string,
    mediaAssetId: string,
    keepSegments: Segment[],
    index?: number,
  ) =>
    request<Clip[]>(`/api/tracks/${trackId}/apply-cut-plan`, {
      method: "POST",
      body: JSON.stringify({
        media_asset_id: mediaAssetId,
        keep_segments: keepSegments,
        index: index ?? null,
      }),
    }),

  llmStatus: () =>
    request<{ available: boolean; base_url: string; model: string }>(
      "/api/llm/status",
    ),

  aiEdit: (projectId: string, instruction: string) =>
    request<Job>(`/api/projects/${projectId}/ai-edit`, {
      method: "POST",
      body: JSON.stringify({ instruction }),
    }),

  produce: (projectId: string, instruction: string, targetDurationMinutes: number) =>
    request<Job>(`/api/projects/${projectId}/produce`, {
      method: "POST",
      body: JSON.stringify({
        instruction,
        target_duration_minutes: targetDurationMinutes,
      }),
    }),

  getProduction: (projectId: string) =>
    request<ProductionData>(`/api/projects/${projectId}/production`),

  updateScene: (
    sceneId: string,
    patch: Partial<
      Pick<Scene, "narration" | "visual_type" | "visual_prompt" | "estimated_duration" | "status">
    >,
  ) =>
    request<Scene>(`/api/scenes/${sceneId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  deleteScene: (sceneId: string) =>
    request<{ ok: boolean }>(`/api/scenes/${sceneId}`, { method: "DELETE" }),
};
