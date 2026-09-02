import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type {
  MediaAsset,
  Project,
  ProductionData,
  QualityPreset,
  SubtitleCue,
  SystemInfo,
  Timeline as TimelineData,
} from "../types";
import MediaBin from "../components/MediaBin";
import PreviewPlayer from "../components/PreviewPlayer";
import Timeline from "../components/Timeline";
import ClipInspector from "../components/ClipInspector";
import SubtitlePanel from "../components/SubtitlePanel";
import CutPlanPanel from "../components/CutPlanPanel";
import AIEditPanel from "../components/AIEditPanel";
import ProductionPanel from "../components/ProductionPanel";
import GenerationPanel from "../components/GenerationPanel";
import SystemInfoPanel from "../components/SystemInfoPanel";
import SystemEnvSummary from "../components/SystemEnvSummary";
import VideoSettingsPanel from "../components/VideoSettingsPanel";
import CreateVideoCTA from "../components/CreateVideoCTA";
import RenderScreen from "../components/RenderScreen";
import CompletionScreen from "../components/CompletionScreen";
import ReRenderBanner from "../components/ReRenderBanner";
import StepBar from "../components/StepBar";
import LlmStatusBadge from "../components/LlmStatusBadge";
import { useJobPolling } from "../hooks/useJobPolling";
import { formatTime } from "../utils/format";
import { QUALITY_CRF } from "../utils/renderEstimate";

type View = "scenes" | "assets" | "edit" | "preview" | "export" | "done";

const STEPS = [
  { id: "plan", label: "企画" },
  { id: "scenes", label: "シーン" },
  { id: "assets", label: "素材" },
  { id: "edit", label: "編集" },
  { id: "preview", label: "プレビュー" },
  { id: "export", label: "書き出し" },
  { id: "done", label: "完成" },
];

function contentHash(timeline: TimelineData | null, cues: SubtitleCue[]): string {
  const tracksPart = (timeline?.tracks ?? []).map((t) => ({
    id: t.id,
    clips: t.clips.map((c) => `${c.media_asset_id}:${c.in_point}:${c.out_point}:${c.volume}`),
  }));
  const cuesPart = cues.map((c) => `${c.start}:${c.end}:${c.text}`);
  return JSON.stringify({ tracksPart, cuesPart });
}

export default function Editor({
  projectId,
  onBack,
  onOpenSettings,
  onOpenStudio,
}: {
  projectId: string;
  onBack: () => void;
  onOpenSettings?: () => void;
  onOpenStudio?: () => void;
}) {
  const [view, setView] = useState<View>("edit");
  const [initializedView, setInitializedView] = useState(false);
  const [project, setProject] = useState<Project | null>(null);
  const [assets, setAssets] = useState<MediaAsset[]>([]);
  const [timeline, setTimeline] = useState<TimelineData | null>(null);
  const [playhead, setPlayhead] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [seekNonce, setSeekNonce] = useState(0);
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [subtitleCues, setSubtitleCues] = useState<SubtitleCue[]>([]);
  const [cutPlanAsset, setCutPlanAsset] = useState<MediaAsset | null>(null);
  const [subtitleRefreshToken, setSubtitleRefreshToken] = useState(0);
  const [production, setProduction] = useState<ProductionData | null>(null);
  const [quality, setQuality] = useState<QualityPreset>("standard");
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(null);
  const [showSystemModal, setShowSystemModal] = useState(false);
  const [burnSubtitles, setBurnSubtitles] = useState(false);
  const [lastSavedAt, setLastSavedAt] = useState<number | null>(null);
  const [lastRenderHash, setLastRenderHash] = useState<string | null>(
    () => window.localStorage.getItem(`kairo:lastRenderHash:${projectId}`),
  );

  const { job: renderJob, track: trackRenderJob, isBusy: renderBusy } = useJobPolling();
  const didAutoAdvanceRef = useRef(false);

  const assetsById = useMemo(() => {
    const map: Record<string, MediaAsset> = {};
    for (const a of assets) map[a.id] = a;
    return map;
  }, [assets]);

  const videoTrack = timeline?.tracks.find((t) => t.type === "video") ?? null;
  const bgmTrack = timeline?.tracks.find((t) => t.type === "audio") ?? null;

  const refreshTimeline = () =>
    api
      .getTimeline(projectId)
      .then((t) => {
        setTimeline(t);
        setLastSavedAt(Date.now());
      })
      .catch((e) => setError(String(e)));

  const refreshProduction = () =>
    api.getProduction(projectId).then(setProduction).catch(() => {});

  useEffect(() => {
    api.getProject(projectId).then(setProject).catch((e) => setError(String(e)));
    api.listMedia(projectId).then(setAssets).catch((e) => setError(String(e)));
    api.getSystemInfo().then(setSystemInfo).catch(() => {});
    api
      .getSettings()
      .then((s) => setBurnSubtitles(s.subtitle.enabled))
      .catch(() => {});
    refreshTimeline();
    refreshProduction();
    api
      .listJobs(projectId)
      .then((jobs) => {
        const latest = jobs.find((j) => j.type === "render");
        if (latest) trackRenderJob(latest);
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // Pick a sensible starting screen from real project state, once, right
  // after the first load resolves - never overrides the user's own
  // navigation on later re-renders.
  useEffect(() => {
    if (initializedView || production === null || timeline === null) return;
    const totalScenes = production.chapters.reduce((n, c) => n + c.scenes.length, 0);
    const clipCount = videoTrack?.clips.length ?? 0;
    if (!production.spec) setView("scenes");
    else if (clipCount === 0) setView(totalScenes > 0 ? "assets" : "scenes");
    else setView("edit");
    setInitializedView(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [production, timeline, initializedView]);

  useEffect(() => {
    if (renderJob?.status === "completed" && !didAutoAdvanceRef.current) {
      didAutoAdvanceRef.current = true;
      const hash = contentHash(timeline, subtitleCues);
      window.localStorage.setItem(`kairo:lastRenderHash:${projectId}`, hash);
      setLastRenderHash(hash);
      setView("done");
    }
    if (renderJob && renderJob.status !== "completed") {
      didAutoAdvanceRef.current = false;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [renderJob?.status]);

  const findTrackIdForClip = (clipId: string): string | null => {
    for (const track of timeline?.tracks ?? []) {
      if (track.clips.some((c) => c.id === clipId)) return track.id;
    }
    return null;
  };

  const selectedClip =
    (timeline?.tracks ?? [])
      .flatMap((t) => t.clips)
      .find((c) => c.id === selectedClipId) ?? null;
  const selectedAsset = selectedClip
    ? assetsById[selectedClip.media_asset_id] ?? null
    : null;

  const currentSubtitleText =
    subtitleCues.find((c) => playhead >= c.start && playhead < c.end)?.text ?? null;

  const handleAddToTrack = async (
    assetId: string,
    trackType: "video" | "audio",
  ) => {
    const track = trackType === "video" ? videoTrack : bgmTrack;
    if (!track) return;
    try {
      await api.addClip(track.id, assetId);
      await refreshTimeline();
    } catch (e) {
      setError(String(e));
    }
  };

  const handleDropAsset = async (
    trackId: string,
    assetId: string,
    index: number,
  ) => {
    try {
      await api.addClip(trackId, assetId, 0, undefined, index);
      await refreshTimeline();
    } catch (e) {
      setError(String(e));
    }
  };

  const handleSeek = (time: number) => {
    setPlayhead(time);
    setSeekNonce((n) => n + 1);
  };

  const handleDeleteClip = async (clipId: string) => {
    try {
      await api.deleteClip(clipId);
      if (clipId === selectedClipId) setSelectedClipId(null);
      await refreshTimeline();
    } catch (e) {
      setError(String(e));
    }
  };

  const handleUpdateClip = async (
    patch: Parameters<typeof api.updateClip>[1],
  ) => {
    if (!selectedClipId) return;
    try {
      await api.updateClip(selectedClipId, patch);
      await refreshTimeline();
    } catch (e) {
      setError(String(e));
    }
  };

  const handleSplitHere = async () => {
    if (!selectedClipId) return;
    const trackId = findTrackIdForClip(selectedClipId);
    if (!trackId) return;
    try {
      await api.splitClip(trackId, playhead);
      await refreshTimeline();
    } catch (e) {
      setError(String(e));
    }
  };

  const handleStartRender = async () => {
    setError(null);
    try {
      const crf = QUALITY_CRF[quality];
      const started = await api.startRender(projectId, burnSubtitles && subtitleCues.length > 0, crf);
      trackRenderJob(started);
    } catch (e) {
      setError(String(e));
    }
  };

  const totalDuration = timeline?.total_duration ?? 0;
  const clipCount = videoTrack?.clips.length ?? 0;
  const totalScenes = production?.chapters.reduce((n, c) => n + c.scenes.length, 0) ?? 0;
  const ffmpegAvailable = systemInfo ? systemInfo.ffmpeg.available : true;
  const cpuOnly = systemInfo
    ? !(systemInfo.gpu.names && systemInfo.gpu.names.length > 0 && systemInfo.ai_runtime.cuda_available)
    : true;

  const currentHash = contentHash(timeline, subtitleCues);
  const hasCompletedRender = renderJob?.status === "completed";
  const isStale = !!lastRenderHash && lastRenderHash !== currentHash && hasCompletedRender;

  const doneIds = useMemo(() => {
    const ids = new Set<string>();
    if (production?.spec) ids.add("plan");
    if (totalScenes > 0) ids.add("scenes");
    if (assets.length > 0) ids.add("assets");
    if (clipCount > 0) {
      ids.add("edit");
      ids.add("preview");
    }
    if (hasCompletedRender) {
      ids.add("export");
      ids.add("done");
    }
    return ids;
  }, [production, totalScenes, assets.length, clipCount, hasCompletedRender]);

  const currentStepId =
    view === "scenes" ? (production?.spec ? "scenes" : "plan") : view;

  const handleSelectStep = (id: string) => {
    if (id === "plan" || id === "scenes") setView("scenes");
    else setView(id as View);
  };

  return (
    <div className="editor-root">
      <div className="editor-topbar">
        <button onClick={onBack}>&larr; ホーム</button>
        <span className="editor-title">{project?.name ?? "..."}</span>
        {lastSavedAt && <span className="autosave-badge">✓ 自動保存済み</span>}
        <span style={{ flex: 1 }} />
        <LlmStatusBadge />
        {onOpenStudio && <button onClick={onOpenStudio}>✨ AI制作に戻る</button>}
        <button onClick={() => setShowSystemModal(true)}>📊 PC診断</button>
        {onOpenSettings && <button onClick={onOpenSettings}>⚙ 設定</button>}
      </div>

      <StepBar steps={STEPS} currentId={currentStepId} doneIds={doneIds} onSelect={handleSelectStep} />

      {error && (
        <div className="editor-error" onClick={() => setError(null)}>
          {error}
        </div>
      )}

      {isStale && view !== "export" && view !== "done" && (
        <ReRenderBanner onGoToExport={() => setView("export")} />
      )}

      {view === "scenes" && <ProductionPanel projectId={projectId} />}

      {view === "assets" && (
        <div className="assets-stage">
          <GenerationPanel
            projectId={projectId}
            onCompleted={() => api.listMedia(projectId).then(setAssets).catch((e) => setError(String(e)))}
          />
          <MediaBin
            projectId={projectId}
            assets={assets}
            onUploaded={(a) => setAssets((prev) => [...prev, a])}
            onAddToTrack={handleAddToTrack}
            onDetectSilence={setCutPlanAsset}
          />
        </div>
      )}

      {view === "edit" && (
        <>
          <AIEditPanel
            projectId={projectId}
            onApplied={() => {
              refreshTimeline();
              setSubtitleRefreshToken((n) => n + 1);
            }}
          />

          <div className="editor-main">
            <MediaBin
              projectId={projectId}
              assets={assets}
              onUploaded={(a) => setAssets((prev) => [...prev, a])}
              onAddToTrack={handleAddToTrack}
              onDetectSilence={setCutPlanAsset}
            />

            <div className="editor-center">
              <PreviewPlayer
                clips={videoTrack?.clips ?? []}
                assets={assetsById}
                playhead={playhead}
                isPlaying={isPlaying}
                seekNonce={seekNonce}
                onTimeUpdate={setPlayhead}
                onEnded={() => setIsPlaying(false)}
                subtitleText={currentSubtitleText}
              />
              <div className="playback-controls">
                <button onClick={() => setIsPlaying((p) => !p)}>
                  {isPlaying ? "⏸ 一時停止" : "▶ 再生"}
                </button>
                <span>
                  {formatTime(playhead)} / {formatTime(totalDuration)}
                </span>
              </div>
            </div>

            <div className="right-sidebar">
              <ClipInspector
                clip={selectedClip}
                asset={selectedAsset}
                onUpdate={handleUpdateClip}
                onDelete={() => selectedClipId && handleDeleteClip(selectedClipId)}
                onSplitHere={handleSplitHere}
              />
              <SubtitlePanel
                projectId={projectId}
                hasVideoClips={(videoTrack?.clips.length ?? 0) > 0}
                onSeek={handleSeek}
                onCuesChanged={setSubtitleCues}
                refreshToken={subtitleRefreshToken}
              />
              {project && (
                <VideoSettingsPanel
                  project={project}
                  quality={quality}
                  onQualityChange={setQuality}
                  totalDurationSeconds={totalDuration}
                  clipCount={clipCount}
                  cpuOnly={cpuOnly}
                  onUpdated={setProject}
                />
              )}
            </div>
          </div>

          <Timeline
            tracks={timeline?.tracks ?? []}
            assets={assetsById}
            playhead={playhead}
            selectedClipId={selectedClipId}
            onSeek={handleSeek}
            onSelectClip={setSelectedClipId}
            onDropAsset={handleDropAsset}
            onDeleteClip={handleDeleteClip}
            subtitleCues={subtitleCues}
          />

          {clipCount > 0 && (
            <div className="edit-to-preview-nudge">
              <button className="primary" onClick={() => setView("preview")}>
                プレビューへ進む →
              </button>
            </div>
          )}
        </>
      )}

      {view === "preview" && (
        <div className="preview-stage">
          <div
            className={`preview-stage-frame${project && project.height > project.width ? " preview-stage-frame-vertical" : ""}`}
          >
            <PreviewPlayer
              clips={videoTrack?.clips ?? []}
              assets={assetsById}
              playhead={playhead}
              isPlaying={isPlaying}
              seekNonce={seekNonce}
              onTimeUpdate={setPlayhead}
              onEnded={() => setIsPlaying(false)}
              subtitleText={currentSubtitleText}
            />
          </div>
          <div className="playback-controls">
            <button onClick={() => setIsPlaying((p) => !p)}>
              {isPlaying ? "⏸ 一時停止" : "▶ 再生"}
            </button>
            <span>
              {formatTime(playhead)} / {formatTime(totalDuration)}
            </span>
          </div>
          {clipCount === 0 ? (
            <div className="preview-empty-hint">
              まだ動画がありません。編集画面でタイムラインにクリップを追加してください。
            </div>
          ) : (
            <button className="primary preview-to-export-btn" onClick={() => setView("export")}>
              この内容で書き出す →
            </button>
          )}
        </div>
      )}

      {view === "export" && (
        <div className="export-stage">
          {renderJob && renderJob.status !== "completed" ? (
            <RenderScreen
              job={renderJob}
              projectName={project?.name ?? ""}
              clipCount={clipCount}
              hasBgm={(bgmTrack?.clips.length ?? 0) > 0}
              burnSubtitles={burnSubtitles && subtitleCues.length > 0}
              ffmpegAvailable={ffmpegAvailable}
              onRetry={handleStartRender}
              onCheckSettings={() => setView("edit")}
            />
          ) : (
            <>
              <SystemEnvSummary onOpenDetail={() => setShowSystemModal(true)} />
              {subtitleCues.length > 0 && (
                <label className="burn-subtitles-toggle">
                  <input
                    type="checkbox"
                    checked={burnSubtitles}
                    onChange={(e) => setBurnSubtitles(e.target.checked)}
                  />
                  字幕を焼き込む
                </label>
              )}
              <CreateVideoCTA
                sceneCount={totalScenes}
                clipCount={clipCount}
                timelineDuration={totalDuration}
                ffmpegAvailable={ffmpegAvailable}
                blockedReason={clipCount === 0 ? "タイムラインに動画クリップがありません" : null}
                busy={renderBusy}
                onStart={handleStartRender}
              />
            </>
          )}
        </div>
      )}

      {view === "done" && renderJob?.status === "completed" && project && (
        <CompletionScreen
          job={renderJob}
          project={project}
          totalDurationSeconds={totalDuration}
          burnSubtitles={burnSubtitles && subtitleCues.length > 0}
          onBackToEdit={() => setView("edit")}
          onRerender={() => setView("export")}
        />
      )}

      {showSystemModal && (
        <div className="modal-overlay" onClick={() => setShowSystemModal(false)}>
          <div className="modal-panel modal-panel-wide" onClick={(e) => e.stopPropagation()}>
            <div className="modal-panel-close-row">
              <button onClick={() => setShowSystemModal(false)}>閉じる ✕</button>
            </div>
            <SystemInfoPanel />
          </div>
        </div>
      )}

      {cutPlanAsset && videoTrack && (
        <CutPlanPanel
          asset={cutPlanAsset}
          videoTrackId={videoTrack.id}
          onApplied={refreshTimeline}
          onClose={() => setCutPlanAsset(null)}
        />
      )}
    </div>
  );
}
