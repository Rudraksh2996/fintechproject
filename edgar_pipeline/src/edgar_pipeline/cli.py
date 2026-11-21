"""EDGAR command-line entry point for synthetic ingestion and database detection."""

import argparse
import json
from decimal import Decimal
from itertools import batched
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
from edgar_pipeline.db.repository import ingest
from edgar_pipeline.demo import fixtures, price_rows


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


def main() -> None:
    parser = argparse.ArgumentParser(prog="edgar")
    parser.add_argument("command", choices=["seed-demo", "detect"])
    args = parser.parse_args()
    settings = Settings()
    engine = create_engine(settings.database_url())
    try:
        with Session(engine) as db:
            if args.command == "seed-demo":
                if not settings.demo_mode:
                    parser.error("seed-demo requires DEMO_MODE=true")
                print(json.dumps(seed_demo(db, settings.seed)))
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
