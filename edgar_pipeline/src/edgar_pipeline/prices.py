"""Daily US equity closes for a historical backtest, cached by ticker and session."""

import csv
import io
import re
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from itertools import batched

import httpx
import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from edgar_pipeline.db.models import PriceBar, PriceFetchRange


class PriceError(Exception):
    """Price history could not be obtained or persisted."""


def _yahoo(ticker: str, start: date, end: date) -> dict[date, Decimal]:
    import yfinance as yf  # type: ignore[import-untyped]

    try:
        frame: pd.DataFrame = yf.Ticker(ticker).history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            interval="1d",
            auto_adjust=False,
            actions=False,
            timeout=15,
            raise_errors=True,
        )
        return {
            date.fromisoformat(str(index)[:10]): Decimal(str(value))
            for index, value in frame["Close"].dropna().items()
        }
    except Exception as exc:
        raise PriceError(f"yfinance could not load {ticker}") from exc


class LivePrices:
    def __init__(
        self,
        sessions: Callable[[], Session],
        start: date,
        end: date,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if end < start:
            raise ValueError("Price end precedes start")
        self.sessions, self.start, self.end, self.transport = sessions, start, end, transport

    def _stooq(self, ticker: str) -> dict[date, Decimal]:
        with httpx.Client(transport=self.transport, timeout=15) as client:
            response = client.get(
                "https://stooq.com/q/d/l/",
                params={
                    "s": ticker.lower() + ".us",
                    "i": "d",
                    "d1": self.start.strftime("%Y%m%d"),
                    "d2": self.end.strftime("%Y%m%d"),
                },
            )
            response.raise_for_status()
            data = {
                date.fromisoformat(row["Date"]): Decimal(row["Close"])
                for row in csv.DictReader(io.StringIO(response.text))
            }
        return data

    def _validate(self, data: dict[date, Decimal]) -> dict[date, Decimal]:
        bars = {d: p for d, p in data.items() if self.start <= d <= self.end}
        if not bars or any(not p.is_finite() or p <= 0 for p in bars.values()):
            raise PriceError("Missing or invalid daily closes")
        return bars

    def closes(self, ticker: str) -> dict[date, Decimal]:
        ticker = ticker.strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,30}", ticker):
            raise ValueError("Invalid price ticker")
        try:
            with self.sessions() as db:
                next_day = self.start
                for span in db.scalars(
                    select(PriceFetchRange)
                    .where(
                        PriceFetchRange.ticker == ticker,
                        PriceFetchRange.end_date >= self.start,
                        PriceFetchRange.start_date <= self.end,
                    )
                    .order_by(PriceFetchRange.start_date)
                ):
                    if span.start_date > next_day:
                        break
                    next_day = max(next_day, span.end_date + timedelta(days=1))
                cached = {
                    r.date: r.close
                    for r in db.scalars(
                        select(PriceBar).where(
                            PriceBar.ticker == ticker,
                            PriceBar.source.in_(("stooq", "yfinance")),
                            PriceBar.date.between(self.start, self.end),
                        )
                    )
                }
            # Avoid treating a disjoint or partial range as a complete cache hit.
            weekdays = pd.bdate_range(self.start, self.end)
            if next_day > self.end or all(d.date() in cached for d in weekdays):
                return cached
            try:
                bars = self._validate(self._stooq(ticker))
                source = "stooq"
            except (httpx.HTTPError, ValueError, KeyError, InvalidOperation, csv.Error, PriceError):
                bars = self._validate(_yahoo(ticker, self.start, self.end))
                source = "yfinance"
            with self.sessions() as db, db.begin():
                completed_end = min(self.end, date.today() - timedelta(days=1))
                if completed_end >= self.start:
                    db.execute(
                        insert(PriceFetchRange)
                        .values(ticker=ticker, start_date=self.start, end_date=completed_end)
                        .on_conflict_do_nothing()
                    )
                for batch in batched(bars.items(), 500):
                    stmt = insert(PriceBar).values(
                        [
                            {"ticker": ticker, "date": d, "close": p, "source": source}
                            for d, p in batch
                        ]
                    )
                    db.execute(
                        stmt.on_conflict_do_update(
                            index_elements=[PriceBar.ticker, PriceBar.date],
                            set_={"close": stmt.excluded.close, "source": stmt.excluded.source},
                            where=PriceBar.source.in_(("stooq", "yfinance")),
                        )
                    )
            return bars
        except SQLAlchemyError as exc:
            raise PriceError(f"Database price cache unavailable for {ticker}") from exc
