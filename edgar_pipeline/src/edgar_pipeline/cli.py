"""EDGAR command-line entry point for synthetic ingestion and database detection."""

import argparse
import asyncio
import json
from datetime import date
from decimal import Decimal
from itertools import batched
from pathlib import Path
from statistics import mean

from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from edgar_pipeline.cluster_engine import Trade, detect
from edgar_pipeline.config import Settings
from edgar_pipeline.conviction import Config, executive_rank
from edgar_pipeline.db.models import (
    ClusterAlert,
    ClusterAlertMember,
    DetectionConfig,
    Form4Filing,
    Form4Transaction,
    IngestionRun,
    PriceBar,
)
from edgar_pipeline.db.repository import FilingInput, ingest
from edgar_pipeline.demo import fixtures, price_rows
from edgar_pipeline.discovery import by_index, by_issuer
from edgar_pipeline.http_client import SecClient


def seed_demo(db: Session, seed: int) -> dict[str, int]:
    run_id = ingest(db, fixtures(seed), "synthetic")
    for batch in batched(price_rows(seed), 500):
        stmt = insert(PriceBar).values(
            [{"ticker": t, "date": d, "close": p, "source": "synthetic"} for t, d, p in batch]
        )
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=[PriceBar.ticker, PriceBar.date],
                set_={"close": stmt.excluded.close},
                where=PriceBar.source == "synthetic",
            )
        )
    db.commit()
    run = db.get_one(IngestionRun, run_id)
    return {
        "run_id": run_id,
        "seen": run.filings_seen,
        "inserted": run.transactions_inserted,
        "quarantined": run.errors,
    }


def detect_database(db: Session, source: str) -> list[str]:
    db.execute(text("SELECT pg_advisory_xact_lock(733451)"))
    active = db.scalars(select(DetectionConfig).where(DetectionConfig.is_active)).one()
    config = Config(**{k: getattr(active, k) for k in Config.__dataclass_fields__})
    query = (
        select(Form4Transaction)
        .join(Form4Filing)
        .where(Form4Transaction.superseded.is_(False), Form4Filing.source == source)
    )
    trades = []
    tickers: dict[int, str] = {}
    for r in db.scalars(query):
        if not r.ticker:
            continue
        tickers[r.company_id] = r.ticker
        trades.append(
            Trade(
                r.id,
                r.company_id,
                r.insider_id,
                r.transaction_date,
                r.filing_date,
                r.value_usd,
                active.new_position_pct if r.is_new_position else r.pct_holdings_increase,
                r.officer_title or "",
                r.is_director,
                r.is_officer,
                r.is_ten_percent_owner,
                r.is_10b5_1,
            )
        )
    emitted = []
    for cluster in detect(trades, config):
        members = list(cluster.members.values())
        score, factors = cluster.score(config)
        ratios = [t.holdings for t in members if t.holdings is not None]
        values = {
            "company_id": cluster.company,
            "config_id": active.id,
            "ticker": tickers[cluster.company],
            "window_start": cluster.start,
            "window_end": cluster.end,
            "alert_filing_date": cluster.trigger,
            "first_filing_date": min(t.filed for t in members),
            "n_insiders": len({t.insider for t in members}),
            "n_csuite": len({t.insider for t in members if executive_rank(t.title)}),
            "avg_pct_holdings_increase": mean(ratios) if ratios else None,
            "total_value_usd": sum(t.value or Decimal(0) for t in members),
            "conviction_score": score,
            "score_breakdown": factors,
        }
        stmt = insert(ClusterAlert).values(**values)
        alert_id = db.scalars(
            stmt.on_conflict_do_update(
                constraint="uq_cluster_window_config",
                set_={
                    k: stmt.excluded[k]
                    for k in values
                    if k not in {"company_id", "config_id", "window_start"}
                },
            ).returning(ClusterAlert.id)
        ).one()
        db.execute(delete(ClusterAlertMember).where(ClusterAlertMember.alert_id == alert_id))
        db.execute(
            insert(ClusterAlertMember),
            [{"alert_id": alert_id, "transaction_id": t.id} for t in members],
        )
        emitted.append(tickers[cluster.company])
    db.commit()
    return sorted(emitted)


async def live_ingest(
    db: Session,
    settings: Settings,
    start: date,
    end: date,
    issuer: str | None,
    quarterly: bool,
    cache: Path,
) -> list[int]:
    client = SecClient(settings.sec_user_agent, cache, settings.sec_max_rps)
    try:
        refs = (
            await by_issuer(client, issuer, start, end)
            if issuer
            else await by_index(client, start, end, "quarterly" if quarterly else "daily")
        )
        runs = []
        for batch in batched(refs, 50):
            inputs = [
                FilingInput(
                    ref.accession, ref.filing_date, ref.xml_url, await client.get(ref.xml_url)
                )
                for ref in batch
            ]
            runs.append(ingest(db, inputs, "sec_edgar"))
        return runs
    finally:
        await client.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="edgar")
    parser.add_argument("command", choices=["seed-demo", "detect", "ingest", "backfill"])
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--issuer", help="Ticker or numeric issuer CIK")
    parser.add_argument("--cache", type=Path, default=Path(".cache/edgar"))
    args = parser.parse_args()
    settings = Settings()
    engine = create_engine(settings.database_url())
    try:
        with Session(engine) as db:
            if args.command == "seed-demo":
                if not settings.demo_mode:
                    parser.error("seed-demo requires DEMO_MODE=true")
                print(json.dumps(seed_demo(db, settings.seed)))
            elif args.command in {"ingest", "backfill"}:
                if settings.demo_mode or settings.sec_user_agent == "YourOrg you@example.com":
                    parser.error("Live ingestion requires DEMO_MODE=false and a real SEC contact")
                if args.start is None or args.end is None:
                    parser.error("Live ingestion requires --start and --end dates")
                print(
                    json.dumps(
                        {
                            "runs": asyncio.run(
                                live_ingest(
                                    db,
                                    settings,
                                    args.start,
                                    args.end,
                                    args.issuer,
                                    args.command == "backfill",
                                    args.cache,
                                )
                            )
                        }
                    )
                )
            else:
                print(
                    json.dumps(
                        {
                            "alerts": detect_database(
                                db, "synthetic" if settings.demo_mode else "sec_edgar"
                            )
                        }
                    )
                )
    finally:
        engine.dispose()
