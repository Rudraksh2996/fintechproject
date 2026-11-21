"""Evaluate trailing transaction-date windows, using filing dates for availability."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from itertools import groupby
from statistics import median

from edgar_pipeline.conviction import Config, conviction, executive_rank


@dataclass(frozen=True)
class Trade:
    id: int
    company: int
    insider: int
    day: date
    filed: date
    value: Decimal | None
    holdings: Decimal | None
    title: str = ""
    director: bool = False
    officer: bool = False
    ten_percent: bool = False
    plan: bool = False


@dataclass
class Cluster:
    company: int
    start: date
    end: date
    trigger: date
    members: dict[int, Trade]

    def score(self, config: Config) -> tuple[Decimal, dict[str, float]]:
        ranks: dict[int, int] = {}
        for t in self.members.values():
            ranks[t.insider] = max(ranks.get(t.insider, 0), executive_rank(t.title))
        amounts = sum((t.value or Decimal(0) for t in self.members.values()), Decimal(0))
        ratios = [t.holdings for t in self.members.values() if t.holdings is not None]
        return conviction(
            config,
            len(ranks),
            sum(ranks.values()),
            amounts,
            median(ratios) if ratios else Decimal(0),
        )


def _trigger(rows: list[Trade], c: Config) -> date:
    totals: defaultdict[int, Decimal] = defaultdict(Decimal)
    buyers = 0
    value = Decimal(0)
    for t in sorted(rows, key=lambda t: t.filed):
        previous = totals[t.insider]
        delta = t.value or Decimal(0)
        totals[t.insider] += delta
        if previous >= c.min_insider_value_usd:
            value += delta
        elif totals[t.insider] >= c.min_insider_value_usd:
            buyers += 1
            value += totals[t.insider]
        if buyers >= c.min_insiders and value >= c.min_cluster_value_usd:
            return t.filed
    raise ValueError("Window did not trigger")


DEFAULT_CONFIG = Config()


@dataclass
class DetectionStats:
    window_entries: int = 0


def detect(
    trades: Iterable[Trade], config: Config = DEFAULT_CONFIG, *, stats: DetectionStats | None = None
) -> list[Cluster]:
    eligible = sorted(
        (
            t
            for t in trades
            if t.value is not None
            and t.value > 0
            and (t.director or t.officer or (config.include_ten_percent_owners and t.ten_percent))
            and not (config.exclude_10b5_1 and t.plan)
        ),
        key=lambda t: (t.company, t.day, t.id),
    )
    alerts: list[Cluster] = []
    for company, group in groupby(eligible, key=lambda t: t.company):
        rows = list(group)
        left = 0
        totals: defaultdict[int, Decimal] = defaultdict(Decimal)
        for right, t in enumerate(rows):
            totals[t.insider] += t.value or Decimal(0)
            if stats is not None:
                stats.window_entries += 1
            if right + 1 < len(rows) and rows[right + 1].day == t.day:
                continue
            start = t.day - timedelta(days=config.window_days - 1)
            while rows[left].day < start:
                old = rows[left]
                totals[old.insider] -= old.value or Decimal(0)
                if totals[old.insider] == 0:
                    del totals[old.insider]
                left += 1
            qualified = {i for i, v in totals.items() if v >= config.min_insider_value_usd}
            if (
                len(qualified) < config.min_insiders
                or sum(totals[i] for i in qualified) < config.min_cluster_value_usd
            ):
                continue
            members = [r for r in rows[left : right + 1] if r.insider in qualified]
            trigger = _trigger(members, config)
            if (
                alerts
                and alerts[-1].company == company
                and start <= alerts[-1].end + timedelta(days=1)
            ):
                current = alerts[-1]
                current.end = t.day
                current.trigger = min(current.trigger, trigger)
                current.members.update((r.id, r) for r in members)
            else:
                alerts.append(Cluster(company, start, t.day, trigger, {r.id: r for r in members}))
    return alerts
