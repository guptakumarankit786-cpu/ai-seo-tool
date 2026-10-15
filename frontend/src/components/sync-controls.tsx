"use client";

import { useState } from "react";
import { Button } from "@/components/ui";
import { useSync } from "@/components/use-sync";
import { fmt, type Property, type SyncRequest } from "@/lib/api";

const OPTIONS: { value: string; label: string; body: SyncRequest }[] = [
  { value: "latest", label: "Latest days", body: { mode: "latest" } },
  { value: "90", label: "Last 3 months", body: { mode: "range", days: 90 } },
  { value: "180", label: "Last 6 months", body: { mode: "range", days: 180 } },
  { value: "486", label: "Full 16 months", body: { mode: "range", days: 486 } },
];

/** Status line for a property's performance data: progress while syncing, else the stored range. */
export function SyncStatus({ property, running, run }: Pick<ReturnType<typeof useSync>, "running" | "run"> & { property: Property }) {
  if (running && run) {
    const months = run.chunks_total > 1 ? ` — month ${Math.min(run.chunks_done + 1, run.chunks_total)} of ${run.chunks_total}` : "";
    return <>Syncing{months}… newest data first, you can keep working.</>;
  }
  if (run?.status === "failed") return <>Last sync failed: {run.error}</>;
  if (property.data_start && property.data_end) {
    return (
      <>
        Data {fmt.date(property.data_start)} – {fmt.date(property.data_end)}
        {property.last_synced_at && ` · synced ${fmt.dateTime(property.last_synced_at)}`}
      </>
    );
  }
  return <>Not synced yet</>;
}

/** Range picker + Sync button. Defaults to "Latest days" once data exists, else the full 16 months. */
export function SyncControls({
  property,
  running,
  start,
}: {
  property: Property;
  running: boolean;
  start: (body: SyncRequest) => void;
}) {
  const hasData = !!property.data_end;
  const options = hasData ? OPTIONS : OPTIONS.filter((o) => o.value !== "latest");
  const [choice, setChoice] = useState(hasData ? "latest" : "486");
  const selected = options.find((o) => o.value === choice) ?? options[options.length - 1];

  return (
    <div className="flex items-center gap-2">
      <select
        aria-label="What to sync"
        value={selected.value}
        onChange={(e) => setChoice(e.target.value)}
        disabled={running}
        className="rounded-md border border-border bg-surface px-2 py-1.5 text-sm disabled:opacity-50"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <Button variant="secondary" disabled={running} onClick={() => start(selected.body)}>
        {running ? "Syncing…" : "Sync"}
      </Button>
    </div>
  );
}
