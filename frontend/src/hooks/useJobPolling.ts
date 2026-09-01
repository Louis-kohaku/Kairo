import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Job } from "../types";

export function useJobPolling() {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, []);

  const track = (initial: Job) => {
    setJob(initial);
    if (pollRef.current) window.clearInterval(pollRef.current);
    pollRef.current = window.setInterval(async () => {
      try {
        const updated = await api.getJob(initial.id);
        setJob(updated);
        if (updated.status === "completed" || updated.status === "failed") {
          if (pollRef.current) window.clearInterval(pollRef.current);
        }
      } catch (e) {
        setError(String(e));
        if (pollRef.current) window.clearInterval(pollRef.current);
      }
    }, 1000);
  };

  const isBusy = job?.status === "pending" || job?.status === "running";

  return { job, error, setError, track, isBusy };
}
