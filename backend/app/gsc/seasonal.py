"""Seasonal keywords and one-off spikes, from monthly impressions over the stored history.

Search Console keeps 16 months, so a calendar month only appears twice for a few months of the
year. A keyword counts as seasonal only when its peak *repeats* in those months in both years;
the rest of the "only busy for a few months" keywords are one-off spikes (spam/bot searches,
short-lived rankings) and are reported separately. Detection improves as the app keeps syncing,
because stored history isn't deleted when Google drops it.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from statistics import median
from typing import Literal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import GscDailyMetric, GscMonthlyKeywordCache, GscProperty

MIN_TOTAL_IMPRESSIONS = 1_000  # keywords considered: this many impressions over the full months
SEASONAL_PEAK_FACTOR = 2  # a peak month has at least 2x the keyword's median month …
SEASONAL_MIN_PEAK = 100  # … and at least 100 impressions, in every year it appears …
SEASONAL_LOCAL_FACTOR = 1.25  # … and stands out from the months either side (a peak, not a plateau)
SPIKE_MIN_SHARE = 0.6  # one month holds 60%+ of all impressions …
SPIKE_FACTOR = 5  # … and is 5x+ the keyword's median of the other months
COMING_UP_MONTHS = 2

Status = Literal["in_season", "coming_up", "off_season"]


def full_month_range(first: date, last: date) -> tuple[date, date] | None:
    """[start, end) covering only complete calendar months between first and last stored days."""
    start = first if first.day == 1 else (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    end = last + timedelta(days=1) if (last + timedelta(days=1)).day == 1 else last.replace(day=1)
    return (start, end) if start < end else None


def build_monthly(db: Session, prop: GscProperty) -> GscMonthlyKeywordCache | None:
    """Aggregate monthly impressions/clicks per keyword (keywords above the threshold only)."""
    first, last = db.execute(
        select(func.min(GscDailyMetric.date), func.max(GscDailyMetric.date)).where(
            GscDailyMetric.property_id == prop.id
        )
    ).one()
    if first is None or not (span := full_month_range(first, last)):
        return None
    start, end = span

    db.execute(text("set local jit = off"))
    db.execute(text("set local work_mem = '128MB'"))
    rows = db.execute(
        text(
            """
            with m as (
                select query, date_trunc('month', date)::date as month,
                       sum(impressions) as impressions, sum(clicks) as clicks
                from gsc_query_metrics
                where property_id = :pid and date >= :start and date < :end
                group by 1, 2
            ),
            keep as (select query from m group by query having sum(impressions) >= :min_total)
            select m.* from m join keep using (query)
            """
        ),
        {"pid": prop.id, "start": start, "end": end, "min_total": MIN_TOTAL_IMPRESSIONS},
    ).all()

    months: list[date] = []
    month = start
    while month < end:
        months.append(month)
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    index = {m: i for i, m in enumerate(months)}
    series: dict[str, dict[str, list[int]]] = {}
    for r in rows:
        s = series.setdefault(r.query, {"impressions": [0] * len(months), "clicks": [0] * len(months)})
        s["impressions"][index[r.month]] = int(r.impressions)
        s["clicks"][index[r.month]] = int(r.clicks)

    cache = db.get(GscMonthlyKeywordCache, prop.id)
    if cache is None:
        cache = GscMonthlyKeywordCache(property_id=prop.id)
        db.add(cache)
    cache.months = months
    cache.series = series
    cache.built_at = datetime.now(UTC)
    db.commit()
    return cache


def monthly(db: Session, prop: GscProperty) -> GscMonthlyKeywordCache | None:
    cache = db.get(GscMonthlyKeywordCache, prop.id)
    if cache and (prop.last_synced_at is None or cache.built_at >= prop.last_synced_at):
        return cache
    return build_monthly(db, prop)


def repeating_months(months: list[date]) -> list[int]:
    """Calendar months (1-12) that appear at least twice in the history."""
    seen: dict[int, int] = {}
    for m in months:
        seen[m.month] = seen.get(m.month, 0) + 1
    return sorted(m for m, n in seen.items() if n >= 2)


@dataclass
class Seasonal:
    query: str
    peak_months: list[int]
    status: Status


@dataclass
class Spike:
    query: str
    month: date
    impressions: int
    share: float


def status_for(peak_months: list[int], today: date) -> Status:
    if today.month in peak_months:
        return "in_season"
    upcoming = {(today.month - 1 + k) % 12 + 1 for k in range(1, COMING_UP_MONTHS + 1)}
    return "coming_up" if upcoming & set(peak_months) else "off_season"


def _is_local_peak(impressions: list[int], i: int) -> bool:
    neighbours = [impressions[j] for j in (i - 1, i + 1) if 0 <= j < len(impressions)]
    return not neighbours or impressions[i] >= SEASONAL_LOCAL_FACTOR * (sum(neighbours) / len(neighbours))


def find_seasonal(query: str, months: list[date], impressions: list[int], today: date) -> Seasonal | None:
    """Seasonal if, for a calendar month seen in both years, the keyword peaked there every time."""
    typical = median(impressions)
    threshold = max(SEASONAL_MIN_PEAK, SEASONAL_PEAK_FACTOR * typical)
    peaks = [
        cal
        for cal in repeating_months(months)
        if all(
            impressions[i] >= threshold and _is_local_peak(impressions, i)
            for i, m in enumerate(months)
            if m.month == cal
        )
    ]
    if not peaks:
        return None
    return Seasonal(query, peaks, status_for(peaks, today))


def find_spike(query: str, months: list[date], impressions: list[int]) -> Spike | None:
    total = sum(impressions)
    if not total:
        return None
    i = max(range(len(impressions)), key=impressions.__getitem__)
    others = impressions[:i] + impressions[i + 1 :]
    if impressions[i] / total < SPIKE_MIN_SHARE:
        return None
    if others and impressions[i] < SPIKE_FACTOR * max(median(others), 1):
        return None
    return Spike(query, months[i], impressions[i], impressions[i] / total)
