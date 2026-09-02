import type { Phase, ProductionEvent, ProductionRun } from "../../types";

/**
 * The production checklist (design doc section 5).
 *
 * State per phase comes from the run's `completed_phases` plus the event
 * stream, not from a local guess, so a browser reload or a resumed run
 * shows exactly the same marks the backend believes in. A phase that
 * legitimately did nothing is marked skipped rather than done - claiming a
 * step ran when it did not is the failure mode this whole panel exists to
 * avoid.
 */

type Mark = "done" | "active" | "pending" | "failed" | "skipped" | "paused";

const MARK_GLYPH: Record<Mark, string> = {
  done: "✓",
  active: "●",
  pending: "○",
  failed: "!",
  skipped: "–",
  paused: "⏸",
};

export function phaseMarks(
  phases: Phase[],
  run: ProductionRun | null,
  events: ProductionEvent[],
): Record<string, Mark> {
  const marks: Record<string, Mark> = {};
  for (const phase of phases) marks[phase.id] = "pending";
  if (!run) return marks;

  const skipped = new Set(
    events.filter((e) => e.status === "skipped").map((e) => e.phase),
  );
  for (const id of run.completed_phases) {
    marks[id] = skipped.has(id) ? "skipped" : "done";
  }

  if (run.status === "failed") marks[run.phase] = "failed";
  else if (run.status === "paused" || run.status === "pausing") marks[run.phase] = "paused";
  else if (run.status === "stopped") {
    if (marks[run.phase] !== "done") marks[run.phase] = "paused";
  } else if (run.status === "running" || run.status === "pending") {
    if (marks[run.phase] !== "done") marks[run.phase] = "active";
  }
  return marks;
}

export default function ProductionProgress({
  phases,
  run,
  events,
  onSelectPhase,
}: {
  phases: Phase[];
  run: ProductionRun | null;
  events: ProductionEvent[];
  onSelectPhase?: (phaseId: string) => void;
}) {
  const marks = phaseMarks(phases, run, events);

  return (
    <div className="prod-progress">
      <div className="prod-progress-head">
        <span className="prod-progress-title">制作進行</span>
        {run && (
          <span className="prod-progress-pct">{run.progress.toFixed(0)}%</span>
        )}
      </div>

      {run && (
        <div className="prod-progress-bar">
          <div className="prod-progress-fill" style={{ width: `${run.progress}%` }} />
        </div>
      )}

      <ol className="prod-phase-list">
        {phases.map((phase) => {
          const mark = marks[phase.id] ?? "pending";
          return (
            <li
              key={phase.id}
              className={`prod-phase prod-phase-${mark}`}
              onClick={onSelectPhase ? () => onSelectPhase(phase.id) : undefined}
              title={phase.purpose}
            >
              <span className="prod-phase-mark" aria-hidden>
                {MARK_GLYPH[mark]}
              </span>
              <span className="prod-phase-label">{phase.label}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
