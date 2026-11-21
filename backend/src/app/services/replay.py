"""Ingest a second synthetic season, one chronological batch at a time."""

import asyncio
import logging
from datetime import timedelta
from itertools import groupby

from edgar_pipeline.cli import detect_database, store_demo_prices
from edgar_pipeline.db.models import IngestionRun
from edgar_pipeline.db.repository import FilingInput, IngestionError, ingest
from edgar_pipeline.demo import START, fixtures
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

# A whole number of weeks keeps each filing on the same weekday as the seed season.
REPLAY_START = START + timedelta(weeks=104)


def apply_batch(engine: Engine, seed: int, week: int, filings: list[FilingInput]) -> None:
    with engine.begin() as conn, Session(bind=conn, join_transaction_mode="create_savepoint") as db:
        db.execute(text("SELECT pg_advisory_xact_lock(733452)"))
        marker = {"seed": seed, "week": week}
        if (
            db.scalar(
                select(IngestionRun.id).where(
                    IngestionRun.source == "demo_replay", IngestionRun.parameters == marker
                )
            )
            is not None
        ):
            return
        if week == 0:
            store_demo_prices(db, seed, REPLAY_START)
        ingest(db, filings, "synthetic")
        detect_database(db, "synthetic")
        db.add(IngestionRun(source="demo_replay", parameters=marker, status="completed"))
        db.commit()


async def replay(engine: Engine, seed: int, speed: float, stopping: asyncio.Event) -> None:
    batches = groupby(fixtures(seed, REPLAY_START), lambda f: (f.filed - REPLAY_START).days // 7)
    for week, entries in batches:
        batch = list(entries)
        while not stopping.is_set():
            try:
                await asyncio.to_thread(apply_batch, engine, seed, week, batch)
                break
            except (IngestionError, SQLAlchemyError):
                logging.getLogger("gateway").exception("Could not commit demo week %d", week)
                await asyncio.sleep(1)
        if stopping.is_set():
            return
        try:
            await asyncio.wait_for(stopping.wait(), 1 / speed)
        except TimeoutError:
            continue
