"""Admin-only migration environment; URLs and passwords never enter the ini file."""

from logging.config import fileConfig

from alembic import context
from edgar_pipeline.config import Settings
from edgar_pipeline.db.models import Base
from sqlalchemy import create_engine, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    context.configure(
        dialect_name="postgresql",
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    settings = Settings()
    engine = create_engine(
        settings.database_url(admin=True),
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": 10},
    )
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
