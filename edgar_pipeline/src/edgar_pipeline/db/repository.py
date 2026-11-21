"""Atomic filing ingestion. One XML transaction line represents one purchase."""

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DataError, SQLAlchemyError
from sqlalchemy.orm import Session

from edgar_pipeline.db.models import (
    Company,
    Form4Filing,
    Form4Transaction,
    IngestionRun,
    Insider,
    ParseError,
)
from edgar_pipeline.form4_parser import Filing, FilingParseError, parse_form4


class IngestionError(Exception):
    """A database operation prevented batch completion."""


@dataclass(frozen=True)
class FilingInput:
    accession: str
    filed: date
    url: str
    xml: bytes
    supersedes: str | None = None


def _owners(filing: Filing) -> set[str]:
    return {owner.cik.zfill(10) for owner in filing.owners}


def _original(
    db: Session, item: FilingInput, filing: Filing, company: int, source: str
) -> str | None:
    if filing.form != "4/A":
        if item.supersedes:
            raise FilingParseError("Only an amendment may supersede a filing")
        return None
    candidates = select(Form4Filing).where(
        Form4Filing.company_id == company,
        Form4Filing.source == source,
        Form4Filing.filing_date <= item.filed,
        ~Form4Filing.accession_number.in_(
            select(Form4Filing.supersedes_accession).where(
                Form4Filing.supersedes_accession.is_not(None)
            )
        ),
    )
    if item.supersedes:
        candidates = candidates.where(Form4Filing.accession_number == item.supersedes)
    elif filing.period is not None:
        candidates = candidates.where(Form4Filing.period_of_report == filing.period)
    else:
        raise FilingParseError("Amendment lacks an original accession or reporting period")
    matches = [
        row.accession_number
        for row in db.scalars(candidates)
        if _owners(parse_form4(row.raw_xml.encode())) == _owners(filing)
    ]
    if len(matches) != 1:
        raise FilingParseError("Amendment does not identify exactly one active original")
    return matches[0]


def _save(db: Session, item: FilingInput, source: str) -> int:
    filing = parse_form4(item.xml)
    raw = item.xml.decode("utf-8-sig")
    digest = hashlib.sha256(item.xml).hexdigest()
    # The company upsert serializes competing amendments for this issuer.
    statement = insert(Company).values(
        cik=filing.issuer_cik.zfill(10), name=filing.issuer_name, ticker=filing.ticker
    )
    company = db.scalars(
        statement.on_conflict_do_update(
            index_elements=[Company.cik],
            set_={"name": statement.excluded.name, "ticker": statement.excluded.ticker},
        ).returning(Company.id)
    ).one()
    existing = db.get(Form4Filing, item.accession)
    if existing is not None:
        if (existing.sha256, existing.source, existing.filing_date) != (digest, source, item.filed):
            raise FilingParseError("Accession already exists with different content or provenance")
        return 0
    parent = _original(db, item, filing, company, source)
    db.add(
        Form4Filing(
            accession_number=item.accession,
            company_id=company,
            filing_date=item.filed,
            period_of_report=filing.period,
            form_type=filing.form,
            supersedes_accession=parent,
            raw_xml_url=item.url,
            raw_xml=raw,
            sha256=digest,
            source=source,
        )
    )
    db.flush()
    if parent:
        db.execute(
            update(Form4Transaction)
            .where(Form4Transaction.accession_number == parent)
            .values(superseded=True)
        )
    ids: dict[str, int] = {}
    for owner in sorted(filing.owners, key=lambda o: o.cik):
        stmt = insert(Insider).values(cik=owner.cik.zfill(10), name=owner.name)
        ids[owner.cik] = db.scalars(
            stmt.on_conflict_do_update(
                index_elements=[Insider.cik], set_={"name": stmt.excluded.name}
            ).returning(Insider.id)
        ).one()
    # Joint filings have one economic amount per XML line. Retain the complete
    # owner list in raw XML and use the first reported owner for line attribution.
    owner = filing.owners[0]
    count = 0
    for row in filing.purchases:
        saved = db.scalars(
            insert(Form4Transaction)
            .values(
                accession_number=item.accession,
                line_number=row.line,
                company_id=company,
                insider_id=ids[owner.cik],
                ticker=filing.ticker,
                transaction_date=row.transaction_date,
                filing_date=item.filed,
                transaction_code="P",
                acquired_disposed="A",
                shares=row.shares,
                price=row.price,
                value_usd=row.value_usd,
                shares_owned_after=row.post_shares,
                pct_holdings_increase=row.holdings_increase(),
                is_director=owner.director,
                is_officer=owner.officer,
                officer_title=owner.title,
                is_ten_percent_owner=owner.ten_percent,
                is_other=owner.other,
                is_csuite=bool(
                    re.search(r"\b(?:C[A-Z]{1,3}O|chief\b.*\bofficer)\b", owner.title or "", re.I)
                ),
                is_10b5_1=filing.plan_10b5_1,
                is_amendment=parent is not None,
                is_new_position=row.post_shares is not None and row.post_shares == row.shares,
                missing_price=row.price is None,
                direct_or_indirect=row.ownership,
                footnote_refs=list(row.footnotes),
                raw_xml_url=item.url,
            )
            .on_conflict_do_nothing(
                index_elements=[Form4Transaction.accession_number, Form4Transaction.line_number]
            )
            .returning(Form4Transaction.id)
        ).one_or_none()
        count += int(saved is not None)
    return count


def ingest(
    db: Session, items: Iterable[FilingInput], source: Literal["synthetic", "sec_edgar"]
) -> int:
    """Use a dedicated session. Commit each filing together with its run counters."""
    run = IngestionRun(source=source, parameters={})
    db.add(run)
    try:
        db.flush()
        run_id = run.id
        db.commit()
        for item in items:
            try:
                with db.begin_nested():
                    inserted = _save(db, item, source)
                run.transactions_inserted += inserted
            except (FilingParseError, UnicodeError, DataError) as exc:
                db.add(
                    ParseError(
                        accession_number=item.accession,
                        ingestion_run_id=run_id,
                        raw_xml_url=item.url,
                        raw_xml=item.xml.decode(errors="replace").replace("\x00", "�"),
                        error_type=type(exc).__name__,
                        error_detail=str(exc).splitlines()[0],
                    )
                )
                run.errors += 1
            run.filings_seen += 1
            db.commit()
        run.status = "completed"
        run.finished_at = datetime.now(UTC)
        db.commit()
        return run_id
    except Exception as exc:
        db.rollback()
        if run.id is not None and (failed := db.get(IngestionRun, run.id)) is not None:
            failed.status = "failed"
            failed.error_detail = type(exc).__name__
            failed.finished_at = datetime.now(UTC)
            db.commit()
        if isinstance(exc, SQLAlchemyError):
            raise IngestionError("Could not persist ingestion batch") from exc
        raise
