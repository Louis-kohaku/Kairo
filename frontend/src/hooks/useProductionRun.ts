import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { MaterialMode, Phase, ProductionEvent, ProductionRun } from "../types";

/**
 * Tracks one production run: its status and its event stream.
 *
 * Events are fetched with the backend's long poll (`wait=true`), which
 * returns as soon as the pipeline emits anything. That keeps the "AI作業状況"
 * panel genuinely live - a scene finishing shows up in well under a second -
 * without a socket, and without hammering the API while a slow phase runs.
 *
 * Every event ever emitted is replayed on mount, so reloading the browser
 * mid-production restores the whole history rather than resuming from
 * whatever happens next.
 */
export function useProductionRun(projectId: string) {
  const [run, setRun] = useState<ProductionRun | null>(null);
  const [phases, setPhases] = useState<Phase[]>([]);
  const [events, setEvents] = useState<ProductionEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const seqRef = useRef(0);
  const runIdRef = useRef<string | null>(null);
  const stoppedRef = useRef(false);
  // Bumped whenever a run becomes active again, to restart the event
  // pump after it exited on a finished run.
  const [pumpKey, setPumpKey] = useState(0);

  const refreshRun = useCallback(async () => {
    try {
      const data = await api.getStudioRun(projectId);
      setRun(data.run);
      setPhases(data.phases);
      if (data.run && data.run.id !== runIdRef.current) {
        // A different run than we were following: start its event stream
        // from the beginning.
        runIdRef.current = data.run.id;
        seqRef.current = 0;
        setEvents([]);
      }
      return data.run;
    } catch (e) {
      setError(String(e));
      return null;
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    stoppedRef.current = false;
    seqRef.current = 0;
    runIdRef.current = null;
    setEvents([]);
    refreshRun();
    return () => {
      stoppedRef.current = true;
    };
  }, [projectId, refreshRun]);

  // Event pump. One loop for the component's lifetime rather than an
  // interval, so a long poll that returns after 20s of silence immediately
  // starts the next one instead of waiting for the next tick.
  //
  // It must also *stop*. A long poll holds an HTTP connection open, the
  // browser allows only six per origin, and a finished run can emit no
  // further events - so continuing to poll one is not merely wasteful, it
  // starves everything else on the page. That is what left the preview
  // permanently black: the <video> element's request never got a
  // connection and stalled with no data and no error.
  useEffect(() => {
    let cancelled = false;

    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
    const isFinished = (status?: string) =>
      status === "completed" || status === "failed" || status === "stopped";

    const pump = async () => {
      while (!cancelled && !stoppedRef.current) {
        const runId = runIdRef.current;
        if (!runId) {
          await sleep(800);
          continue;
        }
        try {
          const fresh = await api.getRunEvents(runId, seqRef.current, true);
          if (cancelled) return;
          if (fresh.length > 0) {
            seqRef.current = fresh[fresh.length - 1].seq;
            setEvents((prev) => [...prev, ...fresh]);
          }
          const current = await refreshRun();
          if (cancelled) return;
          if (isFinished(current?.status)) {
            // Nothing more can arrive for this run. Release the connection
            // and wait to be woken by a new run (`start` bumps pumpKey).
            return;
          }
        } catch {
          // Backend restart or a dropped connection: back off, keep going.
          await sleep(2000);
        }
      }
    };

    pump();
    return () => {
      cancelled = true;
    };
  }, [projectId, refreshRun, pumpKey]);

  const start = useCallback(
    async (opts: {
      instruction: string;
      targetDurationSeconds: number;
      orientation: string;
      mode?: "full_auto" | "co_creation";
      materialMode?: MaterialMode;
      selectedAssetIds?: string[];
      // Empty = the edit director decides.
      platform?: string;
      editStyle?: string;
    }) => {
      setError(null);
      try {
        const started = await api.startStudioRun(projectId, opts);
        runIdRef.current = started.id;
        seqRef.current = 0;
        setEvents([]);
        setRun(started);
        setPumpKey((k) => k + 1);
        return started;
      } catch (e) {
        setError(String(e));
        throw e;
      }
    },
    [projectId],
  );

  const control = useCallback(
    async (action: "pause" | "resume" | "stop") => {
      if (!run) return;
      setError(null);
      try {
        const updated =
          action === "pause"
            ? await api.pauseRun(run.id)
            : action === "resume"
              ? await api.resumeRun(run.id)
              : await api.stopRun(run.id);
        setRun(updated);
        // Resuming makes the run live again, so the pump has to come back.
        if (action === "resume") setPumpKey((k) => k + 1);
      } catch (e) {
        setError(String(e));
      }
    },
    [run],
  );

  return { run, phases, events, error, setError, loading, start, control, refreshRun };
}

/** The most recent user-facing event, which is what "現在の作業" shows. */
export function currentActivity(events: ProductionEvent[]): ProductionEvent | null {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].level === "user" && events[i].status === "running") return events[i];
  }
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].level === "user") return events[i];
  }
  return null;
}
