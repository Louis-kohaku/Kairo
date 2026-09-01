export interface Project {
  id: string;
  name: string;
  fps: number;
  width: number;
  height: number;
  created_at: string;
  updated_at: string;
}

export interface MediaAsset {
  id: string;
  project_id: string;
  kind: "video" | "audio";
  original_filename: string;
  duration: number;
  width: number | null;
  height: number | null;
  fps: number | null;
  has_audio: boolean;
  video_codec: string | null;
  audio_codec: string | null;
  imported_at: string;
}

export interface Clip {
  id: string;
  track_id: string;
  media_asset_id: string;
  order_index: number;
  in_point: number;
  out_point: number;
  volume: number;
}

export interface Track {
  id: string;
  project_id: string;
  type: "video" | "audio";
  name: string;
  order_index: number;
  clips: Clip[];
}

export interface Timeline {
  tracks: Track[];
  total_duration: number;
}

export interface SubtitleCue {
  id: string;
  project_id: string;
  order_index: number;
  start: number;
  end: number;
  text: string;
}

export interface Segment {
  start: number;
  end: number;
}

export interface SilenceCutPlan {
  duration: number;
  keep_segments: Segment[];
  silence_segments: Segment[];
}

export type VisualType =
  | "ai_video"
  | "ai_image"
  | "photo"
  | "diagram"
  | "chart"
  | "map"
  | "text_animation"
  | "existing_video"
  | "existing_image"
  | "screen_recording";

export const VISUAL_TYPE_LABELS: Record<VisualType, string> = {
  ai_video: "AI動画",
  ai_image: "AI画像",
  photo: "写真",
  diagram: "図解",
  chart: "チャート",
  map: "地図",
  text_animation: "テキストアニメーション",
  existing_video: "既存動画",
  existing_image: "既存画像",
  screen_recording: "画面録画",
};

export interface Scene {
  id: string;
  chapter_id: string;
  project_id: string;
  order_index: number;
  narration: string;
  visual_type: VisualType;
  visual_prompt: string;
  estimated_duration: number;
  status: string;
}

export interface Chapter {
  id: string;
  project_id: string;
  order_index: number;
  title: string;
  summary: string;
  scenes: Scene[];
}

export interface ProductionSpec {
  instruction: string;
  target_duration_minutes: number;
  title: string;
  target_audience: string;
  tone: string;
}

export interface ProductionData {
  spec: ProductionSpec | null;
  chapters: Chapter[];
}

export interface EngineCapabilities {
  id: string;
  display_name: string;
  supports_text_to_video: boolean;
  supports_image_to_video: boolean;
  supports_video_to_video: boolean;
  prompt_conditioned: boolean;
  approx_download_gb: number;
  min_ram_gb: number;
  recommended_ram_gb: number;
  license: string;
  commercial_use: boolean;
  notes: string;
  is_model_downloaded: boolean;
  status: "ready" | "not_downloaded" | "not_recommended";
  status_reason: string;
  estimate_low_seconds: number | null;
  estimate_high_seconds: number | null;
}

export interface Generation {
  id: string;
  project_id: string;
  kind: string;
  engine_id: string;
  prompt: string;
  status: "pending" | "running" | "completed" | "failed";
  job_id: string | null;
  output_media_asset_id: string | null;
  elapsed_seconds: number | null;
  error: string | null;
  error_detail: string | null;
  created_at: string;
  updated_at: string;
}

export type DiagnosisCategory =
  | "ai_provider"
  | "model"
  | "api"
  | "network"
  | "resource"
  | "memory"
  | "ffmpeg"
  | "input_material"
  | "configuration"
  | "unknown";

export interface AIContext {
  provider: string;
  model: string;
  task: string;
  operation: string;
  endpoint: string;
  model_status: string;
}

export interface Diagnosis {
  summary: string;
  cause_known: boolean;
  cause: string;
  category: DiagnosisCategory;
  facts: string[];
  candidates: string[];
  suggestions: { label: string; action: string }[];
  ai_context: AIContext | null;
  step: string | null;
  retryable: boolean;
  raw_error: string;
}

export interface LLMStatus {
  available: boolean;
  base_url: string;
  model: string;
  server_reachable: boolean;
  api_ok: boolean;
  models_loaded: string[];
  configured_model_loaded: boolean;
  can_generate: boolean;
}

export interface CapabilityRating {
  label: string;
  level: "green" | "yellow" | "orange" | "red";
  reason: string;
}

export interface SystemInfo {
  cpu: { name: string; physical_cores: number | null; logical_cores: number | null };
  ram: { total_gb: number; available_gb: number; used_percent: number };
  disk: { total_gb: number; free_gb: number; data_root: string };
  gpu: { names: string[] | null; note?: string };
  ffmpeg: { available: boolean; path: string | null; version: string | null };
  os: { name: string; version: string; release: string };
  ai_runtime: {
    python_version: string;
    torch_installed: boolean;
    torch_version?: string;
    cuda_available: boolean;
    mps_available: boolean;
    xpu_available: boolean;
    openvino_installed: boolean;
    active_backends: string[];
    whisper_installed: boolean;
  };
  capabilities: CapabilityRating[];
  video_generation_engines: {
    id: string;
    display_name: string;
    commercial_use: boolean;
    notes: string;
  }[];
  ai_pipeline: {
    id: string;
    label: string;
    provider: string;
    model: string | null;
    ready: boolean;
    detail: string;
  }[];
}

export type JobStatus = "pending" | "running" | "completed" | "failed";

export interface Job {
  id: string;
  project_id: string;
  type: string;
  status: JobStatus;
  progress: number;
  message: string;
  error: string | null;
  error_detail: string | null;
  step: string | null;
  output_path: string | null;
  created_at: string;
  updated_at: string;
}
