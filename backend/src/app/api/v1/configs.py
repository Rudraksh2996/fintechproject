"""Versioned detector configuration and recoverable PostgreSQL-backed jobs."""

import asyncio
import logging
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal, Self

from edgar_pipeline.cli import detect_database, live_ingest
from edgar_pipeline.config import Settings
from edgar_pipeline.conviction import Config
from edgar_pipeline.db.models import DetectionConfig, IngestionRun
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from sqlalchemy import Engine, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlalchemy.orm import Session


class ConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    name: Annotated[str, Field(min_length=1, max_length=200)]
    window_days: int = 14
    min_insiders: int = 3
    cap_insiders: int = 8
    min_insider_value_usd: Decimal = Decimal(25000)
    min_cluster_value_usd: Decimal = Decimal(100000)
    include_ten_percent_owners: bool = False
    exclude_10b5_1: bool = False
    new_position_pct: Annotated[Decimal, Field(gt=0)] = Decimal(1)
    value_cap_multiple: Decimal = Decimal(100)
    holdings_cap: Decimal = Decimal(".5")
    w_b: Decimal = Decimal(".30")
    w_c: Decimal = Decimal(".25")
    w_v: Decimal = Decimal(".25")
    w_h: Decimal = Decimal(".20")

    @model_validator(mode="after")
    def thresholds(self) -> Self:
        Config(**{key: getattr(self, key) for key in Config.__dataclass_fields__})
        return self


class ConfigView(ConfigInput):
    id: int
    is_active: bool


class IngestInput(BaseModel):
    start: date
    end: date
    issuer: str | None = None
    quarterly: bool = False

    @model_validator(mode="after")
    def dates(self) -> Self:
        if self.end < self.start:
            raise ValueError("end precedes start")
        return self


class Job(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source: Literal["gateway_detect", "gateway_ingest"]
    status: Literal["running", "completed", "failed"]
    parameters: dict[str, JsonValue]
    error_detail: str | None
    started_at: datetime
    finished_at: datetime | None


JOB_SOURCES = ("gateway_detect", "gateway_ingest")


def run_next_job(engine: Engine, settings: Settings) -> bool:
    # Keep the queue row locked while the pipeline commits its own transactions.
    # Process death releases the row for another worker to retry.
    with Session(engine) as queue, queue.begin():
        job = queue.scalars(
            select(IngestionRun)
            .where(IngestionRun.source.in_(JOB_SOURCES), IngestionRun.status == "running")
            .order_by(IngestionRun.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).first()
        if job is None:
            return False
        try:
            with Session(engine) as db:
                if job.source == "gateway_detect":
                    alerts = detect_database(db, "synthetic" if settings.demo_mode else "sec_edgar")
                    job.parameters = {**job.parameters, "alerts": list(alerts)}
                else:
                    request = IngestInput.model_validate(job.parameters)
                    runs = asyncio.run(
                        live_ingest(
                            db,
                            settings,
                            request.start,
                            request.end,
                            request.issuer,
                            request.quarterly,
                            Path(os.getenv("EDGAR_CACHE", ".cache/edgar")),
                        )
                    )
                    job.parameters = {**job.parameters, "runs": list(runs)}
            job.status = "completed"
        except Exception as exc:
            logging.getLogger("gateway").exception("Insider job %d failed", job.id)
            job.status = "failed"
            job.error_detail = type(exc).__name__
        job.finished_at = datetime.now(UTC)
        return True


def routes(engine: AsyncEngine, settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/insider")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    @router.get("/configs")
    async def configs() -> list[ConfigView]:
        async with sessions() as db:
            return [
                ConfigView.model_validate(c)
                for c in await db.scalars(
                    select(DetectionConfig).order_by(DetectionConfig.id.desc())
                )
            ]

    @router.post("/configs", status_code=201)
    async def save(request: ConfigInput) -> ConfigView:
        async with sessions.begin() as db:
            config = DetectionConfig(**request.model_dump())
            db.add(config)
            await db.flush()
            return ConfigView.model_validate(config)

    @router.post("/configs/{id}/activate")
    async def activate(id: int) -> ConfigView:
        async with sessions.begin() as db:
            await db.execute(text("SELECT pg_advisory_xact_lock(733451)"))
            config = await db.get(DetectionConfig, id)
            if config is None:
                raise HTTPException(404, "Unknown config")
            if not config.is_active:
                await db.execute(
                    update(DetectionConfig).where(DetectionConfig.is_active).values(is_active=False)
                )
                config.is_active = True
                await db.flush()
            return ConfigView.model_validate(config)

    async def submit(source: str, parameters: dict[str, JsonValue]) -> Job:
        async with sessions.begin() as db:
            row = IngestionRun(source=source, parameters=parameters)
            db.add(row)
            await db.flush()
            return Job.model_validate(row)

    @router.post("/detect", status_code=202)
    async def detect_job() -> Job:
        return await submit("gateway_detect", {})

    @router.post("/ingest", status_code=202)
    async def ingest_job(request: IngestInput | None = None) -> Job:
        if settings.demo_mode:
            raise HTTPException(409, "Live SEC ingestion is disabled in demo mode")
        if request is None:
            raise HTTPException(422, "Specify a filing date range")
        return await submit("gateway_ingest", request.model_dump(mode="json"))

    @router.get("/jobs/{id}")
    async def get_job(id: int) -> Job:
        async with sessions() as db:
            job = await db.get(IngestionRun, id)
            if job is None or job.source not in JOB_SOURCES:
                raise HTTPException(404, "Unknown job")
            return Job.model_validate(job)

    return router
