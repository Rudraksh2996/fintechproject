from datetime import date

import pytest
from edgar_pipeline.config import Settings
from edgar_pipeline.db.models import Form4Transaction, IngestionRun, ParseError
from edgar_pipeline.db.repository import FilingInput, ingest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from test_form4_parser import filing, transaction


@pytest.mark.integration
def test_ingestion_roundtrip() -> None:
    engine = create_engine(Settings().database_url())
    xml = filing(transaction("P"))
    day = date(2025, 1, 6)
    original = FilingInput(
        "repo-test-original", day, "synthetic:original", xml.replace(b">4/A<", b">4<")
    )
    amended = FilingInput(
        "repo-test-amendment", day, "synthetic:amendment", xml, original.accession
    )
    bad = FilingInput("repo-test-bad", day, "synthetic:bad", b"<broken")
    try:
        with (
            engine.connect() as connection,
            connection.begin() as outer,
            Session(bind=connection, join_transaction_mode="create_savepoint") as db,
        ):
            run_id = ingest(db, [original, bad, amended, original, amended], "synthetic")
            run = db.get(IngestionRun, run_id)
            assert run and (
                run.status,
                run.filings_seen,
                run.transactions_inserted,
                run.errors,
            ) == ("completed", 5, 2, 1)
            error = db.scalars(
                select(ParseError).where(ParseError.ingestion_run_id == run_id)
            ).one()
            assert error.raw_xml == "<broken"
            rows = db.execute(
                select(Form4Transaction.accession_number, Form4Transaction.superseded).where(
                    Form4Transaction.accession_number.in_([original.accession, amended.accession])
                )
            ).all()
            assert dict(rows) == {original.accession: True, amended.accession: False}
            db.close()
            outer.rollback()
    finally:
        engine.dispose()
