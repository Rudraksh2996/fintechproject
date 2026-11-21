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
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = "
            "'form4_transactions'::regclass AND contype = 'u'"
        )
        constraints = dict(cursor.fetchall())
        assert (
            constraints.get("uq_form4_accession_line") == "UNIQUE (accession_number, line_number)"
        )
        cursor.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = %s", ("ix_form4_ticker_date",)
        )
        row = cursor.fetchone()
        assert row == (
            "CREATE INDEX ix_form4_ticker_date ON public.form4_transactions "
            "USING btree (ticker, transaction_date)",
        ), row
        cursor.execute("SELECT count(*) FROM detection_configs WHERE is_active")
        assert cursor.fetchone() == (1,)
        cursor.execute("SELECT tgname FROM pg_trigger WHERE tgrelid = 'cluster_alerts'::regclass")
        assert "cluster_alert_inserted" in {str(row[0]) for row in cursor.fetchall()}
        cursor.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = "
            "'public' AND table_type = 'BASE TABLE'"
        )
        assert cursor.fetchone() == (12,)  # eleven domain tables plus Alembic version
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
        records, _, _ = driver.execute_query("SHOW CONSTRAINTS")
        definitions = {
            (r["name"], r["type"], tuple(r["labelsOrTypes"]), tuple(r["properties"]))
            for r in records
        }
        expected = {
            ("account_id_unique", "UNIQUENESS", ("Account",), ("account_id",)),
            ("device_id_unique", "UNIQUENESS", ("Device",), ("device_id",)),
            ("ip_unique", "UNIQUENESS", ("IP",), ("ip",)),
            ("label_account_unique", "UNIQUENESS", ("Label",), ("account_id",)),
            ("transfer_id_unique", "RELATIONSHIP_UNIQUENESS", ("TRANSFERRED",), ("txn_id",)),
        }
        assert expected <= definitions, definitions
        records, _, _ = driver.execute_query("SHOW INDEXES WHERE name = 'transferred_ts'")
        assert len(records) == 1
        index = records[0]
        assert (index["entityType"], index["labelsOrTypes"], index["properties"]) == (
            "RELATIONSHIP",
            ["TRANSFERRED"],
            ["ts"],
        )
        assert (index["type"], index["state"], index["owningConstraint"]) == (
            "RANGE",
            "ONLINE",
            None,
        )
    print(json.dumps({"neo4j": "passed", "constraints": sorted(expected), "time_index": True}))


if __name__ == "__main__":
    verify_postgres(Settings())
    verify_neo4j(GraphSettings())
