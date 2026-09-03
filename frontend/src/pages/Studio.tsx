import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type {
  MaterialMode,
  MaterialUsageEntry,
  MediaAsset,
  ProductionData,
  Project,
  SubtitleCue,
  Timeline as TimelineData,
} from "../types";
import { useProductionRun } from "../hooks/useProductionRun";
import { useMaterials } from "../hooks/useMaterials";
import { useMaterialUsage } from "../hooks/useMaterialUsage";
import ProductionProgress from "../components/studio/ProductionProgress";
import AIActivity from "../components/studio/AIActivity";
import ProductionLog from "../components/studio/ProductionLog";
import ModelPlanPanel from "../components/studio/ModelPlanPanel";
import StudioLauncher from "../components/studio/StudioLauncher";
import CoCreationChat from "../components/studio/CoCreationChat";
import QualityPanel from "../components/studio/QualityPanel";
import VideoReviewPanel from "../components/studio/VideoReviewPanel";
import AgentDecisionsPanel from "../components/studio/AgentDecisionsPanel";
import ResearchPanel from "../components/studio/ResearchPanel";
import SceneBoard from "../components/studio/SceneBoard";
import MaterialPanel from "../components/studio/MaterialPanel";
import MaterialPlanPanel from "../components/studio/MaterialPlanPanel";
import MaterialUsagePanel from "../components/studio/MaterialUsagePanel";
import StudioCompletion from "../components/studio/StudioCompletion";
import PreviewPlayer from "../components/PreviewPlayer";
import Timeline from "../components/Timeline";
import AIErrorPanel from "../components/AIErrorPanel";
import LlmStatusBadge from "../components/LlmStatusBadge";
import SystemInfoPanel from "../components/SystemInfoPanel";
import { formatTime } from "../utils/format";

type Tab =
  | "progress"
  | "preview"
  | "materials"
  | "usage"
  | "scenes"
  | "quality"
  | "review"
  | "decisions"
  | "research";

const TABS: { id: Tab; label: string }[] = [
  { id: "progress", label: "制作状況" },
  { id: "preview", label: "プレビュー" },
  { id: "materials", label: "素材" },
  { id: "usage", label: "使用素材" },
  { id: "scenes", label: "シーン" },
  { id: "quality", label: "品質" },
  // The rendered file's own score, kept apart from "品質" (which reviews the
  // plan) because the two genuinely can disagree.
  { id: "review", label: "完成動画レビュー" },
  { id: "decisions", label: "AIの判断" },
  { id: "research", label: "調査・戦略" },
];

/**
 * The production studio: one screen for Full Auto and AI Co-Creation.
 *
 * The two modes are not separate pages because they are the same
 * production - Co-Creation is Full Auto plus a conversation. Sharing the
 * screen is what makes "AIが作っている途中に口を挟む" natural rather than a
 * mode switch.
 */
export default function Studio({
  projectId,
  mode,
  onBack,
  onOpenEditor,
  onOpenSettings,
}: {
  projectId: string;
  mode: "full_auto" | "co_creation";
  onBack: () => void;
  onOpenEditor: () => void;
  onOpenSettings: () => void;
}) {
  const { run, phases, events, error, setError, start, control, refreshRun } =
    useProductionRun(projectId);

  const [project, setProject] = useState<Project | null>(null);
  const [timeline, setTimeline] = useState<TimelineData | null>(null);
  const [assets, setAssets] = useState<MediaAsset[]>([]);
  const [cues, setCues] = useState<SubtitleCue[]>([]);
  const [production, setProduction] = useState<ProductionData | null>(null);
  const [tab, setTab] = useState<Tab>("progress");
  const [chatOpen, setChatOpen] = useState(mode === "co_creation");
  const [starting, setStarting] = useState(false);
  const [playhead, setPlayhead] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [seekNonce, setSeekNonce] = useState(0);
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null);
  const [recheckBusy, setRecheckBusy] = useState(false);
  const [reevalBusy, setReevalBusy] = useState(false);
  const [reevalNotice, setReevalNotice] = useState<string | null>(null);
  const [usageKey, setUsageKey] = useState(0);
  const [variantBusy, setVariantBusy] = useState(false);
  // Section 37: available on demand, never cluttering the production view.
  const [showSystem, setShowSystem] = useState(false);

  const material = useMaterials(projectId, run?.target_duration_seconds ?? 30);

  const usage = useMaterialUsage(projectId, usageKey);

  const refreshProject = useCallback(async () => {
    try {
      const [p, t, a, c, prod] = await Promise.all([
        api.getProject(projectId),
        api.getTimeline(projectId),
        api.listMedia(projectId),
        api.listSubtitles(projectId).catch(() => []),
        api.getProduction(projectId).catch(() => null),
      ]);
      setProject(p);
      setTimeline(t);
      setAssets(a);
      setCues(c);
      setProduction(prod);
    } catch (e) {
      setError(String(e));
    }
  }, [projectId, setError]);

  useEffect(() => {
    refreshProject();
  }, [refreshProject]);

  // Material only changes at phase boundaries, so refreshing on phase
  // change (rather than on every event) keeps the preview current without
  // re-fetching the timeline dozens of times per scene.
  const phaseKey = run?.phase ?? "";
  const statusKey = run?.status ?? "";
  useEffect(() => {
    refreshProject();
    material.reload();
    setUsageKey((k) => k + 1);
    // `material.reload` is stable per project; depending on it here would
    // re-run this effect on every render of the hook's internal state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phaseKey, statusKey, refreshProject]);

  const assetsById = useMemo(() => {
    const map: Record<string, MediaAsset> = {};
    for (const a of assets) map[a.id] = a;
    return map;
  }, [assets]);

  const videoTrack = timeline?.tracks.find((t) => t.type === "video") ?? null;
  const totalDuration = timeline?.total_duration ?? 0;
  const currentSubtitle =
    cues.find((c) => playhead >= c.start && playhead < c.end)?.text ?? null;

  const scenes = useMemo(
    () => production?.chapters.flatMap((c) => c.scenes) ?? [],
    [production],
  );

  const handleStart = async (opts: {
    instruction: string;
    targetDurationSeconds: number;
    orientation: string;
    mode: "full_auto" | "co_creation";
    materialMode: MaterialMode;
    selectedAssetIds: string[];
  }) => {
    setStarting(true);
    try {
      await start(opts);
      setTab("progress");
    } catch {
      // surfaced through `error`
    } finally {
      setStarting(false);
    }
  };

  /**
   * Design requirement 12: material added after production started is not a
   * new project. The backend re-matches over the existing scenes, rebuilds
   * only what changed and re-renders, so "海の写真をあと3枚" improves the
   * video that already exists instead of starting again.
   */
  const handleReevaluate = async () => {
    setReevalBusy(true);
    setReevalNotice(null);
    try {
      await api.reevaluateMaterials(projectId, {
        mode: material.mode,
        selectedAssetIds: material.selectedIds,
      });
      setReevalNotice(
        "追加素材の反映を開始しました。進行状況は「制作状況」に表示されます。",
      );
    } catch (e) {
      setError(String(e));
    } finally {
      setReevalBusy(false);
    }
  };

  const handleRecheck = async () => {
    setRecheckBusy(true);
    try {
      await api.runQualityCheck(projectId);
      await refreshRun();
    } catch (e) {
      setError(String(e));
    } finally {
      setRecheckBusy(false);
    }
  };

  const isRunning = run?.status === "running" || run?.status === "pending";
  const isPaused = run?.status === "paused" || run?.status === "pausing";
  const canResume =
    run != null && ["paused", "stopped", "failed"].includes(run.status);
  const isDone = run?.status === "completed";

  // Nothing has been produced yet: show the launcher rather than an empty
  // studio the user has to work out what to do with (section 48).
  if (!run || (run.status === "stopped" && run.completed_phases.length === 0)) {
    return (
      <div className="studio-root">
        <StudioTopBar
          project={project}
          onBack={onBack}
          onOpenSettings={onOpenSettings}
          onOpenEditor={onOpenEditor}
          onOpenSystem={() => setShowSystem(true)}
        />
        {showSystem && <SystemModal onClose={() => setShowSystem(false)} />}
        <StudioLauncher
          projectId={projectId}
          mode={mode}
          onStart={handleStart}
          busy={starting}
          error={error}
        />
      </div>
    );
  }

  return (
    <div className={`studio-root${chatOpen ? " studio-chat-open" : ""}`}>
      <StudioTopBar
        project={project}
        onBack={onBack}
        onOpenSettings={onOpenSettings}
        onOpenEditor={onOpenEditor}
        onOpenSystem={() => setShowSystem(true)}
      />

      {showSystem && <SystemModal onClose={() => setShowSystem(false)} />}

      <div className="studio-controls">
        <div className="studio-controls-status">
          <span className={`studio-status studio-status-${run.status}`}>
            {run.status === "running" && "制作中"}
            {run.status === "pending" && "開始しています"}
            {run.status === "pausing" && "一時停止しています…"}
            {run.status === "paused" && "一時停止中"}
            {run.status === "stopped" && "停止しました"}
            {run.status === "failed" && "エラーで停止"}
            {run.status === "completed" && "完成"}
          </span>
          <span className="studio-phase-now">{run.phase_label}</span>
          <span className="studio-progress-pct">{run.progress.toFixed(0)}%</span>
        </div>

        <div className="studio-controls-buttons">
          {isRunning && (
            <button onClick={() => control("pause")}>⏸ 一時停止</button>
          )}
          {canResume && (
            <button className="primary" onClick={() => control("resume")}>
              ▶ {run.status === "paused" ? "再開" : `${run.resume_phase ? "" : ""}続きから再開`}
            </button>
          )}
          {(isRunning || isPaused) && (
            <button className="danger" onClick={() => control("stop")}>
              ■ 停止
            </button>
          )}
          <button
            className={chatOpen ? "chip chip-on" : "chip"}
            onClick={() => setChatOpen((v) => !v)}
          >
            💬 AIと相談
          </button>
        </div>
      </div>

      {run.status === "stopped" && run.resume_phase && (
        <div className="studio-resume-hint">
          「{phases.find((p) => p.id === run.resume_phase)?.label ?? run.resume_phase}
          」から再開します。完了済みの工程はやり直しません。
        </div>
      )}

      {error && (
        <div className="editor-error" onClick={() => setError(null)}>
          {error}
        </div>
      )}

      {run.status === "failed" && run.error_detail && (
        <AIErrorPanel
          diagnosis={run.error_detail}
          onRecheck={refreshRun}
          onRetry={() => control("resume")}
        />
      )}

      <div className="studio-body">
        <aside className="studio-rail">
          <ProductionProgress phases={phases} run={run} events={events} />
          <AIActivity run={run} events={events} />
          <ModelPlanPanel plan={run.model_plan} compact />
        </aside>

        <main className="studio-stage">
          <div className="studio-tabs">
            {TABS.map((t) => (
              <button
                key={t.id}
                className={tab === t.id ? "studio-tab studio-tab-on" : "studio-tab"}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>

          {tab === "progress" && (
            <div className="studio-panel">
              {isDone && project && (
                <StudioCompletion
                  run={run}
                  project={project}
                  durationSeconds={totalDuration}
                  onOpenEditor={onOpenEditor}
                  onPreview={() => setTab("preview")}
                  onImproveMore={() => setChatOpen(true)}
                  onShowMaterials={() => setTab("usage")}
                />
              )}
              <ProductionLog events={events} />
            </div>
          )}

          {tab === "preview" && (
            <div className="studio-panel studio-preview-panel">
              {(videoTrack?.clips.length ?? 0) === 0 ? (
                <div className="studio-empty">
                  まだ映像がありません。素材生成と編集が終わるとここで再生できます。
                </div>
              ) : (
                <>
                  <div
                    className={`studio-preview-frame${
                      project && project.height > project.width
                        ? " studio-preview-vertical"
                        : ""
                    }`}
                  >
                    <PreviewPlayer
                      clips={videoTrack?.clips ?? []}
                      assets={assetsById}
                      playhead={playhead}
                      isPlaying={isPlaying}
                      seekNonce={seekNonce}
                      onTimeUpdate={setPlayhead}
                      onEnded={() => setIsPlaying(false)}
                      subtitleText={currentSubtitle}
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
                  <Timeline
                    tracks={timeline?.tracks ?? []}
                    assets={assetsById}
                    playhead={playhead}
                    selectedClipId={selectedClipId}
                    onSeek={(t) => {
                      setPlayhead(t);
                      setSeekNonce((n) => n + 1);
                    }}
                    onSelectClip={(id) => {
                      setSelectedClipId(id);
                      // Selecting a clip is the natural way to ask "この素材は
                      // どこから来たのか", so it moves the playhead onto that
                      // clip and the source bar below answers.
                      const clips = videoTrack?.clips ?? [];
                      const index = clips.findIndex((c) => c.id === id);
                      if (index >= 0) {
                        const start = clips
                          .slice(0, index)
                          .reduce((n, c) => n + (c.out_point - c.in_point), 0);
                        setPlayhead(start);
                        setSeekNonce((n) => n + 1);
                      }
                    }}
                    onDropAsset={() => {}}
                    onDeleteClip={() => {}}
                    subtitleCues={cues}
                  />
                  <MaterialSourceBar
                    entry={usage.entryAt(playhead)}
                    onOpenUsage={() => setTab("usage")}
                  />
                </>
              )}
            </div>
          )}

          {tab === "materials" && (
            <div className="studio-panel">
              <MaterialPlanPanel plan={run.material_plan ?? material.plan} />
              {reevalNotice && <div className="material-notice">{reevalNotice}</div>}
              <div className="material-reeval">
                <button
                  className="primary"
                  onClick={handleReevaluate}
                  disabled={reevalBusy || isRunning || material.materials.length === 0}
                  title={
                    isRunning
                      ? "制作の実行中は素材を反映できません。完了を待つか一時停止してください。"
                      : undefined
                  }
                >
                  {reevalBusy ? "反映しています…" : "追加素材を反映して作り直す"}
                </button>
                <span className="material-plan-dim">
                  追加した素材でタイムラインを再評価し、より合う素材に置き換えてMP4を作り直します。
                </span>
              </div>
              <MaterialPanel
                projectId={projectId}
                materials={material.materials}
                loading={material.loading}
                visionAvailable={material.visionAvailable}
                mode={material.mode}
                selectedIds={material.selectedIds}
                onModeChange={material.setMode}
                onSelectionChange={material.setSelectedIds}
                onChanged={material.reload}
                busy={reevalBusy}
              />
            </div>
          )}

          {tab === "usage" && (
            <div className="studio-panel">
              <MaterialUsagePanel
                materials={material.materials}
                usage={usage.usage}
                loading={usage.loading}
                error={usage.error}
                playhead={playhead}
                onSeek={(t) => {
                  setPlayhead(t);
                  setSeekNonce((n) => n + 1);
                  setTab("preview");
                }}
              />
            </div>
          )}

          {tab === "scenes" && (
            <div className="studio-panel">
              <SceneBoard
                scenes={scenes}
                events={events}
                assets={assets}
                isRunning={isRunning}
                onChanged={refreshProject}
              />
            </div>
          )}

          {tab === "review" && (
            <VideoReviewPanel
              review={run?.review ?? null}
              report={run?.report ?? null}
              iteration={run?.iteration ?? 0}
              bestScore={run?.best_score ?? null}
              variants={run?.variants ?? null}
              variantBusy={variantBusy}
              onGenerateVariants={
                run && run.status !== "running"
                  ? async () => {
                      setVariantBusy(true);
                      setError(null);
                      try {
                        const { job_id } = await api.startVariants(projectId);
                        // Each variant is a full re-encode, so this polls the
                        // job rather than holding the request open.
                        for (;;) {
                          await new Promise((resolve) => setTimeout(resolve, 3000));
                          const job = await api.getJob(job_id);
                          if (job.status === "completed") break;
                          if (job.status === "failed") {
                            setError(job.error ?? "バリエーションの作成に失敗しました");
                            break;
                          }
                        }
                        await refreshRun();
                        await refreshProject();
                      } catch (e) {
                        setError(String(e));
                      } finally {
                        setVariantBusy(false);
                      }
                    }
                  : undefined
              }
            />
          )}

          {tab === "decisions" && (
            <AgentDecisionsPanel trend={run?.trend ?? null} assets={run?.assets ?? null} />
          )}

          {tab === "quality" && (
            <div className="studio-panel">
              <QualityPanel
                report={run.quality}
                improvement={run.improvement}
                onRecheck={handleRecheck}
                busy={recheckBusy}
              />
            </div>
          )}

          {tab === "research" && (
            <div className="studio-panel">
              <ResearchPanel research={run.research} strategy={run.strategy} />
            </div>
          )}
        </main>

        {chatOpen && (
          <aside className="studio-chat">
            <CoCreationChat
              projectId={projectId}
              onApplied={() => {
                refreshProject();
                refreshRun();
              }}
              onClose={() => setChatOpen(false)}
              disabled={isRunning}
              disabledReason="制作の実行中は変更を適用できません。一時停止するか、完成を待ってから指示してください。"
            />
          </aside>
        )}
      </div>
    </div>
  );
}

/**
 * "この素材はどこから来たのか" for whatever is on screen right now.
 *
 * Sits directly under the timeline because that is where the question gets
 * asked - the user clicks a clip and wants to know whether it is their
 * photo or something Kairo produced, without leaving the preview.
 */
function MaterialSourceBar({
  entry,
  onOpenUsage,
}: {
  entry: MaterialUsageEntry | null;
  onOpenUsage: () => void;
}) {
  if (entry == null) return null;
  return (
    <div className="material-source-bar">
      <span className={`origin-badge origin-${entry.origin}`}>{entry.origin_label}</span>
      <span className="material-source-name">
        {entry.filename || `Scene ${entry.scene_number}`}
      </span>
      <span className="material-plan-dim">
        {formatTime(entry.start)}〜{formatTime(entry.end)}
        {entry.source_start != null && ` / 元素材 ${formatTime(entry.source_start)}〜`}
      </span>
      {entry.note && <span className="material-plan-dim">{entry.note}</span>}
      <span style={{ flex: 1 }} />
      <button onClick={onOpenUsage}>使用素材の一覧</button>
    </div>
  );
}

function StudioTopBar({
  project,
  onBack,
  onOpenSettings,
  onOpenEditor,
  onOpenSystem,
}: {
  project: Project | null;
  onBack: () => void;
  onOpenSettings: () => void;
  onOpenEditor: () => void;
  onOpenSystem: () => void;
}) {
  return (
    <div className="editor-topbar">
      <button onClick={onBack}>&larr; ホーム</button>
      <span className="editor-title">{project?.name ?? "…"}</span>
      <span style={{ flex: 1 }} />
      <LlmStatusBadge />
      <button onClick={onOpenSystem}>📊 PC診断</button>
      <button onClick={onOpenEditor}>✂ 手動編集</button>
      <button onClick={onOpenSettings}>⚙ 設定</button>
    </div>
  );
}

/** PC / AI environment status, on demand (design doc section 37). */
function SystemModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel modal-panel-wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-panel-close-row">
          <button onClick={onClose}>閉じる ✕</button>
        </div>
        <SystemInfoPanel />
      </div>
    </div>
  );
}
