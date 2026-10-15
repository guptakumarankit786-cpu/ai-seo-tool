"use client";

import { useState } from "react";
import { Banner, Card } from "@/components/ui";
import {
  api,
  fmt,
  type QuerySegment,
  type SeasonStatus,
  type SeasonalResponse,
  type SeasonalRow,
  type SpikeRow,
  type SpikesResponse,
} from "@/lib/api";
import { BrandDot, Footer, usePaged } from "./opportunity-views";

const PAGE_SIZE = 100;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const LOADING = "Working out monthly patterns from your stored history… the first time after a sync takes ~5–15 seconds.";

const STATUS_LABEL: Record<SeasonStatus, string> = {
  coming_up: "Coming up",
  in_season: "In season",
  off_season: "Off season",
};
const STATUS_STYLE: Record<SeasonStatus, string> = {
  coming_up: "bg-negative/15 text-negative",
  in_season: "bg-positive/15 text-positive",
  off_season: "bg-border text-muted",
};

/** Tiny monthly bar chart; highlighted bars are the peak / spike months. */
function MonthBars({ months, values, highlight }: { months: string[]; values: number[]; highlight: (month: string) => boolean }) {
  const max = Math.max(...values, 1);
  return (
    <div className="flex h-8 items-end gap-px" role="img" aria-label="Monthly impressions">
      {values.map((v, i) => (
        <div
          key={months[i]}
          title={`${fmt.month(months[i])}: ${fmt.int(v)} impressions`}
          className={`w-1.5 rounded-sm ${highlight(months[i]) ? "bg-accent" : "bg-muted/40"}`}
          style={{ height: `${Math.max(4, (v / max) * 100)}%` }}
        />
      ))}
    </div>
  );
}

export function SeasonalPanel({ propertyId, segment }: { propertyId: number; segment: QuerySegment }) {
  const [status, setStatus] = useState<SeasonStatus | null>(null);
  const { data, rows, error, loading, more } = usePaged<SeasonalRow, SeasonalResponse>(
    (offset) => api.seasonal(propertyId, segment, status, PAGE_SIZE, offset),
    [propertyId, segment, status],
  );

  return (
    <Card className="overflow-hidden">
      <div className="space-y-2 px-4 pt-4 pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-medium">
            {data ? `${fmt.int(data.total)} seasonal keywords` : "Seasonal keywords"}
            {loading && data && <span className="ml-2 font-normal text-muted">Updating…</span>}
          </h2>
          {data && (
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="Season status">
              <StatusChip active={status === null} onClick={() => setStatus(null)} label="All" />
              {(Object.keys(STATUS_LABEL) as SeasonStatus[]).map((s) => (
                <StatusChip
                  key={s}
                  active={status === s}
                  onClick={() => setStatus(s)}
                  label={`${STATUS_LABEL[s]} ${fmt.int(data.counts[s])}`}
                />
              ))}
            </div>
          )}
        </div>
        {data && (
          <p className="text-xs text-muted">
            Keywords ({fmt.int(data.min_impressions)}+ impressions) whose impressions peak in the same calendar month
            <b className="font-medium text-foreground"> every year</b>. Google keeps 16 months, so today only{" "}
            <b className="font-medium text-foreground">{data.repeating_months.join(", ") || "no months"}</b> can be checked
            twice — the list grows as the app keeps syncing (stored history isn&apos;t deleted). &quot;Coming up&quot; = peak
            in the next 2 months: prepare content and pages now.
          </p>
        )}
      </div>
      {error && (
        <div className="px-4 pb-3">
          <Banner tone="error">{error}</Banner>
        </div>
      )}
      {loading && !data ? (
        <p className="px-4 pb-6 text-sm text-muted">{LOADING}</p>
      ) : data && !data.available ? (
        <p className="px-4 pb-6 text-sm text-muted">Sync at least a few months of data to find seasonal keywords.</p>
      ) : rows.length === 0 ? (
        <p className="px-4 pb-6 text-sm text-muted">No seasonal keywords found yet for these filters.</p>
      ) : (
        <table className="w-full table-fixed text-sm">
          <thead className="bg-surface text-xs text-muted">
            <tr className="border-b border-border">
              <th className="px-4 py-2 text-left font-normal">Keyword</th>
              <th className="hidden w-36 px-2 py-2 text-left font-normal sm:table-cell">Monthly impressions</th>
              <th className="w-28 px-2 py-2 text-left font-normal">Peaks in</th>
              <th className="w-24 px-4 py-2 text-right font-normal">Impr.</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {rows.map((r) => (
              <tr key={r.query} className="border-b border-border align-middle last:border-0">
                <td className="max-w-0 px-4 py-2">
                  <div className="flex items-center gap-2">
                    <BrandDot brand={r.brand} />
                    <span className="truncate" title={r.query}>
                      {r.query}
                    </span>
                  </div>
                  <span className={`ml-4 mt-1 inline-block rounded-full px-2 py-0.5 text-[11px] ${STATUS_STYLE[r.status]}`}>
                    {STATUS_LABEL[r.status]}
                  </span>
                </td>
                <td className="hidden px-2 py-2 sm:table-cell">
                  {data && (
                    <MonthBars
                      months={data.months}
                      values={r.impressions}
                      highlight={(m) => r.peak_months.includes(new Date(m + "T00:00:00").getMonth() + 1)}
                    />
                  )}
                </td>
                <td className="px-2 py-2">{r.peak_months.map((m) => MONTHS[m - 1]).join(", ")}</td>
                <td className="px-4 py-2 text-right">{fmt.int(r.total_impressions)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {data && <Footer shown={rows.length} total={data.total} loading={loading} onMore={more} />}
    </Card>
  );
}

function StatusChip({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-full border px-2.5 py-0.5 text-xs ${active ? "border-accent bg-accent-soft text-accent" : "border-border hover:bg-accent-soft"}`}
    >
      {label}
    </button>
  );
}

export function SpikesPanel({ propertyId, segment }: { propertyId: number; segment: QuerySegment }) {
  const { data, rows, error, loading, more } = usePaged<SpikeRow, SpikesResponse>(
    (offset) => api.spikes(propertyId, segment, PAGE_SIZE, offset),
    [propertyId, segment],
  );

  return (
    <Card className="overflow-hidden">
      <div className="space-y-2 px-4 pt-4 pb-3">
        <h2 className="text-sm font-medium">
          {data ? `${fmt.int(data.total)} one-off spikes` : "Spikes"}
          {loading && data && <span className="ml-2 font-normal text-muted">Updating…</span>}
        </h2>
        {data && (
          <p className="text-xs text-muted">
            Keywords ({fmt.int(data.min_impressions)}+ impressions) where a single month holds most of their impressions
            and it isn&apos;t a yearly pattern — newest first. Check them: spam or bot searches, a news moment, or a page
            that ranked briefly and dropped.
          </p>
        )}
      </div>
      {error && (
        <div className="px-4 pb-3">
          <Banner tone="error">{error}</Banner>
        </div>
      )}
      {loading && !data ? (
        <p className="px-4 pb-6 text-sm text-muted">{LOADING}</p>
      ) : rows.length === 0 ? (
        <p className="px-4 pb-6 text-sm text-muted">No spikes found for these filters.</p>
      ) : (
        <table className="w-full table-fixed text-sm">
          <thead className="bg-surface text-xs text-muted">
            <tr className="border-b border-border">
              <th className="px-4 py-2 text-left font-normal">Keyword</th>
              <th className="hidden w-36 px-2 py-2 text-left font-normal sm:table-cell">Monthly impressions</th>
              <th className="w-36 px-2 py-2 text-left font-normal">Spike</th>
              <th className="w-28 px-4 py-2 text-right font-normal">Impr. in spike</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {rows.map((r) => (
              <tr key={r.query} className="border-b border-border last:border-0">
                <td className="max-w-0 px-4 py-2">
                  <div className="flex items-center gap-2">
                    <BrandDot brand={r.brand} />
                    <span className="truncate" title={r.query}>
                      {r.query}
                    </span>
                  </div>
                </td>
                <td className="hidden px-2 py-2 sm:table-cell">
                  {data && <MonthBars months={data.months} values={r.impressions} highlight={(m) => m === r.spike_month} />}
                </td>
                <td className="px-2 py-2">
                  {fmt.month(r.spike_month)}
                  {data && r.spike_month === data.months[0] && (
                    <div className="text-[11px] text-muted" title="We can't see the months before this one">
                      history starts here — may be a lost ranking
                    </div>
                  )}
                  {data && r.spike_month === data.months[data.months.length - 1] && (
                    <div className="text-[11px] text-muted">latest month — may still be growing</div>
                  )}
                </td>
                <td className="px-4 py-2 text-right">
                  {fmt.int(r.spike_impressions)} <span className="text-xs text-muted">({Math.round(r.share * 100)}%)</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {data && <Footer shown={rows.length} total={data.total} loading={loading} onMore={more} />}
    </Card>
  );
}
