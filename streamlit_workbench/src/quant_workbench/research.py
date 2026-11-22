"""Read-only research queries shared by all four workbench pages."""

from collections.abc import Mapping
from datetime import date
from decimal import Decimal

import pandas as pd
from edgar_pipeline.backtest import ForwardReturn, Signal, backtest
from edgar_pipeline.cli import load_trades
from edgar_pipeline.cluster_engine import Cluster, detect
from edgar_pipeline.conviction import Config
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL, Engine, create_engine, text
from sqlalchemy.orm import Session


class Environment(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "fintech"
    workbench_ro_password: SecretStr
    gateway_url: str = "http://localhost:8000"
    demo_mode: bool = True

    def engine(self) -> Engine:
        return create_engine(
            URL.create(
                "postgresql+psycopg",
                username="workbench_ro",
                password=self.workbench_ro_password.get_secret_value(),
                host=self.postgres_host,
                port=self.postgres_port,
                database=self.postgres_db,
            ),
            pool_pre_ping=True,
        )


def frame(engine: Engine, sql: str, **params: str | int | bool) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params, coerce_float=False)


def clusters(
    engine: Engine, demo: bool, config: Config, new_position: Decimal
) -> tuple[list[Cluster], dict[int, str]]:
    with Session(engine) as db:
        trades, tickers = load_trades(db, "synthetic" if demo else "sec_edgar", new_position)
    return detect(trades, config), tickers


class CachedPrices:
    def __init__(self, engine: Engine, demo: bool) -> None:
        bars = frame(
            engine,
            "SELECT ticker,date,close FROM price_bars WHERE (source='synthetic')=:demo",
            demo=demo,
        )
        self.bars = {
            str(t): dict(zip(rows.date, rows.close, strict=True))
            for t, rows in bars.groupby("ticker")
        }

    def closes(self, ticker: str) -> Mapping[date, Decimal]:
        return self.bars.get(ticker, {})


def returns(
    engine: Engine, demo: bool, config: Config, new_position: Decimal, start: date, end: date
) -> list[ForwardReturn]:
    found, tickers = clusters(engine, demo, config, new_position)
    signals = []
    for c in found:
        if start <= c.trigger <= end:
            known = Cluster(
                c.company,
                c.start,
                c.end,
                c.trigger,
                {i: t for i, t in c.members.items() if t.filed <= c.trigger},
            )
            signals.append(Signal(tickers[c.company], c.trigger, known.score(config)[0]))
    return backtest(signals, CachedPrices(engine, demo), "SYNBENCH" if demo else "SPY")
