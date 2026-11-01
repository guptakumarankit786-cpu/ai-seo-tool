from collections import defaultdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.gsc import ga4, google_api
from app.gsc.router import Compare, PeriodDep
from app.models import GscProperty

router = APIRouter(prefix="/api/gsc/properties/{property_id}", tags=["ga4"])

DbDep = Annotated[Session, Depends(get_db)]


class Ga4Metrics(BaseModel):
    sessions: int = 0
    key_events: int = 0
    orders: int = 0
    revenue: float = 0.0


class AiSource(Ga4Metrics):
    assistant: str
    previous: Ga4Metrics | None  # null with no comparison


class AiPage(Ga4Metrics):
    url: str  # https://host/path as GA4 recorded it
    assistant: str  # the assistant bringing most of its sessions
    previous_sessions: int | None


class AiDay(BaseModel):
    date: date
    sessions: int


class AiTrafficOut(BaseModel):
    linked: bool  # false: no GA4 property linked for this client
    ga4_name: str | None = None
    currency: str | None = None
    revenue_tracked: bool = True  # false when GA4 counts orders but no order value
    start_date: date
    end_date: date
    compare: Compare
    compare_start: date | None
    compare_end: date | None
    totals: Ga4Metrics = Ga4Metrics()  # free AI assistant visits (ChatGPT ads not included)
    previous: Ga4Metrics | None = None
    all_sessions: int = 0  # every channel, for the AI share
    previous_all_sessions: int | None = None
    assistants: list[AiSource] = []  # most sessions first
    ads: AiSource | None = None  # ChatGPT ads (paid), kept apart from free AI visits
    daily: list[AiDay] = []
    previous_daily: list[AiDay] = []
    pages: list[AiPage] = []  # top landing pages of free AI visits
    error: str | None = None


def _add(total: Ga4Metrics, row: dict) -> None:
    total.sessions += int(row["sessions"])
    total.key_events += int(row["key_events"])
    total.orders += int(row["orders"])
    total.revenue += row["revenue"]


@router.get("/ai-traffic", response_model=AiTrafficOut)
def ai_traffic(property_id: int, db: DbDep, period: PeriodDep, pages_limit: int = 50):
    """Visits from AI assistants (ChatGPT, Gemini, Perplexity, Claude, Copilot…) from the client's GA4."""
    prop = db.get(GscProperty, property_id)
    if not prop:
        raise HTTPException(404, "Property not found")
    out = AiTrafficOut(
        linked=prop.ga4_property_id is not None,
        start_date=period.start,
        end_date=period.end,
        compare=period.compare,
        compare_start=period.compare_start,
        compare_end=period.compare_end,
    )
    try:
        report = ga4.ai_traffic(db, prop, period.start, period.end, period.compare_start, period.compare_end)
    except google_api.GoogleAPIError as exc:
        out.error = f"Couldn't read GA4: {exc}"[:300]
        return out
    if report is None:
        return out

    has_compare = period.compare_start is not None
    by_source: dict[tuple[str, str], Ga4Metrics] = defaultdict(Ga4Metrics)
    days: dict[tuple[str, date], int] = defaultdict(int)
    pages: dict[tuple[str, str], Ga4Metrics] = defaultdict(Ga4Metrics)
    page_prev: dict[tuple[str, str], int] = defaultdict(int)
    page_assistants: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    totals = {"now": Ga4Metrics(), "before": Ga4Metrics()}
    for r in report["rows"]:
        w = r["window"]
        _add(by_source[(w, r["assistant"])], r)
        if r["assistant"] == ga4.ADS:
            continue
        _add(totals[w], r)
        days[(w, r["date"])] += int(r["sessions"])
        key = (r["host"], r["path"])
        if w == "now":
            _add(pages[key], r)
            page_assistants[key][r["assistant"]] += int(r["sessions"])
        else:
            page_prev[key] += int(r["sessions"])

    def source(name: str) -> AiSource:
        return AiSource(assistant=name, **by_source[("now", name)].model_dump(), previous=by_source[("before", name)] if has_compare else None)

    names = {name for _, name in by_source}
    out.ga4_name, out.currency = report["name"], report["currency"]
    out.totals = totals["now"]
    out.previous = totals["before"] if has_compare else None
    out.revenue_tracked = not (out.totals.orders > 0 and out.totals.revenue == 0)
    out.all_sessions = report["all_sessions"]["now"]
    out.previous_all_sessions = report["all_sessions"]["before"] if has_compare else None
    out.assistants = sorted((source(n) for n in names - {ga4.ADS}), key=lambda s: (-s.sessions, s.assistant))
    out.ads = source(ga4.ADS) if ga4.ADS in names else None
    out.daily = [AiDay(date=d, sessions=s) for (w, d), s in sorted(days.items()) if w == "now"]
    out.previous_daily = [AiDay(date=d, sessions=s) for (w, d), s in sorted(days.items()) if w == "before"]
    top = sorted(pages.items(), key=lambda kv: (-kv[1].sessions, -kv[1].revenue, kv[0]))[:pages_limit]
    out.pages = [
        AiPage(
            url=f"https://{host}{path}" if path.startswith("/") else path,
            assistant=max(page_assistants[(host, path)].items(), key=lambda kv: kv[1])[0],
            previous_sessions=page_prev.get((host, path), 0) if has_compare else None,
            **m.model_dump(),
        )
        for (host, path), m in top
    ]
    return out


# ---------- GA4 overview (all channels) ----------


class Ga4Totals(Ga4Metrics):
    users: int = 0
    engaged_sessions: int = 0


class Ga4Channel(Ga4Totals):
    channel: str
    previous_sessions: int | None


class Ga4Page(Ga4Totals):
    url: str


class Ga4Device(Ga4Totals):
    device: str


class Ga4OverviewOut(BaseModel):
    linked: bool
    ga4_name: str | None = None
    currency: str | None = None
    revenue_tracked: bool = True
    start_date: date
    end_date: date
    compare: Compare
    compare_start: date | None
    compare_end: date | None
    totals: Ga4Totals = Ga4Totals()
    previous: Ga4Totals | None = None
    channels: list[Ga4Channel] = []  # most sessions first
    daily: list[AiDay] = []
    previous_daily: list[AiDay] = []
    pages: list[Ga4Page] = []  # top landing pages, all channels
    devices: list[Ga4Device] = []
    unassigned_share: float = 0.0  # sessions GA4 couldn't give a channel (a tracking problem when high)
    error: str | None = None


def _totals(values: dict) -> Ga4Totals:
    return Ga4Totals(**{k: (v if k == "revenue" else int(v)) for k, v in values.items()})


@router.get("/ga4-overview", response_model=Ga4OverviewOut)
def ga4_overview(property_id: int, db: DbDep, period: PeriodDep):
    """The client's GA4 across every channel: totals, channels, daily sessions, top landing pages, devices."""
    prop = db.get(GscProperty, property_id)
    if not prop:
        raise HTTPException(404, "Property not found")
    out = Ga4OverviewOut(
        linked=prop.ga4_property_id is not None,
        start_date=period.start,
        end_date=period.end,
        compare=period.compare,
        compare_start=period.compare_start,
        compare_end=period.compare_end,
    )
    try:
        report = ga4.overview(db, prop, period.start, period.end, period.compare_start, period.compare_end)
    except google_api.GoogleAPIError as exc:
        out.error = f"Couldn't read GA4: {exc}"[:300]
        return out
    if report is None:
        return out

    has_compare = period.compare_start is not None
    channels = {r["channel"]: r for r in report["channels"] if r["window"] == "now"}
    prev_channel = {r["channel"]: r["sessions"] for r in report["channels"] if r["window"] == "before"}

    out.ga4_name, out.currency = report["name"], report["currency"]
    out.totals = _totals(report["totals"].get("now", {}))
    out.previous = _totals(report["totals"].get("before", {})) if has_compare else None
    out.revenue_tracked = not (out.totals.orders > 0 and out.totals.revenue == 0)
    out.channels = sorted(
        (
            Ga4Channel(
                channel=name,
                previous_sessions=int(prev_channel.get(name, 0)) if has_compare else None,
                **_totals({f: v[f] for f in ga4.OVERVIEW_FIELDS}).model_dump(),
            )
            for name, v in channels.items()
        ),
        key=lambda c: (-c.sessions, c.channel),
    )
    days = sorted(report["daily"], key=lambda r: r["date"])
    out.daily = [AiDay(date=r["date"], sessions=int(r["sessions"])) for r in days if r["window"] == "now"]
    out.previous_daily = [AiDay(date=r["date"], sessions=int(r["sessions"])) for r in days if r["window"] == "before"]
    out.pages = [
        Ga4Page(
            url=f"https://{p['host']}{p['path']}" if p["path"].startswith("/") else p["path"],
            **_totals({f: p[f] for f in ga4.OVERVIEW_FIELDS}).model_dump(),
        )
        for p in report["pages"]
    ]
    out.devices = [Ga4Device(device=d["device"], **_totals({f: d[f] for f in ga4.OVERVIEW_FIELDS}).model_dump()) for d in report["devices"]]
    if out.totals.sessions and "Unassigned" in channels:
        out.unassigned_share = channels["Unassigned"]["sessions"] / out.totals.sessions
    return out
