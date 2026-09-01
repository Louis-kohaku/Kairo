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

export type JobStatus = "pending" | "running" | "completed" | "failed";

export interface Job {
  id: string;
  project_id: string;
  type: string;
  status: JobStatus;
  progress: number;
  message: string;
  error: string | null;
  output_path: string | null;
  created_at: string;
  updated_at: string;
}
