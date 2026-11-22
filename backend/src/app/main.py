"""Single-origin gateway backed by the live databases and shipped bootstrap artifacts."""

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

import torch
from edgar_pipeline.config import Settings
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from ml_pipeline.config import GraphSettings
from neo4j import AsyncGraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable
from pydantic import BaseModel, JsonValue
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, Response

from app.api.v1.configs import routes as config_routes
from app.api.v1.configs import run_next_job
from app.api.v1.insider import routes as insider_routes
from app.api.v1.mule import routes as mule_routes
from app.services.replay import replay
from app.services.transfers import (
    AccountScore,
    RingScore,
    RuntimeModel,
    TransferConflict,
    TransferInput,
    TransferResult,
    apply_transfer,
)
from app.settings import GatewaySettings
from app.ws.alerts import AlertHub, Heartbeat, stop_task


class Problem(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    postgres: bool
    neo4j: bool
    model_loaded: bool
    demo_mode: bool
    version: str


class SystemInfo(BaseModel):
    version: str
    demo_mode: bool
    model_version: str
    model_architecture: str
    scoring_note: str


class ScoreEvent(BaseModel):
    type: Literal["account_scored"] = "account_scored"
    version: Literal[1] = 1
    payload: AccountScore


class RingEvent(BaseModel):
    type: Literal["ring_detected"] = "ring_detected"
    version: Literal[1] = 1
    payload: RingScore


def create_app() -> FastAPI:
    config = GatewaySettings()
    sql = Settings()
    graph = GraphSettings()
    artifacts = Path(os.environ.get("ARTIFACT_DIR", "/artifacts"))
    engine = create_async_engine(
        sql.database_url().set(drivername="postgresql+asyncpg"),
        pool_pre_ping=True,
        connect_args={
            "timeout": config.database_timeout_seconds,
            "command_timeout": config.database_timeout_seconds,
        },
    )
    user, password = graph.neo4j_auth.get_secret_value().split("/", 1)
    driver = AsyncGraphDatabase.driver(
        graph.neo4j_uri, auth=(user, password), connection_timeout=config.database_timeout_seconds
    )
    alerts = AlertHub(engine, sql.database_url(), config.database_timeout_seconds)
    model: RuntimeModel | None = None
    subscribers: set[asyncio.Queue[ScoreEvent | RingEvent]] = set()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        nonlocal model
        worker_engine = create_engine(sql.database_url(), pool_pre_ping=True)
        stopping = asyncio.Event()

        async def process_jobs() -> None:
            while not stopping.is_set():
                try:
                    if await asyncio.to_thread(run_next_job, worker_engine, sql):
                        continue
                except SQLAlchemyError:
                    logging.getLogger("gateway").exception("Job queue unavailable")
                try:
                    await asyncio.wait_for(stopping.wait(), 0.5)
                except TimeoutError:
                    continue

        try:
            torch.set_num_threads(graph.torch_num_threads)
            model = await asyncio.to_thread(
                RuntimeModel, artifacts, graph.seed, graph.reporting_threshold
            )
            async with driver.session() as session:
                await (
                    await session.run(
                        "CREATE CONSTRAINT scoring_state_name IF NOT EXISTS "
                        "FOR (s:ScoringState) REQUIRE s.name IS UNIQUE"
                    )
                ).consume()
            listener = asyncio.create_task(alerts.listen())
            worker = asyncio.create_task(process_jobs())
            replay_task: asyncio.Task[None] | None = None
            try:
                await asyncio.wait_for(alerts.ready.wait(), config.database_timeout_seconds)
                if config.demo_mode and config.replay_enabled:
                    replay_task = asyncio.create_task(
                        replay(worker_engine, sql.seed, config.replay_speed, stopping)
                    )
                yield
            finally:
                await stop_task(listener)
                stopping.set()
                await worker
                if replay_task is not None:
                    await replay_task
        finally:
            worker_engine.dispose()
            model = None
            await driver.close()
            await engine.dispose()

    app = FastAPI(title="FinTech Threat and Signal Gateway", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[config.origin],
        allow_methods=["GET", "PATCH", "POST"],
        allow_headers=["Content-Type", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_log(
        request: Request, next_call: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = uuid4().hex
        response = await next_call(request)
        response.headers["X-Request-ID"] = rid
        logging.getLogger("gateway").info(
            json.dumps(
                {
                    "request_id": rid,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                }
            )
        )
        return response

    def problem(status: int, title: str, detail: str) -> JSONResponse:
        return JSONResponse(
            Problem(status=status, title=title, detail=detail).model_dump(),
            status_code=status,
            media_type="application/problem+json",
        )

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        return problem(exc.status_code, "Request failed", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return problem(422, "Invalid request", "; ".join(str(e["msg"]) for e in exc.errors()))

    async def db_error(_: Request, exc: Exception) -> JSONResponse:
        return problem(503, "Database unavailable", "The database operation could not complete.")

    for error in (Neo4jError, ServiceUnavailable, SQLAlchemyError):
        app.add_exception_handler(error, db_error)

    @app.exception_handler(Exception)
    async def internal_error(_: Request, exc: Exception) -> JSONResponse:
        logging.getLogger("gateway").exception("Unhandled gateway error")
        return problem(500, "Internal server error", "The request could not be completed.")

    @app.get("/api/v1/health")
    async def health() -> Health:
        pg = neo = False
        try:
            async with engine.connect() as conn:
                pg = (await conn.scalar(text("SELECT 1"))) == 1
        except (SQLAlchemyError, OSError, TimeoutError):
            pg = False
        try:
            await driver.verify_connectivity()
            neo = True
        except (Neo4jError, ServiceUnavailable, OSError):
            neo = False
        return Health(
            status="ok" if pg and neo and model is not None else "degraded",
            postgres=pg,
            neo4j=neo,
            model_loaded=model is not None,
            demo_mode=config.demo_mode,
            version=app.version,
        )

    @app.get("/api/v1/system/info")
    def info() -> SystemInfo:
        return SystemInfo(
            version=app.version,
            demo_mode=config.demo_mode,
            model_version=model.version if model else "unavailable",
            model_architecture=model.model.arch if model else "unavailable",
            scoring_note="Scores use currently observed transfers. New-account validation uses "
            "held-out accounts restored with their observed transfer history.",
        )

    @app.get("/api/v1/mule/model/metrics")
    def model_metrics() -> dict[str, JsonValue]:
        from pydantic import TypeAdapter

        return TypeAdapter(dict[str, JsonValue]).validate_json(
            (artifacts / "metrics.json").read_bytes()
        )

    @app.post("/api/v1/mule/transactions")
    async def transfer(item: TransferInput) -> TransferResult:
        if model is None:
            raise HTTPException(503, "Inference model unavailable")
        try:
            result = await apply_transfer(driver, model, item, graph.risk_alert_threshold)
        except TransferConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        if not result.replayed:
            for score in result.scores:
                if score.crossed_threshold:
                    for queue in subscribers:
                        queue.put_nowait(ScoreEvent(payload=score))
            for ring in result.detected_rings:
                for queue in subscribers:
                    queue.put_nowait(RingEvent(payload=ring))
        return result

    @app.websocket("/ws/alerts")
    async def ws_alerts(ws: WebSocket) -> None:
        await alerts.serve(ws, config.origin)

    @app.websocket("/ws/mule")
    async def ws_mule(ws: WebSocket) -> None:
        if ws.headers.get("origin") not in (None, config.origin):
            await ws.close(code=1008)
            return
        await ws.accept()
        queue: asyncio.Queue[ScoreEvent | RingEvent] = asyncio.Queue()
        subscribers.add(queue)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), 15)
                    await ws.send_text(event.model_dump_json())
                except TimeoutError:
                    await ws.send_text(Heartbeat(ts=datetime.now(UTC)).model_dump_json())
        except WebSocketDisconnect:
            return
        finally:
            subscribers.discard(queue)

    app.include_router(config_routes(engine, sql))
    app.include_router(insider_routes(engine))
    app.include_router(mule_routes(driver, artifacts, config.demo_mode))
    return app
