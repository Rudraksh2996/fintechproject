"""Typed insider alert feed, radar, drilldown and acknowledgement routes."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from edgar_pipeline.db.models import ClusterAlert, ClusterAlertMember, Form4Transaction
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

Status = Literal["new", "acknowledged", "dismissed"]


class TradeView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    insider_id: int
    accession_number: str
    line_number: int
    ticker: str | None
    transaction_date: date
    filing_date: date
    shares: Decimal
    price: Decimal | None
    value_usd: Decimal | None
    raw_xml_url: str


class AlertView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ticker: str
    window_start: date
    window_end: date
    alert_filing_date: date
    n_insiders: int
    n_csuite: int
    total_value_usd: Decimal
    conviction_score: Decimal
    score_breakdown: dict[str, JsonValue]
    config_id: int
    status: Status


class AlertPage(BaseModel):
    items: list[AlertView]
    next_cursor: int | None


class AlertDetail(AlertView):
    members: list[TradeView]


class StatusChange(BaseModel):
    status: Status


def routes(engine: AsyncEngine) -> APIRouter:
    router = APIRouter(prefix="/api/v1/insider")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    @router.get("/alerts")
    async def alerts(
        ticker: str | None = None,
        min_score: Annotated[float, Query(ge=0, le=100)] = 0,
        start: Annotated[date | None, Query(alias="from")] = None,
        to: date | None = None,
        status: Status | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
        cursor: Annotated[int | None, Query(gt=0)] = None,
    ) -> AlertPage:
        if start and to and start > to:
            raise HTTPException(422, "Invalid filing date range")
        stmt = select(ClusterAlert).where(ClusterAlert.conviction_score >= min_score)
        if ticker:
            stmt = stmt.where(ClusterAlert.ticker == ticker.upper())
        if start:
            stmt = stmt.where(ClusterAlert.alert_filing_date >= start)
        if to:
            stmt = stmt.where(ClusterAlert.alert_filing_date <= to)
        if status:
            stmt = stmt.where(ClusterAlert.status == status)
        if cursor:
            stmt = stmt.where(ClusterAlert.id < cursor)
        async with sessions() as db:
            rows = (await db.scalars(stmt.order_by(ClusterAlert.id.desc()).limit(limit + 1))).all()
            return AlertPage(
                items=[AlertView.model_validate(r) for r in rows[:limit]],
                next_cursor=rows[limit - 1].id if len(rows) > limit else None,
            )

    @router.get("/alerts/{alert_id}")
    async def detail(alert_id: int) -> AlertDetail:
        async with sessions() as db:
            row = await db.get(ClusterAlert, alert_id)
            if row is None:
                raise HTTPException(404, "Unknown alert")
            members = (
                await db.scalars(
                    select(Form4Transaction)
                    .join(ClusterAlertMember)
                    .where(ClusterAlertMember.alert_id == alert_id)
                    .order_by(Form4Transaction.id)
                )
            ).all()
            return AlertDetail(
                **AlertView.model_validate(row).model_dump(),
                members=[TradeView.model_validate(m) for m in members],
            )

    @router.patch("/alerts/{alert_id}")
    async def patch(alert_id: int, change: StatusChange) -> AlertView:
        async with sessions.begin() as db:
            changed = (
                await db.scalars(
                    update(ClusterAlert)
                    .where(ClusterAlert.id == alert_id)
                    .values(status=change.status)
                    .returning(ClusterAlert)
                )
            ).one_or_none()
            if changed is None:
                raise HTTPException(404, "Unknown alert")
            return AlertView.model_validate(changed)

    @router.get("/companies/{ticker}/transactions")
    async def transactions(
        ticker: str,
        start: Annotated[date | None, Query(alias="from")] = None,
        to: date | None = None,
    ) -> list[TradeView]:
        q = select(Form4Transaction).where(
            Form4Transaction.ticker == ticker.upper(), Form4Transaction.superseded.is_(False)
        )
        if start:
            q = q.where(Form4Transaction.transaction_date >= start)
        if to:
            q = q.where(Form4Transaction.transaction_date <= to)
        async with sessions() as db:
            rows = await db.scalars(
                q.order_by(Form4Transaction.transaction_date, Form4Transaction.id)
            )
            return [TradeView.model_validate(r) for r in rows]

    @router.get("/radar")
    async def radar(
        start: Annotated[date | None, Query(alias="from")] = None, to: date | None = None
    ) -> list[AlertView]:
        q = select(ClusterAlert)
        if start:
            q = q.where(ClusterAlert.alert_filing_date >= start)
        if to:
            q = q.where(ClusterAlert.alert_filing_date <= to)
        async with sessions() as db:
            return [
                AlertView.model_validate(r) for r in await db.scalars(q.order_by(ClusterAlert.id))
            ]

    return router
