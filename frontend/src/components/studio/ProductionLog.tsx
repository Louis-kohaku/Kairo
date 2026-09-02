import { useMemo, useState } from "react";
import type { ProductionEvent } from "../../types";

/**
 * The production log, split the way design doc section 51 requires:
 * plain-language events by default, technical detail (endpoints, ffmpeg
 * arguments, model ids, timings) behind a toggle.
 *
 * Section 50 is the other half of the rule: the technical view is a
 * disclosure, not a permission level. Anything the user needs in order to
 * solve a problem - the cause, the model involved, the failing step - is in
 * the user view already.
 */
export default function ProductionLog({ events }: { events: ProductionEvent[] }) {
  const [showTech, setShowTech] = useState(false);
  const [open, setOpen] = useState(false);

  const visible = useMemo(
    () => (showTech ? events : events.filter((e) => e.level === "user")),
    [events, showTech],
  );

  const techCount = events.length - events.filter((e) => e.level === "user").length;

  return (
    <div className="prodlog">
      <button className="prodlog-toggle" onClick={() => setOpen((v) => !v)}>
        {open ? "▾" : "▸"} 制作ログ ({visible.length}件)
      </button>

      {open && (
        <>
          <label className="prodlog-tech-toggle">
            <input
              type="checkbox"
              checked={showTech}
              onChange={(e) => setShowTech(e.target.checked)}
            />
            技術的な詳細も表示 ({techCount}件)
          </label>

          <div className="prodlog-list">
            {visible.map((e) => (
              <div key={e.id} className={`prodlog-row prodlog-row-${e.level} prodlog-${e.status}`}>
                <span className="prodlog-time">
                  {e.timestamp ? new Date(e.timestamp).toLocaleTimeString() : ""}
                </span>
                <span className="prodlog-phase">{e.phase_label}</span>
                <span className="prodlog-message">
                  {e.task && e.task !== e.message ? `${e.task} — ` : ""}
                  {e.message}
                </span>
              </div>
            ))}
            {visible.length === 0 && <div className="prodlog-empty">まだログがありません。</div>}
          </div>
        </>
      )}
    </div>
  );
}
