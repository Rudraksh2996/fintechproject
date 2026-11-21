import asyncio
from datetime import date
from pathlib import Path

import httpx
from edgar_pipeline.discovery import by_index, by_issuer
from edgar_pipeline.http_client import SecClient


def test_sources_agree_on_raw_xml(tmp_path: Path) -> None:
    accession = "0000000001-24-000012"
    day = date(2024, 1, 2)
    table = {
        "accessionNumber": [accession],
        "form": ["4/A"],
        "filingDate": [str(day)],
        "primaryDocument": ["xslF345X01/ownership.xml"],
    }

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path.endswith(".idx"):
            return httpx.Response(
                200, text=f"4/A  Imaginary Inc  12  {day}  edgar/data/12/{accession}.txt\n"
            )
        if path.endswith(".txt"):
            return httpx.Response(
                200, text="<DOCUMENT>\n<TYPE>4/A\n<FILENAME>ownership.xml\n</DOCUMENT>"
            )
        if path.endswith("company_tickers.json"):
            return httpx.Response(200, json={"0": {"ticker": "FICT", "cik_str": 12}})
        if path.endswith("CIK0000000012.json"):
            return httpx.Response(
                200,
                json={
                    "filings": {
                        "recent": {k: [] for k in table},
                        "files": [
                            {
                                "filingFrom": str(day),
                                "filingTo": str(day),
                                "name": "CIK0000000012-submissions-001.json",
                            }
                        ],
                    }
                },
            )
        assert path.endswith("CIK0000000012-submissions-001.json")
        return httpx.Response(200, json=table)

    async def run() -> None:
        client = SecClient(
            "Test Org test@example.org", tmp_path, transport=httpx.MockTransport(handler)
        )
        try:
            daily = await by_index(client, day, day)
            assert daily == await by_index(client, day, day, "quarterly")
            assert daily == await by_issuer(client, "fict", day, day)
            assert daily[0].xml_url.endswith("/12/000000000124000012/ownership.xml")
        finally:
            await client.aclose()

    asyncio.run(run())
