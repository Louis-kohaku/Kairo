import { useMemo } from "react";
import type { ProductionEvent, ProductionRun } from "../../types";
import { currentActivity } from "../../hooks/useProductionRun";

/**
 * "AIが今なにをしているのか" (design doc sections 4/6).
 *
 * Deliberately answers five questions at once - phase, task, target,
 * purpose, and what comes next - because "AI Processing..." answering none
 * of them is the specific problem this replaces. What it never shows is
 * the model's reasoning (section 7): these are actions Kairo is taking,
 * not thoughts it is having.
 */
export default function AIActivity({
  run,
  events,
}: {
  run: ProductionRun | null;
  events: ProductionEvent[];
}) {
  const current = useMemo(() => currentActivity(events), [events]);

  const userEvents = useMemo(() => events.filter((e) => e.level === "user"), [events]);

  const recentDone = useMemo(
    () =>
      userEvents
        .filter((e) => e.status === "done" || e.status === "skipped")
        .slice(-4)
        .reverse(),
    [userEvents],
  );

  const isActive = run?.status === "running" || run?.status === "pending";

  if (!run) return null;

  return (
    <div className="ai-activity">
      <div className="ai-activity-head">
        <span className={`ai-activity-dot${isActive ? " ai-activity-dot-live" : ""}`} />
        <span className="ai-activity-title">AI作業状況</span>
        {run.status === "paused" && <span className="ai-activity-badge">一時停止中</span>}
        {run.status === "pausing" && (
          <span className="ai-activity-badge">停止位置まで処理中…</span>
        )}
        {run.status === "completed" && (
          <span className="ai-activity-badge ai-activity-badge-ok">完了</span>
        )}
        {run.status === "failed" && (
          <span className="ai-activity-badge ai-activity-badge-bad">停止しました</span>
        )}
      </div>

      <dl className="ai-activity-grid">
        <dt>現在のフェーズ</dt>
        <dd className="ai-activity-phase">{run.phase_label}</dd>

        <dt>現在の作業</dt>
        <dd>{current?.task || run.task || "準備しています"}</dd>

        {current?.target && (
          <>
            <dt>対象</dt>
            <dd>{current.target}</dd>
          </>
        )}

        {current?.message && (
          <>
            <dt>内容</dt>
            <dd className="ai-activity-message">{current.message}</dd>
          </>
        )}

        {current?.reason && (
          <>
            <dt>目的</dt>
            <dd className="ai-activity-reason">{current.reason}</dd>
          </>
        )}

        {current?.model && (
          <>
            <dt>使用モデル</dt>
            <dd className="ai-activity-model">{current.model}</dd>
          </>
        )}

        {current?.next_task && (
          <>
            <dt>次の処理</dt>
            <dd>→ {current.next_task}</dd>
          </>
        )}
      </dl>

      {recentDone.length > 0 && (
        <div className="ai-activity-done">
          <div className="ai-activity-done-title">完了済み</div>
          <ul>
            {recentDone.map((e) => (
              <li key={e.id}>
                <span className={e.status === "skipped" ? "dim" : "ok"}>
                  {e.status === "skipped" ? "–" : "✓"}
                </span>{" "}
                {e.phase_label}
                {e.message ? ` — ${e.message}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
