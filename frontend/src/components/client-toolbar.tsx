"use client";

import { useCallback, useEffect, useState } from "react";
import { DateBar, refreshReports, useDateRange } from "@/components/range-controls";
import { SyncControls, SyncStatus } from "@/components/sync-controls";
import { Card } from "@/components/ui";
import { useSync } from "@/components/use-sync";
import { api, fmt, type DateRange, type Property } from "@/lib/api";

const DAY = 86_400_000;
const addDays = (iso: string, n: number) => new Date(Date.parse(iso) + n * DAY).toISOString().slice(0, 10);

/** Earliest day the chosen period (and its comparison) needs, mirroring the backend's windows. */
function earliestNeeded(r: DateRange, dataEnd: string): string {
  const end = r.start && r.end ? r.end : dataEnd;
  const start = r.start && r.end ? r.start : addDays(dataEnd, 1 - r.days);
  const length = Math.round((Date.parse(end) - Date.parse(start)) / DAY) + 1;
  const compareStart = {
    previous: addDays(start, -length),
    year: addDays(start, -364),
    custom: r.compareStart,
    none: null,
  }[r.compare];
  return compareStart && compareStart < start ? compareStart : start;
}

/** "Sync 6 months to fill it" when the period reaches before the stored data, else null. */
function missingHistory(r: DateRange, p: Property): string | null {
  if (!p.data_start || !p.data_end) return null;
  const needed = earliestNeeded(r, p.data_end);
  if (needed >= p.data_start) return null;
  const daysBack = (Date.now() - Date.parse(needed)) / DAY - 3; // Google's ~3-day lag
  const fix =
    daysBack <= 90
      ? "Sync “Last 3 months” to fill it."
      : daysBack <= 180
        ? "Sync “Last 6 months” to fill it."
        : daysBack <= 486
          ? "Sync “Full 16 months” to fill it."
          : "Google only keeps 16 months, so the oldest part can't be filled.";
  return `This period needs data from ${fmt.date(needed)}, stored data starts ${fmt.date(p.data_start)}. ${fix}`;
}

function Step({ n, label, children }: { n: number; label: string; children: React.ReactNode }) {
  return (
    <section className="min-w-0 space-y-2">
      <h2 className="flex items-center gap-2 text-xs font-medium text-muted">
        <span className="flex size-5 items-center justify-center rounded-full bg-accent-soft text-[11px] text-accent">{n}</span>
        {label}
      </h2>
      {children}
    </section>
  );
}

/** Period → data from Google, above the tabs of every client page. A finished sync reloads every report. */
export function ClientToolbar({ propertyId }: { propertyId: number }) {
  const [property, setProperty] = useState<Property | null>(null);
  const reload = useCallback(
    () =>
      api
        .property(propertyId)
        .then(setProperty)
        .catch(() => {}),
    [propertyId],
  );
  useEffect(() => {
    reload();
  }, [reload]);

  return (
    <Card className="grid gap-4 p-4 lg:grid-cols-[1fr_auto] lg:gap-8">
      <Step n={1} label="Period">
        <DateBar />
      </Step>
      <Step n={2} label="Data from Google">
        {property ? (
          <DataStep
            property={property}
            onDone={() => {
              reload();
              refreshReports();
            }}
          />
        ) : (
          <p className="text-sm text-muted">Loading…</p>
        )}
      </Step>
    </Card>
  );
}

function DataStep({ property, onDone }: { property: Property; onDone: () => void }) {
  const [range] = useDateRange();
  const { run, running, error, start } = useSync(property, onDone);
  const missing = !running && missingHistory(range, property);
  return (
    <div className="space-y-1 lg:max-w-sm">
      <SyncControls property={property} running={running} start={start} />
      <p className="text-xs text-muted">
        <SyncStatus property={property} running={running} run={run} />
      </p>
      {missing && <p className="text-xs text-warning">{missing}</p>}
      {error && <p className="text-xs text-negative">{error}</p>}
    </div>
  );
}
