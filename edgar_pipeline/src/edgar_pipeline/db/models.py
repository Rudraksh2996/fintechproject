"""SQLAlchemy 2.0 schema; migration revisions remain independent schema snapshots."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cik: Mapped[str] = mapped_column(String(10), unique=True)
    ticker: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Insider(Base):
    __tablename__ = "insiders"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cik: Mapped[str] = mapped_column(String(10), unique=True)
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DetectionConfig(Base):
    __tablename__ = "detection_configs"
    __table_args__ = (
        Index(
            "uq_detection_configs_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        CheckConstraint(
            "window_days > 0 AND min_insiders >= 2 AND cap_insiders >= min_insiders",
            name="window_and_buyers",
        ),
        CheckConstraint(
            "min_insider_value_usd > 0 AND min_cluster_value_usd > 0", name="positive_thresholds"
        ),
        CheckConstraint(
            "value_cap_multiple > 1 AND holdings_cap > 0 AND new_position_pct > 0",
            name="positive_caps",
        ),
        CheckConstraint(
            "w_b >= 0 AND w_c >= 0 AND w_v >= 0 AND w_h >= 0 AND w_b + w_c + w_v + w_h = 1",
            name="weights",
        ),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    window_days: Mapped[int] = mapped_column(Integer, server_default="14")
    min_insiders: Mapped[int] = mapped_column(Integer, server_default="3")
    min_insider_value_usd: Mapped[Decimal] = mapped_column(Numeric(24, 6), server_default="25000")
    min_cluster_value_usd: Mapped[Decimal] = mapped_column(Numeric(24, 6), server_default="100000")
    include_ten_percent_owners: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    exclude_10b5_1: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    new_position_pct: Mapped[Decimal] = mapped_column(Numeric(18, 8), server_default="1")
    cap_insiders: Mapped[int] = mapped_column(Integer, server_default="8")
    value_cap_multiple: Mapped[Decimal] = mapped_column(Numeric(18, 8), server_default="100")
    holdings_cap: Mapped[Decimal] = mapped_column(Numeric(18, 8), server_default="0.5")
    w_b: Mapped[Decimal] = mapped_column(Numeric(9, 8), server_default="0.30")
    w_c: Mapped[Decimal] = mapped_column(Numeric(9, 8), server_default="0.25")
    w_v: Mapped[Decimal] = mapped_column(Numeric(9, 8), server_default="0.25")
    w_h: Mapped[Decimal] = mapped_column(Numeric(9, 8), server_default="0.20")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Form4Filing(Base):
    __tablename__ = "form4_filings"
    __table_args__ = (
        CheckConstraint("form_type IN ('4', '4/A')", name="form_type"),
        CheckConstraint("source IN ('synthetic', 'sec_edgar')", name="source"),
    )
    accession_number: Mapped[str] = mapped_column(String(32), primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    filing_date: Mapped[date] = mapped_column(Date)
    period_of_report: Mapped[date | None] = mapped_column(Date)
    form_type: Mapped[str] = mapped_column(String(3))
    supersedes_accession: Mapped[str | None] = mapped_column(
        ForeignKey("form4_filings.accession_number")
    )
    source: Mapped[str] = mapped_column(String(16))
    raw_xml_url: Mapped[str] = mapped_column(Text)
    raw_xml: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Form4Transaction(Base):
    __tablename__ = "form4_transactions"
    __table_args__ = (
        UniqueConstraint("accession_number", "line_number", name="uq_form4_accession_line"),
        Index("ix_form4_ticker_date", "ticker", "transaction_date"),
        Index("ix_form4_company_date", "company_id", "transaction_date"),
        Index("ix_form4_filing_date", "filing_date"),
        CheckConstraint("line_number > 0 AND shares >= 0", name="positive_line_shares"),
        CheckConstraint("acquired_disposed IN ('A', 'D')", name="acquired_disposed"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    accession_number: Mapped[str] = mapped_column(ForeignKey("form4_filings.accession_number"))
    line_number: Mapped[int] = mapped_column(Integer)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    insider_id: Mapped[int] = mapped_column(ForeignKey("insiders.id"))
    ticker: Mapped[str | None] = mapped_column(String(32))
    transaction_date: Mapped[date] = mapped_column(Date)
    filing_date: Mapped[date] = mapped_column(Date)
    transaction_code: Mapped[str] = mapped_column(String(1))
    acquired_disposed: Mapped[str] = mapped_column(String(1))
    shares: Mapped[Decimal] = mapped_column(Numeric(28, 8))
    price: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    value_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    shares_owned_after: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    pct_holdings_increase: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    is_director: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_officer: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_ten_percent_owner: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_other: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    officer_title: Mapped[str | None] = mapped_column(Text)
    is_csuite: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_10b5_1: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_amendment: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    superseded: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_new_position: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    missing_price: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    direct_or_indirect: Mapped[str | None] = mapped_column(String(1))
    footnote_refs: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    raw_xml_url: Mapped[str] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ClusterAlert(Base):
    __tablename__ = "cluster_alerts"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "window_start", "config_id", name="uq_cluster_window_config"
        ),
        CheckConstraint("status IN ('new', 'acknowledged', 'dismissed')", name="status"),
        CheckConstraint("conviction_score BETWEEN 0 AND 100", name="score"),
        CheckConstraint(
            "window_end >= window_start AND alert_filing_date >= first_filing_date", name="dates"
        ),
        Index("ix_cluster_alerts_filing_date", "alert_filing_date"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    ticker: Mapped[str] = mapped_column(String(32))
    window_start: Mapped[date] = mapped_column(Date)
    window_end: Mapped[date] = mapped_column(Date)
    first_filing_date: Mapped[date] = mapped_column(Date)
    alert_filing_date: Mapped[date] = mapped_column(Date)
    n_insiders: Mapped[int] = mapped_column(Integer)
    n_csuite: Mapped[int] = mapped_column(Integer)
    total_value_usd: Mapped[Decimal] = mapped_column(Numeric(28, 8))
    avg_pct_holdings_increase: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    conviction_score: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    score_breakdown: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    config_id: Mapped[int] = mapped_column(ForeignKey("detection_configs.id"))
    status: Mapped[str] = mapped_column(String(16), server_default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClusterAlertMember(Base):
    __tablename__ = "cluster_alert_members"
    alert_id: Mapped[int] = mapped_column(
        ForeignKey("cluster_alerts.id", ondelete="CASCADE"), primary_key=True
    )
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("form4_transactions.id"), primary_key=True
    )


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'completed', 'failed')", name="status"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(String(16))
    parameters: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), server_default="running")
    filings_seen: Mapped[int] = mapped_column(Integer, server_default="0")
    transactions_inserted: Mapped[int] = mapped_column(Integer, server_default="0")
    errors: Mapped[int] = mapped_column(Integer, server_default="0")
    error_detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ParseError(Base):
    __tablename__ = "parse_errors"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    accession_number: Mapped[str | None] = mapped_column(String(32))
    ingestion_run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    raw_xml_url: Mapped[str] = mapped_column(Text)
    raw_xml: Mapped[str] = mapped_column(Text)
    error_type: Mapped[str] = mapped_column(Text)
    error_detail: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PriceFetchRange(Base):
    __tablename__ = "price_fetch_ranges"
    __table_args__ = (CheckConstraint("end_date >= start_date", name="ordered_dates"),)
    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    start_date: Mapped[date] = mapped_column(Date, primary_key=True)
    end_date: Mapped[date] = mapped_column(Date, primary_key=True)


class PriceBar(Base):
    __tablename__ = "price_bars"
    __table_args__ = (CheckConstraint("close > 0", name="positive_close"),)
    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    close: Mapped[Decimal] = mapped_column(Numeric(28, 8))
    source: Mapped[str] = mapped_column(String(32))
