"""Parse ownershipDocument XML, preserving joint owners and original line numbers."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from lxml import etree


class FilingParseError(ValueError):
    """A filing cannot be interpreted and should be quarantined."""


@dataclass(frozen=True)
class Owner:
    cik: str
    name: str
    director: bool
    officer: bool
    ten_percent: bool
    other: bool
    title: str | None


@dataclass(frozen=True)
class Purchase:
    line: int
    transaction_date: date
    shares: Decimal
    price: Decimal | None
    post_shares: Decimal | None
    ownership: str | None
    footnotes: tuple[str, ...]

    @property
    def value_usd(self) -> Decimal | None:
        return None if self.price is None else self.shares * self.price

    def holdings_increase(self, new_position_pct: Decimal = Decimal(1)) -> Decimal | None:
        if self.post_shares is None:
            return None
        prior = self.post_shares - self.shares
        return self.shares / prior if prior > 0 else new_position_pct


@dataclass(frozen=True)
class Filing:
    form: str
    issuer_cik: str
    issuer_name: str
    ticker: str | None
    owners: tuple[Owner, ...]
    purchases: tuple[Purchase, ...]
    plan_10b5_1: bool
    period: date | None


def _text(node: etree._Element, path: str) -> str | None:
    return (node.findtext(path) or "").strip() or None


def _required(node: etree._Element, path: str) -> str:
    value = _text(node, path)
    if value is None:
        raise FilingParseError(f"Missing {path}")
    return value


def _flag(node: etree._Element, path: str) -> bool:
    value = (_text(node, path) or "0").lower()
    if value not in {"0", "1", "false", "true"}:
        raise FilingParseError(f"Invalid flag {path}")
    return value in {"1", "true"}


def _amount(node: etree._Element, path: str) -> Decimal | None:
    value = _text(node, path)
    if value is None:
        return None
    amount = Decimal(value)
    if not amount.is_finite() or amount < 0:
        raise FilingParseError(f"Invalid amount in {path}")
    return amount


def _owner(node: etree._Element) -> Owner:
    rel = "reportingOwnerRelationship/"
    return Owner(
        _required(node, "reportingOwnerId/rptOwnerCik"),
        _required(node, "reportingOwnerId/rptOwnerName"),
        _flag(node, rel + "isDirector"),
        _flag(node, rel + "isOfficer"),
        _flag(node, rel + "isTenPercentOwner"),
        _flag(node, rel + "isOther"),
        _text(node, rel + "officerTitle"),
    )


def parse_form4(xml: bytes) -> Filing:
    """Parse one filing. Ownership scope and thresholds are applied at detection time."""
    try:
        root = etree.fromstring(xml, etree.XMLParser(resolve_entities=False, no_network=True))
        if root.getroottree().docinfo.doctype:
            raise FilingParseError("Unexpected document type declaration")
        for element in root.iter(tag=etree.Element):
            element.tag = etree.QName(element).localname
        form = _required(root, "documentType")
        if root.tag != "ownershipDocument" or form not in {"4", "4/A"}:
            raise FilingParseError("Expected a Form 4 or 4/A ownershipDocument")
        owners = tuple(_owner(n) for n in root.findall("reportingOwner"))
        if not owners:
            raise FilingParseError("Missing reportingOwner")
        purchases: list[Purchase] = []
        rows = root.findall("nonDerivativeTable/nonDerivativeTransaction")
        for line, row in enumerate(rows, 1):
            if _text(row, "transactionCoding/transactionCode") != "P":
                continue
            prefix = "transactionAmounts/"
            if _text(row, prefix + "transactionAcquiredDisposedCode/value") != "A":
                continue
            shares = _amount(row, prefix + "transactionShares/value")
            if shares is None:
                raise FilingParseError(f"Missing purchase shares at line {line}")
            purchases.append(
                Purchase(
                    line,
                    date.fromisoformat(_required(row, "transactionDate/value")),
                    shares,
                    _amount(row, prefix + "transactionPricePerShare/value"),
                    _amount(row, "postTransactionAmounts/sharesOwnedFollowingTransaction/value"),
                    _text(row, "ownershipNature/directOrIndirectOwnership/value"),
                    tuple(ref for n in row.iter("footnoteId") if (ref := n.get("id"))),
                )
            )
        period = _text(root, "periodOfReport")
        return Filing(
            form,
            _required(root, "issuer/issuerCik"),
            _required(root, "issuer/issuerName"),
            _text(root, "issuer/issuerTradingSymbol"),
            owners,
            tuple(purchases),
            _flag(root, "aff10b5One"),
            date.fromisoformat(period) if period else None,
        )
    except FilingParseError:
        raise
    except (ValueError, InvalidOperation, etree.XMLSyntaxError) as exc:
        raise FilingParseError(str(exc)) from exc
