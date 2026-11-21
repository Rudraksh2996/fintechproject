"""Shared score configuration and deterministic components."""

import re
from dataclasses import dataclass
from decimal import Decimal
from math import log10


@dataclass(frozen=True)
class Config:
    window_days: int = 14
    min_insiders: int = 3
    min_insider_value_usd: Decimal = Decimal(25000)
    min_cluster_value_usd: Decimal = Decimal(100000)
    include_ten_percent_owners: bool = False
    exclude_10b5_1: bool = False
    cap_insiders: int = 8
    value_cap_multiple: Decimal = Decimal(100)
    holdings_cap: Decimal = Decimal("0.5")
    w_b: Decimal = Decimal("0.30")
    w_c: Decimal = Decimal("0.25")
    w_v: Decimal = Decimal("0.25")
    w_h: Decimal = Decimal("0.20")

    def __post_init__(self) -> None:
        weights = (self.w_b, self.w_c, self.w_v, self.w_h)
        if min(weights) < 0 or sum(weights) != 1:
            raise ValueError("Score weights must be nonnegative and sum to one")
        if not 2 <= self.min_insiders <= self.cap_insiders or self.window_days < 1:
            raise ValueError("Invalid buyer or window bounds")
        if (
            min(self.min_insider_value_usd, self.min_cluster_value_usd, self.holdings_cap) <= 0
            or self.value_cap_multiple <= 1
        ):
            raise ValueError("Invalid scoring thresholds")


def executive_rank(title: str) -> int:
    if re.search(r"\b(CEO|CFO|chief (executive|financial) officer)\b", title, re.I):
        return 2
    return int(bool(re.search(r"\b(C[A-Z]{1,3}O|chief [\w -]+ officer)\b", title, re.I)))


def conviction(
    c: Config, buyers: int, executive_points: int, value: Decimal, median_holdings: Decimal
) -> tuple[Decimal, dict[str, float]]:
    factors = {
        "buyers": (buyers - c.min_insiders + 1) / (c.cap_insiders - c.min_insiders + 1),
        "csuite": executive_points / 3,
        "value": log10(value / c.min_cluster_value_usd) / log10(c.value_cap_multiple)
        if value > 0
        else 0,
        "holdings": float(median_holdings / c.holdings_cap),
    }
    factors = {k: max(0.0, min(1.0, v)) for k, v in factors.items()}
    score = sum(
        w * Decimal(str(f))
        for w, f in zip((c.w_b, c.w_c, c.w_v, c.w_h), factors.values(), strict=True)
    )
    return (Decimal(100) * score).quantize(Decimal("0.01")), factors
