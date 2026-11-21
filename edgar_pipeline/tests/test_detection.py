from datetime import date, timedelta
from decimal import Decimal
from time import perf_counter

from edgar_pipeline.backtest import Signal, backtest
from edgar_pipeline.cluster_engine import DetectionStats, Trade, detect
from edgar_pipeline.conviction import Config, conviction

BASE = date(2024, 1, 1)


def trade(i: int, day: int, delay: int = 0) -> Trade:
    when = BASE + timedelta(days=day)
    return Trade(
        i, 1, i, when, when + timedelta(days=delay), Decimal(50000), Decimal(".25"), director=True
    )


def test_windows_and_trigger_date() -> None:
    assert not detect([trade(1, 0), trade(2, 1)])
    assert not detect([trade(1, 0), trade(2, 1), trade(3, 14)])
    (alert,) = detect([trade(1, 0, 8), trade(2, 1, 6), trade(3, 2, 2), trade(4, 8, 1)])
    assert alert.trigger == BASE + timedelta(days=8)
    assert set(alert.members) == {1, 2, 3, 4}
    assert conviction(Config(), 1, 0, Decimal(0), Decimal(0))[0] == 0
    assert conviction(Config(), 99, 8, Decimal("1e10"), Decimal(3))[0] == 100


def test_backtest_enters_first_available_close() -> None:
    class Prices:
        def closes(self, ticker: str) -> dict[date, Decimal]:
            return {
                BASE + timedelta(days=i): Decimal(100 + i if ticker == "FICT" else 100)
                for i in range(100)
                if i % 7 < 5
            }

    (five, twenty, sixty) = backtest(
        [Signal("FICT", BASE + timedelta(days=5), Decimal(30))], Prices()
    )
    assert five.entry == BASE + timedelta(days=7)
    assert five.exit == BASE + timedelta(days=14)
    assert five.excess == Decimal(114) / 107 - 1
    assert twenty.sessions == 20 and sixty.sessions == 60


def test_100k_rows() -> None:
    rows = [
        Trade(
            i,
            i % 100,
            (i // 100) % 20,
            BASE + timedelta(days=i // 1000),
            BASE + timedelta(days=i // 1000 + 1),
            Decimal(40000),
            None,
            director=True,
        )
        for i in range(100000)
    ]
    start = perf_counter()
    stats = DetectionStats()
    alerts = detect(rows, stats=stats)
    elapsed = perf_counter() - start
    print(
        f"{stats.window_entries} window entries, {len(alerts)} merged alerts, {elapsed:.3f} seconds"
    )
    assert stats.window_entries == 100_000
    assert [a.company for a in alerts] == list(range(100))
    for a in alerts:
        assert set(a.members) == set(range(a.company, 100_000, 100))
    assert len(alerts) == 100 and elapsed < 10
