"""Gate 1 integration assertions against real PostgreSQL and Neo4j instances."""

import json

import psycopg
from edgar_pipeline.config import Settings
from ml_pipeline.config import GraphSettings
from neo4j import GraphDatabase
from psycopg import errors


def verify_postgres(settings: Settings) -> None:
    admin_url = settings.database_url(admin=True).render_as_string(hide_password=False)
    with (
        psycopg.connect(admin_url.replace("postgresql+psycopg:", "postgresql:")) as conn,
        conn.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid = "
            "'form4_transactions'::regclass AND contype = 'u'"
        )
        names = {str(row[0]) for row in cursor.fetchall()}
        assert "uq_form4_accession_line" in names, names
        cursor.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = %s", ("ix_form4_ticker_date",)
        )
        row = cursor.fetchone()
        assert row is not None and "(ticker, transaction_date)" in str(row[0]), row
        cursor.execute("SELECT count(*) FROM detection_configs WHERE is_active")
        assert cursor.fetchone() == (1,)
        cursor.execute("SELECT tgname FROM pg_trigger WHERE tgrelid = 'cluster_alerts'::regclass")
        assert "cluster_alert_inserted" in {str(row[0]) for row in cursor.fetchall()}
        cursor.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = "
            "'public' AND table_type = 'BASE TABLE'"
        )
        assert cursor.fetchone() == (11,)  # ten domain tables plus Alembic version
    readonly_url = settings.database_url(readonly=True).render_as_string(hide_password=False)
    with psycopg.connect(readonly_url.replace("postgresql+psycopg:", "postgresql:")) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM detection_configs")
            assert cursor.fetchone() == (1,)
        conn.commit()
        # Turn off the session default to prove ACLs themselves prevent writes.
        conn.execute("SET default_transaction_read_only = off")
        conn.commit()
        try:
            conn.execute("INSERT INTO companies(cik, name) VALUES ('0000000000', 'ACL probe')")
        except errors.InsufficientPrivilege:
            conn.rollback()
        else:
            conn.rollback()
            raise AssertionError("workbench_ro unexpectedly has INSERT permission")
    print(
        json.dumps(
            {
                "postgres": "passed",
                "unique_constraint": True,
                "ticker_date_index": True,
                "readonly_insert_denied": True,
            }
        )
    )


def verify_neo4j(settings: GraphSettings) -> None:
    user, separator, password = settings.neo4j_auth.get_secret_value().partition("/")
    if not separator or not password:
        raise ValueError("NEO4J_AUTH must contain user/password")
    with GraphDatabase.driver(
        settings.neo4j_uri, auth=(user, password), connection_timeout=10
    ) as driver:
        records, _, _ = driver.execute_query("SHOW CONSTRAINTS YIELD name RETURN name")
        names = {str(record["name"]) for record in records}
        expected = {
            "account_id_unique",
            "device_id_unique",
            "ip_unique",
            "label_account_unique",
            "transfer_id_unique",
        }
        assert expected <= names, names
        records, _, _ = driver.execute_query("SHOW INDEXES YIELD name, state RETURN name, state")
        indexes = {str(record["name"]): str(record["state"]) for record in records}
        assert indexes.get("transferred_ts") == "ONLINE", indexes
    print(json.dumps({"neo4j": "passed", "constraints": sorted(expected), "time_index": True}))


if __name__ == "__main__":
    verify_postgres(Settings())
    verify_neo4j(GraphSettings())
