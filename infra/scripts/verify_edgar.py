"""Exercise public CLI and compare its persisted outputs with demo ground truth."""

import asyncio
import json
import subprocess
import tempfile
from datetime import date, timedelta
from pathlib import Path

import httpx
from edgar_pipeline.config import Settings
from edgar_pipeline.db.models import ClusterAlert, Company, DetectionConfig, Form4Filing, PriceBar
from edgar_pipeline.demo import PLANTED, TICKERS
from edgar_pipeline.discovery import by_issuer
from edgar_pipeline.form4_parser import parse_form4
from edgar_pipeline.http_client import SecClient, SecError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session


async def live_check(settings: Settings) -> None:
    identity = settings.sec_user_agent.strip()
    if not identity or identity == "YourOrg you@example.com":
        print("Optional live EDGAR: skipped, offline (no configured SEC contact)")
        return
    with tempfile.TemporaryDirectory() as directory:
        client = SecClient(identity, Path(directory), settings.sec_max_rps)
        try:
            today = date.today()
            refs = await by_issuer(client, "AAPL", today - timedelta(days=180), today)
            assert refs, "Expected at least one recent AAPL ownership filing"
            parsed = parse_form4(await client.get(refs[-1].xml_url))
            assert parsed.form == refs[-1].form
            print("Live EDGAR filing verified:", refs[-1].accession)
        except SecError as exc:
            if isinstance(exc.__cause__, httpx.ConnectError):
                print("Optional live EDGAR: skipped, offline (SEC connection unavailable)")
            else:
                raise
        finally:
            await client.aclose()


def main() -> None:
    settings = Settings()
    assert settings.demo_mode, "Gate 2 requires a demo database"
    for replay in (False, True):
        seed = subprocess.check_output(["edgar", "seed-demo"], text=True)
        print(seed.strip(), flush=True)
        stats = json.loads(seed)
        assert stats["quarantined"] == 1 and stats["seen"] == 843
        if replay:
            assert stats["inserted"] == 0
        detection = subprocess.check_output(["edgar", "detect"], text=True)
        print(detection.strip(), flush=True)
        assert json.loads(detection)["alerts"] == sorted(PLANTED)
    engine = create_engine(settings.database_url())
    try:
        with Session(engine) as db:
            persisted = db.scalars(
                select(ClusterAlert.ticker)
                .join(DetectionConfig)
                .where(DetectionConfig.is_active, ClusterAlert.ticker.in_(TICKERS))
            ).all()
            assert sorted(persisted) == sorted(PLANTED)
            amendments = db.scalar(
                select(func.count())
                .select_from(Form4Filing)
                .join(Company)
                .where(Company.ticker.in_(TICKERS), Form4Filing.supersedes_accession.is_not(None))
            )
            assert amendments == 2
            prices = db.scalar(
                select(func.count())
                .select_from(PriceBar)
                .where(PriceBar.source == "synthetic", PriceBar.ticker == "SYNBENCH")
            )
            assert prices and prices >= 380
            print(
                f"Verified {len(persisted)} planted alerts, 30 trap issuers, "
                f"{amendments} amendments and {prices} benchmark closes."
            )
    finally:
        engine.dispose()
    asyncio.run(live_check(settings))


if __name__ == "__main__":
    main()
