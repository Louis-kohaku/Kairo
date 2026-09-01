import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { MediaAsset, Project, SubtitleCue, Timeline as TimelineData } from "../types";
import MediaBin from "../components/MediaBin";
import PreviewPlayer from "../components/PreviewPlayer";
import Timeline from "../components/Timeline";
import ClipInspector from "../components/ClipInspector";
import RenderPanel from "../components/RenderPanel";
import SubtitlePanel from "../components/SubtitlePanel";
import CutPlanPanel from "../components/CutPlanPanel";
import AIEditPanel from "../components/AIEditPanel";
import ProductionPanel from "../components/ProductionPanel";
import GenerationPanel from "../components/GenerationPanel";
import SystemInfoPanel from "../components/SystemInfoPanel";
import LlmStatusBadge from "../components/LlmStatusBadge";
import { formatTime } from "../utils/format";

export default function Editor({
  projectId,
  onBack,
}: {
  projectId: string;
  onBack: () => void;
}) {
  const [mode, setMode] = useState<"edit" | "production" | "generate" | "system">("edit");
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

  const assetsById = useMemo(() => {
    const map: Record<string, MediaAsset> = {};
    for (const a of assets) map[a.id] = a;
    return map;
  }, [assets]);

  const videoTrack = timeline?.tracks.find((t) => t.type === "video") ?? null;
  const bgmTrack = timeline?.tracks.find((t) => t.type === "audio") ?? null;

  const refreshTimeline = () =>
    api.getTimeline(projectId).then(setTimeline).catch((e) => setError(String(e)));

  useEffect(() => {
    api.getProject(projectId).then(setProject).catch((e) => setError(String(e)));
    api.listMedia(projectId).then(setAssets).catch((e) => setError(String(e)));
    refreshTimeline();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

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

  const totalDuration = timeline?.total_duration ?? 0;

  return (
    <div className="editor-root">
      <div className="editor-topbar">
        <button onClick={onBack}>&larr; プロジェクト一覧</button>
        <span className="editor-title">{project?.name ?? "..."}</span>
        <div className="mode-switch">
          <button
            className={mode === "edit" ? "mode-active" : ""}
            onClick={() => setMode("edit")}
          >
            編集
          </button>
          <button
            className={mode === "production" ? "mode-active" : ""}
            onClick={() => setMode("production")}
          >
            AI制作
          </button>
          <button
            className={mode === "generate" ? "mode-active" : ""}
            onClick={() => setMode("generate")}
          >
            生成
          </button>
          <button
            className={mode === "system" ? "mode-active" : ""}
            onClick={() => setMode("system")}
          >
            PC診断
          </button>
        </div>
        <span style={{ flex: 1 }} />
        <LlmStatusBadge />
        {mode === "edit" && (
          <RenderPanel
            projectId={projectId}
            hasVideoClips={(videoTrack?.clips.length ?? 0) > 0}
            hasSubtitles={subtitleCues.length > 0}
          />
        )}
      </div>

      {error && (
        <div className="editor-error" onClick={() => setError(null)}>
          {error}
        </div>
      )}

      {mode === "production" && <ProductionPanel projectId={projectId} />}

      {mode === "generate" && (
        <GenerationPanel
          projectId={projectId}
          onCompleted={() => api.listMedia(projectId).then(setAssets).catch((e) => setError(String(e)))}
        />
      )}

      {mode === "system" && <SystemInfoPanel />}

      {mode === "edit" && (
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
      />

      {cutPlanAsset && videoTrack && (
        <CutPlanPanel
          asset={cutPlanAsset}
          videoTrackId={videoTrack.id}
          onApplied={refreshTimeline}
          onClose={() => setCutPlanAsset(null)}
        />
      )}
        </>
      )}
    </div>
  );
}
