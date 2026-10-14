"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Property, type SyncRun } from "@/lib/api";

const POLL_MS = 2000;

/** Starts a GSC sync for a property and polls until it finishes. */
export function useSync(property: Property, onDone?: () => void) {
  const [run, setRun] = useState<SyncRun | null>(property.latest_run);
  const [error, setError] = useState<string | null>(null);
  const [seenRun, setSeenRun] = useState(property.latest_run);
  const running = run?.status === "running";

  // Adopt a newer run whenever the parent reloads the property.
  if (seenRun !== property.latest_run) {
    setSeenRun(property.latest_run);
    setRun(property.latest_run);
  }

  useEffect(() => {
    if (!running) return;
    const timer = setInterval(async () => {
      try {
        const latest = (await api.property(property.id)).latest_run;
        setRun(latest);
        if (latest?.status !== "running") onDone?.();
      } catch (e) {
        setError((e as Error).message);
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [running, property.id, onDone]);

  const start = useCallback(
    async (days: number) => {
      setError(null);
      try {
        setRun(await api.sync(property.id, days));
      } catch (e) {
        setError((e as Error).message);
      }
    },
    [property.id],
  );

  return { run, running, error, start };
}
