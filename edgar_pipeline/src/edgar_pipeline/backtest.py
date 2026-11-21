"""Close-to-close event returns on matching security and benchmark trading dates."""

from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from statistics import mean, median
from typing import Protocol


class PriceProvider(Protocol):
    def closes(self, ticker: str) -> Mapping[date, Decimal]: ...


@dataclass(frozen=True)
class Signal:
    ticker: str
    filed: date
    score_at_trigger: Decimal


@dataclass(frozen=True)
class ForwardReturn:
    signal: Signal
    entry: date
    exit: date
    sessions: int
    absolute: Decimal
    excess: Decimal


def backtest(
    signals: Sequence[Signal], prices: PriceProvider, benchmark: str = "SPY"
) -> list[ForwardReturn]:
    reference = prices.closes(benchmark)
    result: list[ForwardReturn] = []
    for signal in signals:
        bars = prices.closes(signal.ticker)
        days = sorted(bars)
        index = bisect_left(days, signal.filed)
        if index == len(days):
            continue
        entry = days[index]
        for n in (5, 20, 60):
            if index + n >= len(days):
                continue
            exit_day = days[index + n]
            if entry not in reference or exit_day not in reference:
                continue
            if min(bars[entry], reference[entry]) <= 0:
                raise ValueError("Entry prices must be positive")
            absolute = bars[exit_day] / bars[entry] - 1
            excess = absolute - (reference[exit_day] / reference[entry] - 1)
            result.append(ForwardReturn(signal, entry, exit_day, n, absolute, excess))
    return result


@dataclass(frozen=True)
class Summary:
    hit_rate: float
    mean_excess: Decimal
    median_excess: Decimal
    distribution: tuple[Decimal, ...]
    quintile_means: dict[int, Decimal]


def summarize(returns: Sequence[ForwardReturn]) -> dict[int, Summary]:
    result: dict[int, Summary] = {}
    for n in (5, 20, 60):
        rows = sorted(
            (r for r in returns if r.sessions == n),
            key=lambda r: (r.signal.score_at_trigger, r.signal.ticker, r.entry),
        )
        if not rows:
            continue
        values = tuple(r.excess for r in rows)
        buckets: dict[int, list[Decimal]] = {}
        for i, row in enumerate(rows):
            buckets.setdefault(1 + 5 * i // len(rows), []).append(row.excess)
        result[n] = Summary(
            sum(v > 0 for v in values) / len(values),
            mean(values),
            median(values),
            values,
            {k: mean(v) for k, v in buckets.items()},
        )
    return result
