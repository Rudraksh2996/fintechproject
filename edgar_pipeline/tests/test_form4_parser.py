from decimal import Decimal

import pytest
from edgar_pipeline.form4_parser import FilingParseError, parse_form4


def filing(rows: str) -> bytes:
    owners = "".join(
        f"<reportingOwner><reportingOwnerId><rptOwnerCik>{i}</rptOwnerCik>"
        f"<rptOwnerName>Test Owner {i}</rptOwnerName></reportingOwnerId>"
        "<reportingOwnerRelationship><isDirector>true</isDirector>"
        "</reportingOwnerRelationship></reportingOwner>"
        for i in (1, 2)
    )
    return (
        '<ownershipDocument xmlns="urn:test"><documentType>4/A</documentType>'
        "<issuer><issuerCik>100</issuerCik><issuerName>Test Issuer</issuerName></issuer>"
        f"{owners}<aff10b5One>1</aff10b5One><nonDerivativeTable>{rows}</nonDerivativeTable>"
        "</ownershipDocument>"
    ).encode()


def transaction(code: str, disposition: str = "A") -> str:
    return (
        "<nonDerivativeTransaction><transactionCoding>"
        f"<transactionCode> {code} </transactionCode></transactionCoding>"
        "<transactionDate><value>2025-01-03</value></transactionDate><transactionAmounts>"
        f"<transactionAcquiredDisposedCode><value>{disposition}</value></transactionAcquiredDisposedCode>"
        '<transactionPricePerShare><footnoteId id="F1"/></transactionPricePerShare>'
        "<transactionShares><value>12.5</value></transactionShares></transactionAmounts>"
        "<postTransactionAmounts><sharesOwnedFollowingTransaction><value>12.5</value>"
        "</sharesOwnedFollowingTransaction></postTransactionAmounts></nonDerivativeTransaction>"
    )


def test_joint_amendment_preserves_line_and_footnote_price() -> None:
    xml = filing("".join(transaction(c) for c in "AMFS") + transaction("P", "D") + transaction("P"))
    parsed = parse_form4(xml)
    assert parsed.form == "4/A" and parsed.plan_10b5_1
    assert [owner.cik for owner in parsed.owners] == ["1", "2"]
    (row,) = parsed.purchases
    assert row.line == 6 and row.footnotes == ("F1",)
    assert row.price is None and row.value_usd is None
    assert row.holdings_increase() == Decimal(1)


@pytest.mark.parametrize("xml", [b"<invalid", b"<ownershipDocument/>", b"<!DOCTYPE x><x/>"])
def test_invalid_filing_raises_typed_error(xml: bytes) -> None:
    with pytest.raises(FilingParseError):
        parse_form4(xml)
