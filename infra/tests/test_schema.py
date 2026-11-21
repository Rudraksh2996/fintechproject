"""Offline contract checks; these deliberately do not substitute for the live gate."""

import ast
from pathlib import Path

import pytest
import yaml
from edgar_pipeline.config import Settings
from edgar_pipeline.db.models import Base, Form4Transaction
from pydantic import SecretStr, ValidationError
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

ROOT = Path(__file__).resolve().parents[2]


def configured_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "postgres_password": SecretStr("test-only"),
        "postgres_app_password": SecretStr("test-only"),
        "workbench_ro_password": SecretStr("test-only"),
    }
    values.update(overrides)
    return Settings.model_validate(values)


def test_required_tables_and_transaction_keys() -> None:
    assert set(Base.metadata.tables) == {
        "companies",
        "insiders",
        "form4_transactions",
        "cluster_alerts",
        "form4_filings",
        "cluster_alert_members",
        "detection_configs",
        "ingestion_runs",
        "parse_errors",
        "price_bars",
        "price_fetch_ranges",
    }
    table = Form4Transaction.__table__
    unique_keys = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("accession_number", "line_number") in unique_keys
    assert any(
        tuple(c.name for c in index.columns) == ("ticker", "transaction_date")
        for index in table.indexes
    )


def test_frozen_revision_matches_current_metadata() -> None:
    revision = ROOT / "edgar_pipeline/migrations/versions/0001_initial_schema.py"
    tree = ast.parse(revision.read_text(encoding="utf-8"))
    frozen: tuple[str, ...] | None = None
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "SCHEMA_DDL"
            and node.value is not None
        ):
            frozen = ast.literal_eval(node.value)
    dialect = postgresql.dialect()
    tables = [t for t in Base.metadata.sorted_tables if t.name != "price_fetch_ranges"]
    current = [str(CreateTable(table).compile(dialect=dialect)).strip() for table in tables]
    current.extend(
        str(CreateIndex(index).compile(dialect=dialect)).strip()
        for table in tables
        for index in sorted(table.indexes, key=lambda item: item.name or "")
    )
    assert tuple(current) == frozen


def test_sec_rate_cap_and_live_identity() -> None:
    for invalid in (0, -1, 10.1):
        with pytest.raises(ValidationError):
            configured_settings(sec_max_rps=invalid)
    assert configured_settings(sec_max_rps=10).sec_max_rps == 10
    with pytest.raises(ValidationError, match="SEC_USER_AGENT"):
        configured_settings(demo_mode=False, sec_user_agent="")
    assert not configured_settings(
        demo_mode=False, sec_user_agent="Org contact@example.com"
    ).demo_mode


def test_roles_and_password_encoding() -> None:
    settings = configured_settings(postgres_app_password=SecretStr("a/@:#?b"))
    assert settings.database_url().password == "a/@:#?b"
    assert settings.database_url(readonly=True).username == "workbench_ro"
    with pytest.raises(ValueError):
        settings.database_url(admin=True, readonly=True)


def test_compose_has_persistent_healthchecked_databases() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for name in ("postgres", "neo4j"):
        service = compose["services"][name]
        assert service["healthcheck"]["retries"] >= 10
        assert service["volumes"]
        assert all(port.startswith("127.0.0.1:") for port in service["ports"])
    assert compose["services"]["postgres"]["image"] == "postgres:16.11-bookworm"
    assert compose["services"]["neo4j"]["image"] == "neo4j:5.26-community"
