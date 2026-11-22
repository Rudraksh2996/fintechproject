"""Optional live EDGAR verification. Use a separate Postgres database for live rows."""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from edgar_pipeline.cli import live_ingest
from edgar_pipeline.config import Settings
from edgar_pipeline.db.models import Form4Filing, Form4Transaction, IngestionRun
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session


def main() -> None:
    settings = Settings()
    contact = settings.sec_user_agent.strip()
    if not contact or "example.com" in contact.lower() or "@" not in contact:
        print("Live EDGAR: skipped (no real SEC_USER_AGENT in .env)")
        return
    live = Settings.model_validate(
        {**settings.model_dump(), "demo_mode": False, "sec_max_rps": min(8, settings.sec_max_rps)}
    )
    day = datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    engine = create_engine(live.database_url())
    try:
        with Session(engine) as db:
            ids = asyncio.run(live_ingest(db, live, day, day, None, False, Path(".cache/edgar")))
            runs = list(db.scalars(select(IngestionRun).where(IngestionRun.id.in_(ids))))
            seen = sum(r.filings_seen for r in runs)
            errors = sum(r.errors for r in runs)
            purchases = db.scalar(
                select(func.count())
                .select_from(Form4Transaction)
                .join(Form4Filing)
                .where(
                    Form4Filing.source == "sec_edgar",
                    Form4Filing.filing_date == day,
                    Form4Transaction.transaction_code == "P",
                )
            )
            print(
                json.dumps(
                    {
                        "live_sec_day": str(day),
                        "rps_cap": live.sec_max_rps,
                        "fetched": seen,
                        "parsed": seen - errors,
                        "quarantined": errors,
                        "p_transactions": purchases,
                    }
                )
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
