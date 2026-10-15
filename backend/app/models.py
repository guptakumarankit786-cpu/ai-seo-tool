from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class OAuthState(Base):
    """Short-lived CSRF state for an in-flight OAuth redirect."""

    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GoogleConnection(Base):
    """A Google account the user has authorised for Search Console access."""

    __tablename__ = "google_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    scopes: Mapped[str] = mapped_column(Text)
    refresh_token_enc: Mapped[str] = mapped_column(Text)
    access_token_enc: Mapped[str | None] = mapped_column(Text)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    properties: Mapped[list["GscProperty"]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )


class GscProperty(Base):
    """A Search Console property (domain or URL-prefix) visible to a connection."""

    __tablename__ = "gsc_properties"
    __table_args__ = (UniqueConstraint("connection_id", "site_url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("google_connections.id", ondelete="CASCADE"))
    site_url: Mapped[str] = mapped_column(String(2048))
    permission_level: Mapped[str] = mapped_column(String(64))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Terms that mark a query as "brand". Null = not set yet (a suggestion from the domain is used).
    brand_terms: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    # Competitor names; queries containing one are tagged "competitor". Null/empty = none set.
    competitor_terms: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    connection: Mapped[GoogleConnection] = relationship(back_populates="properties")


class GscSyncRun(Base):
    __tablename__ = "gsc_sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("gsc_properties.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16))  # running | success | failed
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    rows_written: Mapped[int] = mapped_column(Integer, default=0)
    # Long ranges are fetched in ~monthly chunks; progress for the UI.
    chunks_total: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    chunks_done: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GscDailyMetric(Base):
    """Site-level totals per day."""

    __tablename__ = "gsc_daily_metrics"

    property_id: Mapped[int] = mapped_column(
        ForeignKey("gsc_properties.id", ondelete="CASCADE"), primary_key=True
    )
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    clicks: Mapped[int] = mapped_column(Integer)
    impressions: Mapped[int] = mapped_column(Integer)
    ctr: Mapped[float] = mapped_column(Float)
    position: Mapped[float] = mapped_column(Float)


class GscQueryMetric(Base):
    """Per-day, per-query metrics."""

    __tablename__ = "gsc_query_metrics"
    __table_args__ = (Index("ix_gsc_query_metrics_property_date", "property_id", "date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("gsc_properties.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)
    query: Mapped[str] = mapped_column(Text)
    # Lower-cased, spaces/punctuation stripped; filled by Postgres so keyword matching
    # (brand terms, keyword types) doesn't re-run a regex over millions of rows per request.
    query_norm: Mapped[str] = mapped_column(
        Text, Computed(r"regexp_replace(lower(query), '[[:space:][:punct:]]', '', 'g')", persisted=True)
    )
    clicks: Mapped[int] = mapped_column(Integer)
    impressions: Mapped[int] = mapped_column(Integer)
    ctr: Mapped[float] = mapped_column(Float)
    position: Mapped[float] = mapped_column(Float)


class GscPageMetric(Base):
    """Per-day, per-page metrics."""

    __tablename__ = "gsc_page_metrics"
    __table_args__ = (Index("ix_gsc_page_metrics_property_date", "property_id", "date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("gsc_properties.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)
    page: Mapped[str] = mapped_column(Text)
    clicks: Mapped[int] = mapped_column(Integer)
    impressions: Mapped[int] = mapped_column(Integer)
    ctr: Mapped[float] = mapped_column(Float)
    position: Mapped[float] = mapped_column(Float)


class GscInspectionRun(Base):
    """One pass of URL discovery + URL Inspection for a property."""

    __tablename__ = "gsc_inspection_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("gsc_properties.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16))  # running | success | partial | failed
    urls_known: Mapped[int] = mapped_column(Integer, default=0)
    urls_queued: Mapped[int] = mapped_column(Integer, default=0)
    urls_inspected: Mapped[int] = mapped_column(Integer, default=0)
    urls_failed: Mapped[int] = mapped_column(Integer, default=0)
    quota_exhausted: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GscUrlInspection(Base):
    """Latest URL Inspection result for one URL known to belong to a property."""

    __tablename__ = "gsc_url_inspections"
    __table_args__ = (
        UniqueConstraint("property_id", "url"),
        Index("ix_gsc_url_inspections_property_state", "property_id", "coverage_state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("gsc_properties.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(Text)
    in_sitemap: Mapped[bool] = mapped_column(Boolean, default=False)
    in_search: Mapped[bool] = mapped_column(Boolean, default=False)
    # Null until inspected.
    coverage_state: Mapped[str | None] = mapped_column(String(255))
    verdict: Mapped[str | None] = mapped_column(String(32))
    indexing_state: Mapped[str | None] = mapped_column(String(64))
    robots_txt_state: Mapped[str | None] = mapped_column(String(64))
    page_fetch_state: Mapped[str | None] = mapped_column(String(64))
    google_canonical: Mapped[str | None] = mapped_column(Text)
    user_canonical: Mapped[str | None] = mapped_column(Text)
    last_crawl_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    inspected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class GscIndexingExport(Base):
    """An uploaded Search Console "Page indexing" export.

    kind="overview": the main report (reasons table + chart totals).
    kind="issue":    a drill-down for one reason (list of example URLs).
    """

    __tablename__ = "gsc_indexing_exports"

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("gsc_properties.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    filename: Mapped[str] = mapped_column(String(255))
    issue: Mapped[str | None] = mapped_column(String(255))  # for kind="issue"
    chart_date: Mapped[date | None] = mapped_column(Date)
    indexed: Mapped[int | None] = mapped_column(Integer)
    not_indexed: Mapped[int | None] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    reasons: Mapped[list["GscIndexingExportReason"]] = relationship(cascade="all, delete-orphan")
    urls: Mapped[list["GscIndexingExportUrl"]] = relationship(cascade="all, delete-orphan")


class GscIndexingExportReason(Base):
    __tablename__ = "gsc_indexing_export_reasons"

    id: Mapped[int] = mapped_column(primary_key=True)
    export_id: Mapped[int] = mapped_column(ForeignKey("gsc_indexing_exports.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(String(255))
    source: Mapped[str | None] = mapped_column(String(64))
    validation: Mapped[str | None] = mapped_column(String(64))
    pages: Mapped[int] = mapped_column(Integer)
    critical: Mapped[bool | None] = mapped_column(Boolean)


class GscIndexingExportUrl(Base):
    __tablename__ = "gsc_indexing_export_urls"

    id: Mapped[int] = mapped_column(primary_key=True)
    export_id: Mapped[int] = mapped_column(ForeignKey("gsc_indexing_exports.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    last_crawled: Mapped[date | None] = mapped_column(Date)


class GscKeywordCacheEntry(Base):
    """One tagged keyword-explorer result set, keyed by window/compare/brand terms.

    Building the set takes seconds on large sites; filtering, sorting and paging it is cheap,
    so the explorer reuses it until the property is re-synced or the key changes.
    """

    __tablename__ = "gsc_keyword_cache_entries"
    __table_args__ = (UniqueConstraint("property_id", "cache_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("gsc_properties.id", ondelete="CASCADE"))
    cache_key: Mapped[str] = mapped_column(String(255))
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GscKeywordCacheRow(Base):
    """Rows of a cached keyword set. UNLOGGED: it's a rebuildable cache, so skip WAL writes."""

    __tablename__ = "gsc_keyword_cache_rows"
    __table_args__ = {"prefixes": ["UNLOGGED"]}

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("gsc_keyword_cache_entries.id", ondelete="CASCADE"), index=True
    )
    query: Mapped[str] = mapped_column(Text)
    clicks: Mapped[int] = mapped_column(Integer)
    impressions: Mapped[int] = mapped_column(Integer)
    ctr: Mapped[float] = mapped_column(Float)
    position: Mapped[float | None] = mapped_column(Float)
    prev_clicks: Mapped[int | None] = mapped_column(Integer)
    prev_impressions: Mapped[int | None] = mapped_column(Integer)
    prev_position: Mapped[float | None] = mapped_column(Float)
    expected_ctr: Mapped[float | None] = mapped_column(Float)
    click_change: Mapped[int] = mapped_column(Integer)
    brand: Mapped[bool] = mapped_column(Boolean)
    t_long_tail: Mapped[bool] = mapped_column(Boolean)
    t_question: Mapped[bool] = mapped_column(Boolean)
    t_buying: Mapped[bool] = mapped_column(Boolean)
    t_new: Mapped[bool] = mapped_column(Boolean)
    t_lost: Mapped[bool] = mapped_column(Boolean)
    t_rising: Mapped[bool] = mapped_column(Boolean)
    t_declining: Mapped[bool] = mapped_column(Boolean)
    t_low_ctr: Mapped[bool] = mapped_column(Boolean)
    t_zero_clicks: Mapped[bool] = mapped_column(Boolean)
    t_high_performance: Mapped[bool] = mapped_column(Boolean)
    t_competitor: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class GscQueryPageCacheEntry(Base):
    """A live query+page pull from Search Console for one date range.

    Query+page data is too large to keep for 16 months, so it's fetched from Google when a
    page-level view (striking distance, cannibalisation) is opened and kept briefly.
    """

    __tablename__ = "gsc_query_page_cache_entries"
    __table_args__ = (UniqueConstraint("property_id", "start_date", "end_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("gsc_properties.id", ondelete="CASCADE"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GscQueryPageCacheRow(Base):
    """Rows of a live query+page pull. UNLOGGED: a rebuildable cache."""

    __tablename__ = "gsc_query_page_cache_rows"
    __table_args__ = {"prefixes": ["UNLOGGED"]}

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("gsc_query_page_cache_entries.id", ondelete="CASCADE"), index=True
    )
    query: Mapped[str] = mapped_column(Text)
    query_norm: Mapped[str] = mapped_column(
        Text, Computed(r"regexp_replace(lower(query), '[[:space:][:punct:]]', '', 'g')", persisted=True)
    )
    page: Mapped[str] = mapped_column(Text)
    clicks: Mapped[int] = mapped_column(Integer)
    impressions: Mapped[int] = mapped_column(Integer)
    position: Mapped[float] = mapped_column(Float)


class GscMonthlyKeywordCache(Base):
    """Monthly impressions/clicks per keyword over the stored history, for seasonal and spike views.

    Aggregating millions of daily rows by month takes seconds, so it's built once per sync.
    `series` maps keyword -> {"impressions": [...], "clicks": [...]} aligned with `months`.
    """

    __tablename__ = "gsc_monthly_keyword_cache"

    property_id: Mapped[int] = mapped_column(
        ForeignKey("gsc_properties.id", ondelete="CASCADE"), primary_key=True
    )
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    months: Mapped[list[date]] = mapped_column(ARRAY(Date))
    series: Mapped[dict] = mapped_column(JSONB)
