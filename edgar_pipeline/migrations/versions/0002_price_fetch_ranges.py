"""Record completed historical price fetches, including exchange holidays."""

import os

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.create_table(
        "price_fetch_ranges",
        sa.Column("ticker", sa.String(32), primary_key=True),
        sa.Column("start_date", sa.Date(), primary_key=True),
        sa.Column("end_date", sa.Date(), primary_key=True),
        sa.CheckConstraint("end_date >= start_date", name="ordered_dates"),
    )
    role = op.get_bind().dialect.identifier_preparer.quote_identifier(
        os.environ.get("POSTGRES_APP_USER", "fintech_app")
    )
    op.execute(sa.text(f"GRANT SELECT, INSERT ON price_fetch_ranges TO {role}"))


def downgrade() -> None:
    op.drop_table("price_fetch_ranges")
