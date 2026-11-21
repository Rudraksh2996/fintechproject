"""Deterministic synthetic ownership documents and daily GBM closes."""

import math
import random
from datetime import date, timedelta
from decimal import Decimal
from xml.etree import ElementTree as ET

from edgar_pipeline.db.repository import FilingInput

START = date(2024, 1, 2)
TICKERS = tuple(f"ZXQ{i:02d}" for i in range(40))
PLANTED = frozenset(TICKERS[:10])


def fixtures(seed: int) -> list[FilingInput]:
    rng = random.Random(seed)
    items: list[FilingInput] = []

    def filing(
        i: int,
        owner: int,
        day: int,
        code: str,
        price: int,
        ten: bool = False,
        original: FilingInput | None = None,
    ) -> FilingInput:
        when = START + timedelta(days=day)
        root = ET.Element("ownershipDocument")

        def put(path: str, value: str) -> None:
            node = root
            for part in path.split("/"):
                child = node.find(part)
                node = ET.SubElement(node, part) if child is None else child
            node.text = value

        put("schemaVersion", "X0508")
        put("documentType", "4/A" if original else "4")
        put("periodOfReport", str(when))
        put("issuer/issuerCik", str(9000000000 + i))
        put("issuer/issuerName", f"Fictional Quartz Issuer {i:02d}")
        put("issuer/issuerTradingSymbol", TICKERS[i])
        put("reportingOwner/reportingOwnerId/rptOwnerCik", str(8000000000 + i * 100 + owner))
        put("reportingOwner/reportingOwnerId/rptOwnerName", f"Fictional Owner {i:02d}-{owner}")
        relation = "reportingOwner/reportingOwnerRelationship/"
        put(relation + "isDirector", "0" if ten else "1")
        put(relation + "isOfficer", "1" if owner == 1 and not ten else "0")
        put(relation + "isTenPercentOwner", str(int(ten)))
        if owner == 1 and not ten:
            put(relation + "officerTitle", "Chief Financial Officer")
        tx = "nonDerivativeTable/nonDerivativeTransaction/"
        put(tx + "securityTitle/value", "Synthetic Common Stock")
        put(tx + "transactionDate/value", str(when))
        put(tx + "transactionCoding/transactionFormType", "4")
        put(tx + "transactionCoding/transactionCode", code)
        put(tx + "transactionCoding/equitySwapInvolved", "0")
        put(tx + "transactionAmounts/transactionShares/value", "1000")
        put(tx + "transactionAmounts/transactionPricePerShare/value", str(price))
        put(
            tx + "transactionAmounts/transactionAcquiredDisposedCode/value",
            "D" if code in "SF" else "A",
        )
        put(tx + "postTransactionAmounts/sharesOwnedFollowingTransaction/value", "4000")
        put(tx + "ownershipNature/directOrIndirectOwnership/value", "D")
        filed = when + timedelta(days=4 if original else 1)
        put("ownerSignature/signatureName", f"Synthetic Signer {owner}")
        put("ownerSignature/signatureDate", str(filed))
        accession = f"{9000000000 + i}-{filed.year % 100:02d}-{len(items) + 1:06d}"
        item = FilingInput(
            accession,
            filed,
            f"synthetic://{accession}.xml",
            ET.tostring(root),
            original.accession if original else None,
        )
        items.append(item)
        return item

    for i in range(40):
        for month in range(18):
            filing(i, 8, month * 30 + rng.randrange(6), rng.choice(["A", "M", "F", "S", "P"]), 30)
        day = 120 + i * 5
        for owner in range(3):
            price = 50 if i < 8 else (34 if i < 10 else 24)
            first = filing(i, owner, day + owner, "P", price, i >= 30)
            if i in (0, 1) and owner == 0:
                filing(i, owner, day, "P", price + 1, original=first)
    items.append(FilingInput("9999999999-24-999999", START, "synthetic://broken.xml", b"<broken"))
    return sorted(items, key=lambda item: (item.filed, item.accession))


def price_rows(seed: int) -> list[tuple[str, date, Decimal]]:
    rng = random.Random(seed)
    rows: list[tuple[str, date, Decimal]] = []
    for ticker in (*TICKERS, "SYNBENCH"):
        close = 100.0
        for day in range(630):
            when = START + timedelta(days=day)
            if when.weekday() < 5:
                close *= math.exp(0.0001 + 0.012 * rng.gauss(0, 1))
                rows.append((ticker, when, Decimal(f"{close:.6f}")))
    return rows
