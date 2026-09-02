import type {
  AppSettings,
  AppSettingsPatch,
  Clip,
  EngineCapabilities,
  EstimateOut,
  Generation,
  Job,
  LLMStatus,
  MediaAsset,
  ModelsListOut,
  Project,
  ProductionData,
  RecommendationOut,
  Scene,
  Segment,
  SilenceCutPlan,
  ParallelismWarning,
  SubtitleCue,
  SystemInfo,
  Timeline,
  TTSVoicesOut,
  VideoSettingWarning,
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

  updateProject: (
    id: string,
    patch: Partial<Pick<Project, "name" | "fps" | "width" | "height">>,
  ) =>
    request<Project>(`/api/projects/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  deleteProject: (id: string) =>
    request<{ ok: boolean }>(`/api/projects/${id}`, { method: "DELETE" }),

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

  startRender: (projectId: string, burnSubtitles = false, crf = 18) =>
    request<Job>(
      `/api/projects/${projectId}/render?burn_subtitles=${burnSubtitles}&crf=${crf}`,
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

  llmStatus: () => request<LLMStatus>("/api/llm/status"),

  getJobLog: (jobId: string) =>
    request<{ log: string }>(`/api/jobs/${jobId}/log`).then((r) => r.log),

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

  regenerateScene: (sceneId: string) =>
    request<Job>(`/api/scenes/${sceneId}/regenerate`, { method: "POST" }),

  listGenerationEngines: () =>
    request<EngineCapabilities[]>("/api/generation-engines"),

  generateImageToVideo: (
    projectId: string,
    image: File,
    opts: {
      prompt?: string;
      engineId?: string;
      width?: number;
      height?: number;
      numFrames?: number;
      numInferenceSteps?: number;
      fps?: number;
      seed?: number;
    } = {},
  ) => {
    const form = new FormData();
    form.append("image", image);
    if (opts.prompt) form.append("prompt", opts.prompt);
    if (opts.engineId) form.append("engine_id", opts.engineId);
    if (opts.width) form.append("width", String(opts.width));
    if (opts.height) form.append("height", String(opts.height));
    if (opts.numFrames) form.append("num_frames", String(opts.numFrames));
    if (opts.numInferenceSteps)
      form.append("num_inference_steps", String(opts.numInferenceSteps));
    if (opts.fps) form.append("fps", String(opts.fps));
    if (opts.seed !== undefined) form.append("seed", String(opts.seed));
    return request<Job>(`/api/projects/${projectId}/generate/image-to-video`, {
      method: "POST",
      body: form,
    });
  },

  listGenerations: (projectId: string) =>
    request<Generation[]>(`/api/projects/${projectId}/generations`),

  getSystemInfo: () => request<SystemInfo>("/api/system/info"),

  getSettings: () => request<AppSettings>("/api/settings"),

  updateSettings: (patch: AppSettingsPatch) =>
    request<AppSettings>("/api/settings", { method: "PUT", body: JSON.stringify(patch) }),

  resetSettings: () => request<AppSettings>("/api/settings/reset", { method: "POST" }),

  getAiModels: () => request<ModelsListOut>("/api/ai/models"),

  getAiRecommendation: () => request<RecommendationOut>("/api/ai/recommendation"),

  checkVideoSetting: (width: number, height: number, fps: number) =>
    request<VideoSettingWarning>(
      `/api/ai/video-setting-check?width=${width}&height=${height}&fps=${fps}`,
    ),

  getEstimate: (durationSeconds: number, qualityPreset: string) =>
    request<EstimateOut>(
      `/api/ai/estimate?duration_seconds=${durationSeconds}&quality_preset=${qualityPreset}`,
    ),

  checkParallelism: (value: number) =>
    request<ParallelismWarning>(`/api/ai/parallelism-check?value=${value}`),

  getTtsVoices: () => request<TTSVoicesOut>("/api/ai/tts-voices"),

  ttsPreview: async (text: string, voiceId: string | null) => {
    const res = await fetch(`${API_BASE}/api/ai/tts-preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, voice_id: voiceId }),
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(detail.detail ?? `Request failed: ${res.status}`);
    }
    return res.blob();
  },
};
