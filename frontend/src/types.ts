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
  // "image" joined video/audio when the studio started accepting the
  // user's own photos as scene material.
  kind: "video" | "image" | "audio";
  original_filename: string;
  duration: number;
  width: number | null;
  height: number | null;
  fps: number | null;
  has_audio: boolean;
  video_codec: string | null;
  audio_codec: string | null;
  // Where this file came from: user | web | ai_generated | kairo_clip |
  // kairo_bgm. Absent on rows imported before the material pipeline.
  origin?: string;
  origin_detail?: string;
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
  // Short-form scene design (backend: app/models/production.py). The
  // caption is deliberately separate from the narration.
  purpose: string;
  emotion: string;
  camera: string;
  subtitle_text: string;
  sfx: string;
  transition: string;
  continuity: string;
  asset_source: string;
  // The user's pinned footage; media_asset_id is the rendered clip.
  user_asset_id: string | null;
  user_asset_start: number | null;
  user_asset_end: number | null;
  // Where this scene's picture came from, for the 使用素材 report.
  material_origin: string;
  material_note: string;
  media_asset_id: string | null;
  narration_duration: number | null;
  start_time: number;
  is_hook: boolean;
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
  requested_model: string;
  model_source: string;
  models_loaded: string[];
  connection_status: string;
  error_code: string;
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
  error_code: string;
}

export type ModelSource = "env" | "user" | "auto" | "fallback" | "none";

export interface LLMStatus {
  available: boolean;
  base_url: string;
  model: string | null;
  server_reachable: boolean;
  api_ok: boolean;
  models_loaded: string[];
  configured_model_loaded: boolean;
  can_generate: boolean;
  model_source: ModelSource;
  resolution_reason: string;
  error_code: string;
  ready: boolean;
  diagnosis: Diagnosis | null;
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
  gpu: { names: string[] | null; dedicated: boolean[] | null; vram_label: string[] | null; note?: string };
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

// ---- Settings (design doc sections 12/30-32/38-40) ----

export type AIMode = "auto" | "manual";
export type QualityPreset = "fast" | "standard" | "high" | "ultra" | "custom";
export type PerformanceProfile = "auto" | "speed" | "balanced" | "quality" | "custom";
export type TTSMode = "auto" | "off" | "manual";
export type SubtitlePosition = "top" | "middle" | "bottom";
export type SubtitleStyleT = "outline" | "box" | "plain";

export interface AISettingsT {
  mode: AIMode;
  selected_model: string | null;
}

export interface TTSSettingsT {
  mode: TTSMode;
  selected_voice: string | null;
}

export interface SubtitleSettingsT {
  enabled: boolean;
  font: string;
  size: number;
  position: SubtitlePosition;
  color: string;
  style: SubtitleStyleT;
}

export interface GenerationSettingsT {
  parallelism: number; // 0 = auto
  cache_enabled: boolean;
  default_engine_id: string | null;
}

export interface VideoSettingsT {
  aspect_ratio: string;
  width: number;
  height: number;
  fps: number;
  quality_preset: QualityPreset;
  duration_seconds: number;
}

export interface PerformanceCustomOverrides {
  width: number | null;
  height: number | null;
  fps: number | null;
  num_inference_steps: number | null;
}

export interface PerformanceSettingsT {
  profile: PerformanceProfile;
  custom: PerformanceCustomOverrides | null;
}

export interface TrendSettingsT {
  enabled: boolean;
  region: string;
  interval_minutes: number;
  sources: string[];
  use_in_production: boolean;
  max_signals_per_source: number;
}

export interface LibrarySettingsT {
  auto_download_fonts: boolean;
  prefer_commercial_safe: boolean;
}

export interface RefinementSettingsT {
  enabled: boolean;
  max_iterations: number;
  target_score: number;
  min_gain: number;
}

export interface AppSettings {
  ai: AISettingsT;
  video: VideoSettingsT;
  performance: PerformanceSettingsT;
  tts: TTSSettingsT;
  subtitle: SubtitleSettingsT;
  generation: GenerationSettingsT;
  trends: TrendSettingsT;
  library: LibrarySettingsT;
  refinement: RefinementSettingsT;
}

export interface AppSettingsPatch {
  ai?: Partial<AISettingsT> & { clear_selected_model?: boolean };
  video?: Partial<VideoSettingsT>;
  performance?: Partial<PerformanceSettingsT>;
  tts?: Partial<TTSSettingsT> & { clear_selected_voice?: boolean };
  subtitle?: Partial<SubtitleSettingsT>;
  generation?: Partial<GenerationSettingsT> & { clear_default_engine_id?: boolean };
  trends?: Partial<TrendSettingsT>;
  library?: Partial<LibrarySettingsT>;
  refinement?: Partial<RefinementSettingsT>;
}

export interface TTSVoice {
  id: string;
  name: string;
  culture: string;
  gender: string;
}

export interface TTSVoicesOut {
  available: boolean;
  voices: TTSVoice[];
  note: string;
}

export interface ParallelismWarning {
  level: "recommended" | "caution" | "not_recommended";
  reason: string;
}

// ---- AI model management (design doc sections 3-20) ----

export interface ModelInfo {
  id: string;
  loaded: boolean;
  recommended: boolean;
  catalog_tier_label: string | null;
  is_current: boolean;
}

export interface ModelsListOut {
  connected: boolean;
  base_url: string;
  models: ModelInfo[];
  current_model: string | null;
  current_model_source: string | null;
  diagnosis: Diagnosis | null;
}

export interface SetupCandidate {
  id: string;
  display_name: string;
  purpose: string;
  size_gb: number;
  quant: string;
  tier_label: string;
  required_free_gb: number;
  current_free_gb: number;
  enough_disk_space: boolean;
  estimated_download_minutes_low: number;
  estimated_download_minutes_high: number;
  recommendation_stars: number;
  already_available: boolean;
}

export interface RecommendationOut {
  ram_gb: number;
  gpu_names: string[];
  gpu_dedicated: boolean;
  recommended_tier_label: string;
  reasons: string[];
  recommended_model_id: string | null;
  recommended_model_source: "existing" | "catalog" | "none";
  setup_candidates: SetupCandidate[];
}

export interface EstimateRange {
  low_seconds: number;
  high_seconds: number;
}

export interface EstimateOut {
  planning: EstimateRange;
  generation: EstimateRange;
  total: EstimateRange;
  based_on_history: boolean;
  note: string;
}

export interface VideoSettingWarning {
  level: "recommended" | "caution" | "not_recommended";
  reason: string;
}

// ---- AI Production Studio ----
//
// Mirrors backend/app/services/studio/*. The event stream is the single
// source the progress UI, the activity panel and both logs render from, so
// these shapes are shared rather than each panel inventing its own.

export interface Phase {
  id: string;
  label: string;
  purpose: string;
  skippable: boolean;
}

export type RunStatus =
  | "pending"
  | "running"
  | "pausing"
  | "paused"
  | "stopping"
  | "stopped"
  | "completed"
  | "failed";

export type EventStatus = "running" | "done" | "failed" | "skipped" | "paused" | "info";

export interface ProductionEvent {
  id: string;
  run_id: string;
  seq: number;
  phase: string;
  phase_label: string;
  task: string;
  status: EventStatus;
  level: "user" | "tech";
  scene_id: string | null;
  target: string;
  message: string;
  reason: string;
  next_task: string;
  progress: number;
  model: string;
  error: Diagnosis | null;
  timestamp: string | null;
}

export interface ResearchSource {
  title: string;
  url: string;
  snippet: string;
  fetched: boolean;
}

export interface TrendReport {
  query: string;
  common_patterns: string[];
  differentiation: string[];
  typical_duration_seconds: number | null;
  typical_scene_seconds: number | null;
  hook_patterns: string[];
  subtitle_patterns: string[];
  audio_patterns: string[];
  ending_patterns: string[];
  notes: string;
}

export interface ResearchResult {
  performed: boolean;
  skipped_reason: string;
  queries: string[];
  sources: ResearchSource[];
  trends: TrendReport;
}

export interface ProductionStrategy {
  target: string;
  title: string;
  concept: string;
  hook: string;
  pacing: string;
  scene_seconds_min: number;
  scene_seconds_max: number;
  subtitle_policy: string;
  audio_policy: string;
  bgm_mood: string;
  ending: string;
  differentiation: string;
  emotional_arc: string[];
  visual_style: string;
}

export interface QualityIssue {
  axis: string;
  severity: "info" | "minor" | "major";
  scene_index: number | null;
  detail: string;
  suggestion: string;
  fix: string | null;
  fix_value: number | null;
}

export interface QualityReport {
  score: number;
  axes: Record<string, number>;
  issues: QualityIssue[];
  strengths: string[];
  summary: string;
  checked_by: string;
}

export interface AppliedImprovement {
  scene_index: number | null;
  what: string;
  before: string;
  after: string;
  reason: string;
}

export interface ImprovementReport {
  applied: AppliedImprovement[];
  skipped: string[];
  score_before: number;
  score_after: number;
}

export interface RoleAssignment {
  id: string;
  label: string;
  purpose: string;
  provider: string;
  model: string | null;
  ready: boolean;
  status: string;
  detail: string;
  remedy: string[];
}

export interface LMModel {
  id: string;
  state: "loaded" | "downloaded" | "unknown";
  kind: string;
  quantization: string;
  max_context_length: number | null;
  publisher: string;
  arch: string;
  chat_capable: boolean;
  tier_label: string | null;
  recommended: boolean;
  size_gb: number | null;
  speed_label: string;
}

export interface ModelPlan {
  roles: RoleAssignment[];
  llm_ready: boolean;
  llm_model: string | null;
  llm_model_source: string;
  llm_error_code: string;
  available_models: LMModel[];
  blocking: string[];
  warnings: string[];
}

export interface ProductionRun {
  id: string;
  project_id: string;
  mode: "full_auto" | "co_creation";
  status: RunStatus;
  phase: string;
  phase_label: string;
  task: string;
  progress: number;
  instruction: string;
  target_duration_seconds: number;
  orientation: string;
  material_mode: MaterialMode;
  selected_asset_ids: string[];
  material_plan: MaterialPlan | null;
  completed_phases: string[];
  resume_phase: string | null;
  render_job_id: string | null;
  output_path: string | null;
  error: string | null;
  error_detail: Diagnosis | null;
  research: ResearchResult | null;
  strategy: ProductionStrategy | null;
  quality: QualityReport | null;
  improvement: ImprovementReport | null;
  model_plan: ModelPlan | null;
  // 動画制作エージェント: what the run knew, chose and thought of the result.
  // Null on runs produced before the agent existed, and on any run that has
  // not reached the phase that fills the field.
  trend: TrendContext | null;
  assets: AssetDecisions | null;
  // The 編集方針 this run was cut to, decided before anything was written.
  // Null on a run made before the edit director existed, which the panel
  // reports as such rather than as an empty policy.
  direction: EditDirective | null;
  transitions: TransitionPlan | null;
  subtitle_design: SubtitleDesignPlan | null;
  platform: string;
  edit_style: string;
  review: VideoReview | null;
  report: ProductionReport | null;
  variants: VariantResult | null;
  iteration: number;
  best_score: number | null;
  scene_count: number;
  created_at: string | null;
  updated_at: string | null;
}


// ---------------------------------------------------------------- material
//
// The user's own photos and videos, what Kairo worked out about them, and
// where they end up in the finished video. Mirrors backend/app/schemas/
// material.py field for field - the two are one contract, not two.

export type MaterialOrigin = "user" | "local" | "web" | "ai_generated" | "procedural";

export const MATERIAL_ORIGIN_LABELS: Record<MaterialOrigin, string> = {
  user: "ユーザー素材",
  local: "ローカル素材",
  web: "Web素材",
  ai_generated: "AI生成",
  procedural: "抽象背景",
};

export type MaterialMode = "ai_auto" | "use_all" | "selected";

export interface UsableRange {
  start: number;
  end: number;
  reason: string;
}

export interface MaterialAnalysis {
  asset_id: string;
  kind: string;
  tags: string[];
  description: string;
  scene_summary: string;
  width: number | null;
  height: number | null;
  orientation: string;
  duration: number;
  fps: number | null;
  has_audio: boolean;
  brightness: number | null;
  motion: number | null;
  dominant_colors: string[];
  usable: UsableRange;
  // "vision_ai" | "metadata" | "metadata+filename" - shown verbatim so the
  // user is never told an AI looked at a photo when none did.
  analyzed_by: string;
  notes: string;
}

export interface PlannedUse {
  scene_number: number;
  start_time: number;
  duration: number;
  reason: string;
}

export interface Material {
  id: string;
  project_id: string;
  kind: "video" | "image" | "audio";
  original_filename: string;
  duration: number;
  width: number | null;
  height: number | null;
  fps: number | null;
  has_audio: boolean;
  video_codec: string | null;
  audio_codec: string | null;
  origin: string;
  origin_detail: string;
  analysis_status: "pending" | "done" | "failed" | "skipped";
  analysis_error: string | null;
  analysis: MaterialAnalysis | null;
  planned_use: PlannedUse | null;
  imported_at: string | null;
}

export interface MaterialUploadError {
  filename: string;
  message: string;
  cause: string;
  hint: string;
  raw: string;
}

export interface MaterialAssignment {
  scene_index: number;
  scene_number: number;
  subtitle: string;
  visual_prompt: string;
  duration: number;
  start_time: number;
  origin: MaterialOrigin;
  asset_id: string | null;
  filename: string;
  source_start: number | null;
  source_end: number | null;
  reason: string;
  matched_tags: string[];
  score: number;
}

export interface MaterialShortage {
  scene_index: number;
  scene_number: number;
  need: string;
  keywords: string[];
  fill_method: MaterialOrigin;
  fill_reason: string;
}

export interface MaterialPlan {
  mode: MaterialMode;
  user_photo_count: number;
  user_video_count: number;
  used_photo_count: number;
  used_video_count: number;
  unused_asset_ids: string[];
  assignments: MaterialAssignment[];
  shortages: MaterialShortage[];
  fill_counts: Record<string, number>;
  available_fill_sources: string[];
  notes: string[];
  provisional: boolean;
  estimated_scene_count: number;
}

export interface MaterialUsageEntry {
  scene_index: number;
  scene_number: number;
  start: number;
  end: number;
  origin: MaterialOrigin;
  origin_label: string;
  asset_id: string | null;
  filename: string;
  subtitle: string;
  note: string;
  source_start: number | null;
  source_end: number | null;
}

export interface MaterialUsageReport {
  entries: MaterialUsageEntry[];
  total_duration: number;
  counts: Record<string, number>;
}

export interface ChangePreview {
  what: string;
  before: string;
  after: string;
  reason: string;
}

export interface ChangeProposal {
  id: string;
  summary: string;
  reason: string;
  status: "pending" | "applied" | "cancelled" | "undone" | "failed";
  preview: ChangePreview[];
  created_at: string | null;
}

export interface ChatMessageT {
  id: string;
  role: "user" | "assistant";
  content: string;
  proposal: ChangeProposal | null;
  created_at: string | null;
}

export interface QuickAction {
  id: string;
  label: string;
  instruction: string;
}

export interface ApplyResult {
  applied: string[];
  skipped: string[];
  rebuilt_scenes: number[];
  total_seconds: number;
}

/* -------------------------------------------------------------------------
 * 動画制作エージェント: Trend Intelligence, the Creative Asset Library,
 * the AI Video Reviewer, and the connected-services view.
 * ---------------------------------------------------------------------- */

export interface TrendSignal {
  id: string;
  platform: string;
  keyword: string;
  category: string;
  category_label: string;
  region: string;
  score: number;
  growth_rate: number;
  observation_count: number;
  observed_at: string | null;
  expires_at: string | null;
  source: string;
  source_url: string;
  metadata: Record<string, unknown>;
  /** Score after time decay - what the planner actually ranks on. */
  effective_score: number;
  stale: boolean;
}

export interface GenreProfileData {
  genre: string;
  label: string;
  duration_seconds: number | null;
  scene_seconds: number | null;
  hook_seconds: number | null;
  hook_patterns: string[];
  opening_patterns: string[];
  cut_tempo: string;
  subtitle_density: string;
  subtitle_position: string;
  subtitle_style: string;
  font_style: string[];
  bgm_mood: string;
  bgm_bpm_range: number[];
  sfx_usage: string[];
  transitions: string[];
  title_patterns: string[];
  cta_patterns: string[];
  hashtags: string[];
  notes: string;
  evidence: string[];
}

export interface TrendSourceStatus {
  id: string;
  label: string;
  kind: string;
  enabled: boolean;
  configured: boolean;
  requires_key: boolean;
  key_env: string;
  endpoint: string;
  terms_url: string;
  note: string;
  last_ok: string | null;
  last_error: string;
  last_count: number;
}

export interface TrendOverview {
  enabled: boolean;
  region: string;
  interval_minutes: number;
  last_run_at: string | null;
  last_run_status: string;
  next_run_at: string | null;
  total_signals: number;
  fresh_signals: number;
  sources: TrendSourceStatus[];
  top: TrendSignal[];
  by_category: Record<string, number>;
}

export interface TrendContext {
  used: boolean;
  reason: string;
  genre: string;
  genre_label: string;
  region: string;
  signals: TrendSignal[];
  profile: GenreProfileData | null;
  /** "llm" = analysed from collected signals; "defaults" = built-in convention. */
  profile_source: string;
  collected_at: string | null;
}

export interface GenreBreakdown {
  genre: string;
  label: string;
  count: number;
  signals: TrendSignal[];
  profile: GenreProfileData;
  derived_from: string;
  sample_size: number;
  updated_at: string | null;
}

export interface LicenseRef {
  id: string;
  name: string;
  status: string;
  status_label: string;
  url: string;
  attribution_required: boolean;
  attribution: string;
  commercial_use: boolean;
}

export interface LicenseInfo {
  id: string;
  name: string;
  url: string;
  status: string;
  status_label: string;
  commercial_use: boolean;
  attribution_required: boolean;
  redistribution: boolean;
  summary: string;
}

export interface LibraryAsset {
  id: string;
  kind: "font" | "music" | "sfx";
  name: string;
  family: string;
  path: string;
  is_system: boolean;
  available: boolean;
  category: string;
  mood: string;
  source: string;
  source_url: string;
  license: LicenseRef & { file: string; summary: string };
  auto_usable: boolean;
  languages: string[];
  styles: string[];
  genres: string[];
  weight: number;
  readability: number | null;
  supports_japanese: boolean;
  supports_latin: boolean;
  duration: number | null;
  bpm: number | null;
  loudness_lufs: number | null;
  analysis_status: string;
  analysis_error: string;
  notes: string;
}

export interface LibraryKindSummary {
  total: number;
  available: number;
  auto_usable: number;
  by_status: Record<string, number>;
}

export interface LibraryOverview {
  summary: Record<string, LibraryKindSummary>;
  roots: { fonts: string; music: string; sfx: string };
  settings: { auto_download_fonts: boolean; prefer_commercial_safe: boolean };
  licenses: LicenseInfo[];
  status_labels: Record<string, string>;
  sfx_import_only: string[];
}

export interface FontCatalogEntry {
  id: string;
  family: string;
  languages: string[];
  license_id: string;
  note: string;
  variable_only: boolean;
  source: string;
  source_url: string;
  installed: boolean;
}

export interface AssetChoice {
  kind: string;
  found: boolean;
  asset_id: string;
  name: string;
  family: string;
  path: string;
  category: string;
  source: string;
  source_url: string;
  reason: string;
  reasons: string[];
  score: number;
  license: LicenseRef;
  bpm: number | null;
  duration: number | null;
  loudness_lufs: number | null;
  considered: number;
  rejected_for_license: number;
  unavailable_reason: string;
}

export interface SfxPlacement {
  at: number;
  category: string;
  asset_id: string;
  name: string;
  trigger: string;
  scene_index: number | null;
  gain: number;
  reason: string;
}

export interface BeatSyncResult {
  applied: boolean;
  reason: string;
  bpm: number | null;
  bpm_source: string;
  beat_seconds: number | null;
  beats_per_cut: number;
  adjusted_scenes: number;
  total_drift_seconds: number;
  cut_points: number[];
}

export interface SubtitleDecision {
  font: string;
  size: number;
  position: string;
  style: string;
  color: string;
  max_chars_per_line: number;
  reason: string;
  from_trend_profile: boolean;
}

/** One face the font ranking considered, and how it scored. */
export interface FontCandidate {
  asset_id: string;
  name: string;
  family: string;
  score: number;
  reasons: string[];
  penalties: string[];
  recently_used: boolean;
}

/**
 * The field the caption font was chosen against.
 *
 * Shown alongside the winner because "why this font" is only answerable
 * next to "instead of which others" - and because `profiled: false` means
 * the ranking fell back to legibility alone, which the user needs to be
 * told rather than left to infer from a font that never changes.
 */
export interface FontRanking {
  considered: number;
  eligible: number;
  rejected_for_license: number;
  below_readability_floor: number;
  readability_floor: number;
  caption_load: number;
  size_pressure: number;
  profiled: boolean;
  recent_families: string[];
  candidates: FontCandidate[];
}

export interface AssetDecisions {
  genre: string;
  genre_label: string;
  font: AssetChoice | null;
  font_ranking: FontRanking | null;
  music: AssetChoice | null;
  sfx: SfxPlacement[];
  sfx_assets: AssetChoice[];
  subtitle: SubtitleDecision | null;
  beat_sync: BeatSyncResult;
  notes: string[];
}

export interface AxisScore {
  axis: string;
  label: string;
  score: number;
  /** measured = read from the file, planned = from the scene design, ai = model. */
  basis: string;
  detail: string;
}

export interface ReviewFinding {
  axis: string;
  severity: "info" | "minor" | "major";
  problem: string;
  cause: string;
  suggestion: string;
  fix: string | null;
  fix_value: number | null;
  scene_index: number | null;
}

export interface VideoReview {
  performed: boolean;
  iteration: number;
  overall_score: number;
  axes: AxisScore[];
  findings: ReviewFinding[];
  strengths: string[];
  summary: string;
  measured: Record<string, unknown>;
  reviewed_by: string;
  output_path: string;
  error: string;
}

export interface IterationRecord {
  iteration: number;
  score: number;
  changes: string[];
  output_path: string;
  adopted: boolean;
  note: string;
}

export interface VariantRecord {
  id: string;
  label: string;
  strategy_note: string;
  score: number;
  output_path: string;
  best: boolean;
}

export interface VariantResult {
  variants: VariantRecord[];
  best_id: string;
  error: string;
}

export interface VariantSpec {
  id: string;
  label: string;
  note: string;
  tempo_scale: number;
}

export interface ProductionReport {
  project_id: string;
  project_name: string;
  run_id: string;
  title: string;
  genre: string;
  genre_label: string;
  instruction: string;
  duration_seconds: number;
  orientation: string;
  resolution: string;
  llm_provider: string;
  llm_endpoint: string;
  llm_model: string;
  transcription_engine: string;
  tts_engine: string;
  rendering_engine: string;
  trend_used: boolean;
  trend_reason: string;
  trend_sources: string[];
  trend_keywords: string[];
  genre_profile_source: string;
  font: string;
  font_license: string;
  music: string;
  music_license: string;
  sfx: string[];
  attribution: string[];
  review: VideoReview | null;
  iterations: IterationRecord[];
  final_score: number;
  output_path: string;
  assets_used_path: string;
  generated_at: string;
}

export interface ConnectedService {
  id: string;
  category: string;
  label: string;
  purpose: string;
  connection: string;
  endpoint: string;
  model: string;
  auth: string;
  cost: string;
  state: "connected" | "not_connected" | "not_configured" | "unavailable" | "disabled";
  detail: string;
  remedy: string;
  files: string[];
  terms_url: string;
}

export interface ConnectedServices {
  services: ConnectedService[];
  by_category: Record<string, ConnectedService[]>;
  counts: { connected: number; total: number };
  note: string;
}

/* ---------------------------------------------------------------- 編集方針
 *
 * The AI edit director's output (backend: app/schemas/edit_style.py). This
 * is what the "今回のKairo編集方針" panel renders: every decision the agent
 * made before editing started, each with the reason it was made, so the
 * judgements are inspectable rather than a black box.
 */

export type EditStyleId =
  | "vlog"
  | "travel"
  | "cinematic"
  | "food"
  | "tutorial"
  | "entertainment"
  | "shorts"
  | "documentary"
  | "luxury"
  | "casual";

export type PlatformId =
  | "youtube_shorts"
  | "tiktok"
  | "instagram_reels"
  | "youtube_landscape"
  | "generic";

export type TransitionId =
  | "cut"
  | "fade"
  | "dissolve"
  | "dip_to_black"
  | "slide_left"
  | "slide_right"
  | "slide_up"
  | "push_left"
  | "zoom"
  | "match_cut";

export interface ColorGrade {
  id: string;
  label: string;
  brightness: number;
  contrast: number;
  saturation: number;
  gamma: number;
  shadow_blue: number;
  highlight_red: number;
  strength: number;
  reason: string;
}

export interface TransitionPolicy {
  default: TransitionId;
  allowed: TransitionId[];
  max_ratio: number;
  duration: number;
  strong: TransitionId;
  reason: string;
}

export interface SubtitlePolicy {
  density: "minimal" | "low" | "medium" | "high";
  coverage: number;
  position: "top" | "middle" | "bottom";
  style: "outline" | "box" | "plain";
  size_scale: number;
  max_lines: number;
  emphasis: boolean;
  emphasis_scale: number;
  animation: "none" | "fade" | "pop" | "slide_up";
  letter_spacing: number;
  line_spacing: number;
  reason: string;
}

export interface FontDirection {
  wanted: string[];
  avoid: string[];
  luxury: number;
  casual: number;
  cinematic: number;
  impact: number;
  weight_min: number;
  weight_max: number;
  min_readability: number;
  needs_japanese: boolean;
  needs_latin: boolean;
  reason: string;
}

export interface PhotoMotionPolicy {
  intensity: number;
  prefer: string[];
  subject_safe: boolean;
  reason: string;
}

export interface AudioPolicy {
  normalize: boolean;
  target_lufs: number;
  bgm_mood: string;
  bgm_bpm_range: number[];
  bgm_volume: number;
  duck_narration: boolean;
  keep_ambience: number;
  denoise: boolean;
  sfx_per_minute: number;
  narration_rate: number;
  narration_style: string;
  reason: string;
}

export interface StoryBeat {
  id: string;
  label: string;
  purpose: string;
  share: number;
}

export interface EditDirective {
  style: EditStyleId;
  style_label: string;
  genre: string;
  genre_label: string;
  platform: PlatformId;
  platform_label: string;
  audience: string;
  concept: string;
  duration_seconds: number;
  orientation: "vertical" | "horizontal" | "square";
  width: number;
  height: number;
  mood: string;
  tempo: "slow" | "medium" | "fast";
  scene_seconds: number;
  scene_seconds_min: number;
  scene_seconds_max: number;
  energy_curve: string[];
  story: StoryBeat[];
  hook_seconds: number;
  hook_direction: string;
  ending_direction: string;
  cta: string;
  subtitle: SubtitlePolicy;
  font: FontDirection;
  transitions: TransitionPolicy;
  photo_motion: PhotoMotionPolicy;
  color: ColorGrade;
  audio: AudioPolicy;
  /** "defaults" | "defaults+profile" | "defaults+profile+ai" - how much
   *  evidence actually went into the directive. Shown so a defaults-only
   *  policy is never presented as an AI judgement. */
  decided_by: string;
  notes: string[];
  material_summary: string;
  ai_note: string;
}

export interface TransitionChoice {
  index: number;
  transition: TransitionId;
  label: string;
  duration: number;
  reason: string;
  reason_label: string;
  detail: string;
}

export interface TransitionPlan {
  choices: TransitionChoice[];
  non_cut_count: number;
  boundary_count: number;
  summary: string;
}

export interface CueDesign {
  index: number;
  text: string;
  start: number;
  end: number;
  size_scale: number;
  bold: boolean;
  position: "top" | "middle" | "bottom";
  style: "outline" | "box" | "plain";
  color: string;
  animation: "none" | "fade" | "pop" | "slide_up";
  letter_spacing: number;
  line_spacing: number;
  emphasis: string[];
  reason: string;
}

export interface SubtitleDesignPlan {
  cues: CueDesign[];
  dropped: number;
  summary: string;
}

export interface EditStyleOption {
  id: EditStyleId;
  label: string;
  description: string;
  tempo: string;
  scene_seconds: number;
  subtitle_density: string;
  color_grade: string;
  bgm_mood: string;
  genres: string[];
}

export interface PlatformOption {
  id: PlatformId;
  label: string;
  orientation: string;
  width: number;
  height: number;
  ideal_seconds: number;
  max_seconds: number;
  notes: string[];
}

export interface FontStarterItem {
  id: string;
  family: string;
  purpose: string;
  installed: boolean;
  license_id: string;
  variable_only: boolean;
}

export interface FontStarterSet {
  items: FontStarterItem[];
  installed_count: number;
  total: number;
  missing_ids: string[];
  license: string;
  source: string;
}

/**
 * Kairo Style Memory (backend: app/services/studio/style_memory.py).
 *
 * `preferences` is what the user changed by hand and is applied to the next
 * production. `tendencies` and `recent_fonts` are what Kairo itself chose,
 * kept only so the next video does not repeat them - never treated as a
 * preference.
 */
export interface StyleMemoryPreference {
  value: string | number;
  source: string;
  at: string;
  label: string;
}

export interface StyleMemoryTally {
  value: string;
  count: number;
}

export interface StyleMemory {
  enabled: boolean;
  path: string;
  exists: boolean;
  production_count: number;
  updated_at: string | null;
  preferences: Record<string, StyleMemoryPreference>;
  recent_fonts: string[];
  tendencies: {
    font: StyleMemoryTally[];
    edit_style: StyleMemoryTally[];
    color_grade: StyleMemoryTally[];
    music: StyleMemoryTally[];
  };
}
