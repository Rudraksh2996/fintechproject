"""Discover ownership filings from SEC form indexes or an issuer's submissions."""

import calendar
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import PurePosixPath
from typing import Literal

import httpx

from edgar_pipeline.http_client import SecClient, SecError

ARCHIVES = "https://www.sec.gov/Archives/"
SUBMISSIONS = "https://data.sec.gov/submissions/"
_ACCESSION = re.compile(r"\d{10}-\d{2}-\d{6}")


@dataclass(frozen=True)
class FilingRef:
    accession: str
    filing_date: date
    form: str
    xml_url: str


def _filename(value: str) -> str:
    if not re.fullmatch(r"[\w.-]+\.xml", value, re.IGNORECASE):
        raise SecError(f"Invalid ownership document filename: {value}")
    return value


def _document_name(submission: bytes, form: str) -> str:
    for section in re.findall(rb"<DOCUMENT>(.*?)</DOCUMENT>", submission, re.I | re.S):
        kind = re.search(rb"(?im)^\s*<TYPE>\s*([^\r\n<]+)", section)
        name = re.search(rb"(?im)^\s*<FILENAME>\s*([^\r\n<]+)", section)
        if kind and name and kind[1].strip() == form.encode():
            return _filename(name[1].decode().strip())
    raise SecError("Submission has no primary ownership XML")


def _index_urls(start: date, end: date, daily: bool) -> Iterator[str]:
    day = start
    while day <= end:
        quarter = (day.month - 1) // 3 + 1
        folder = f"{day.year}/QTR{quarter}"
        if daily:
            if day.weekday() < 5:
                yield f"{ARCHIVES}edgar/daily-index/{folder}/form.{day:%Y%m%d}.idx"
            day += timedelta(days=1)
        else:
            yield f"{ARCHIVES}edgar/full-index/{folder}/form.idx"
            day = date(day.year, 3 * quarter, calendar.monthrange(day.year, 3 * quarter)[1])
            day += timedelta(days=1)


async def by_index(
    client: SecClient, start: date, end: date, frequency: Literal["daily", "quarterly"] = "daily"
) -> list[FilingRef]:
    if start > end:
        raise ValueError("Start must precede end")
    result: dict[str, FilingRef] = {}
    for url in _index_urls(start, end, frequency == "daily"):
        try:
            data = await client.get(url, max_age=3600)
        except SecError as exc:
            cause = exc.__cause__
            if (
                frequency == "daily"
                and isinstance(cause, httpx.HTTPStatusError)
                and cause.response.status_code == 404
            ):
                continue
            raise
        for line in data.decode("latin1").splitlines():
            if not re.match(r"^\s*4(?:/A)?\s", line):
                continue
            form = line.split()[0]
            day_text, path = line.split()[-2:]
            day = date.fromisoformat(day_text)
            if not start <= day <= end:
                continue
            match = re.fullmatch(r"edgar/data/(\d+)/(\d{10}-\d{2}-\d{6})\.txt", path)
            if not match:
                raise SecError(f"Invalid index path: {path}")
            cik, accession = match.groups()
            if accession not in result:
                name = _document_name(await client.get(ARCHIVES + path), form)
                directory = f"{ARCHIVES}edgar/data/{cik}/{accession.replace('-', '')}"
                result[accession] = FilingRef(accession, day, form, f"{directory}/{name}")
    return sorted(result.values(), key=lambda item: (item.filing_date, item.accession))


async def by_issuer(client: SecClient, issuer: str, start: date, end: date) -> list[FilingRef]:
    if start > end:
        raise ValueError("Start must precede end")
    cik = issuer.strip()
    if not cik.isdecimal():
        mapping = json.loads(
            await client.get("https://www.sec.gov/files/company_tickers.json", max_age=86400)
        )
        candidates = [
            str(row["cik_str"]) for row in mapping.values() if row["ticker"].upper() == cik.upper()
        ]
        if len(candidates) != 1:
            raise SecError(f"Cannot resolve ticker {issuer}")
        cik = candidates[0]
    if not re.fullmatch(r"[0-9]{1,10}", cik):
        raise SecError("Invalid issuer CIK")
    payload = json.loads(await client.get(f"{SUBMISSIONS}CIK{int(cik):010d}.json", max_age=900))
    tables = [payload["filings"]["recent"]]
    for shard in payload["filings"]["files"]:
        if shard["filingFrom"] <= end.isoformat() and shard["filingTo"] >= start.isoformat():
            name = shard["name"]
            if not re.fullmatch(r"CIK\d{10}-submissions-\d+\.json", name):
                raise SecError("Invalid submissions archive filename")
            tables.append(json.loads(await client.get(SUBMISSIONS + name, max_age=86400)))
    result: dict[str, FilingRef] = {}
    for table in tables:
        for accession, form, day_text, primary in zip(
            table["accessionNumber"],
            table["form"],
            table["filingDate"],
            table["primaryDocument"],
            strict=True,
        ):
            day = date.fromisoformat(day_text)
            if form not in {"4", "4/A"} or not start <= day <= end:
                continue
            if not _ACCESSION.fullmatch(accession):
                raise SecError("Invalid accession number")
            directory = f"{ARCHIVES}edgar/data/{int(cik)}/{accession.replace('-', '')}"
            if not primary:
                primary = _document_name(await client.get(f"{directory}/{accession}.txt"), form)
            name = _filename(PurePosixPath(primary).name)
            result[accession] = FilingRef(accession, day, form, f"{directory}/{name}")
    return sorted(result.values(), key=lambda item: (item.filing_date, item.accession))
