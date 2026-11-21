from edgar_pipeline.cli import detect_database
from edgar_pipeline.config import Settings
from edgar_pipeline.db.models import ClusterAlert
from edgar_pipeline.db.repository import ingest
from edgar_pipeline.demo import fixtures
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def test_borderline_fixture_replay() -> None:
    # Isolate test accessions and issuers from an already seeded database.
    from dataclasses import replace

    rows = [
        replace(
            item,
            accession="test-" + item.accession,
            supersedes="test-" + item.supersedes if item.supersedes else None,
            xml=item.xml.replace(b"ZXQ", b"TST").replace(b"90000000", b"91000000"),
        )
        for item in fixtures(42)
        if any(t in item.xml for t in (b"ZXQ40", b"ZXQ41", b"ZXQ42"))
    ]
    engine = create_engine(Settings().database_url())
    try:
        with (
            engine.connect() as conn,
            conn.begin() as outer,
            Session(conn, join_transaction_mode="create_savepoint") as db,
        ):
            ingest(db, [i for i in rows if not i.supersedes], "synthetic")
            detect_database(db, "synthetic")

            def expected() -> list[tuple[str, int, int]]:
                return [
                    (a.ticker, a.n_insiders, int(a.total_value_usd))
                    for a in db.scalars(
                        select(ClusterAlert)
                        .where(ClusterAlert.ticker.in_(["TST40", "TST41", "TST42"]))
                        .order_by(ClusterAlert.ticker)
                    )
                ]

            assert expected() == [("TST40", 3, 100000)]
            amendment = next(i for i in rows if i.supersedes)
            ingest(db, [amendment], "synthetic")
            detect_database(db, "synthetic")
            assert expected() == [("TST40", 3, 100000), ("TST42", 3, 100000)]
            assert (
                db.scalars(
                    select(ClusterAlert.alert_filing_date).where(ClusterAlert.ticker == "TST42")
                ).one()
                == amendment.filed
            )
            db.close()
            outer.rollback()
    finally:
        engine.dispose()
