from datetime import date
from decimal import Decimal

import httpx
import pandas as pd
import pytest
import yfinance
from edgar_pipeline.config import Settings
from edgar_pipeline.db.models import PriceBar
from edgar_pipeline.prices import LivePrices
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker


@pytest.mark.parametrize("status,source", [(200, "stooq"), (503, "yfinance")])
def test_vendor_fallback_and_persistent_cache(
    status: int, source: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # MLK Day (Monday Jan 20) has no bar; the fetched interval still covers it.
    start, end = date(2025, 1, 17), date(2025, 1, 21)
    requests = []
    fallback = []

    def stooq(req: httpx.Request) -> httpx.Response:
        requests.append(req)
        assert req.url.params["s"] == "qxtest.us"
        return httpx.Response(status, text="Date,Close\n2025-01-17,10.50\n2025-01-21,11.75\n")

    def history(self: object, **kwargs: object) -> pd.DataFrame:
        fallback.append(kwargs)
        assert kwargs["end"] == "2025-01-22" and kwargs["auto_adjust"] is False
        return pd.DataFrame({"Close": [10.5, 11.75]}, index=pd.to_datetime([start, end]))

    monkeypatch.setattr(yfinance.Ticker, "history", history)
    engine = create_engine(Settings().database_url())
    try:
        with engine.connect() as conn, conn.begin() as outer:
            sessions = sessionmaker(conn, join_transaction_mode="create_savepoint")
            for _ in range(2):
                prices = LivePrices(sessions, start, end, transport=httpx.MockTransport(stooq))
                assert prices.closes("qxTest") == {start: Decimal("10.5"), end: Decimal("11.75")}
            with Session(conn) as db:
                assert (
                    list(db.scalars(select(PriceBar.source).where(PriceBar.ticker == "QXTEST")))
                    == [source] * 2
                )
            assert len(requests) == 1 and len(fallback) == int(status == 503)
            outer.rollback()
    finally:
        engine.dispose()
