"""Forward committed PostgreSQL alert inserts to connected WebSocket clients."""

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime
from typing import Literal

import asyncpg  # type: ignore[import-untyped]
from app.api.v1.insider import AlertView
from edgar_pipeline.db.models import ClusterAlert
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker


class AlertEvent(BaseModel):
    type: Literal["cluster_alert"] = "cluster_alert"
    version: Literal[1] = 1
    payload: AlertView


class Heartbeat(BaseModel):
    type: Literal["heartbeat"] = "heartbeat"
    version: Literal[1] = 1
    ts: datetime


class AlertHub:
    def __init__(self, engine: AsyncEngine, url: URL, timeout: float) -> None:
        self.sessions = async_sessionmaker(engine)
        self.url = url.set(drivername="postgresql").render_as_string(hide_password=False)
        self.timeout = timeout
        self.ready = asyncio.Event()
        self.subscribers: set[asyncio.Queue[AlertEvent | None]] = set()

    async def listen(self) -> None:
        while True:
            conn = None
            try:
                conn = await asyncpg.connect(self.url, timeout=self.timeout)
                pending: asyncio.Queue[str | None] = asyncio.Queue()

                def notified(
                    connection: object,
                    pid: int,
                    channel: str,
                    payload: str,
                    q: asyncio.Queue[str | None] = pending,
                ) -> None:
                    q.put_nowait(payload)

                conn.add_termination_listener(lambda _, q=pending: q.put_nowait(None))
                await conn.add_listener("cluster_alerts", notified)
                self.ready.set()
                while (payload := await pending.get()) is not None:
                    if not payload.isdecimal():
                        continue
                    async with self.sessions() as db:
                        row = await db.get(ClusterAlert, int(payload))
                        if row is None:
                            continue
                        event = AlertEvent(payload=AlertView.model_validate(row))
                    for queue in tuple(self.subscribers):
                        if queue.full():
                            self.subscribers.discard(queue)
                            queue.get_nowait()
                            queue.put_nowait(None)
                        else:
                            queue.put_nowait(event)
            except Exception:
                logging.getLogger("gateway").exception("Alert listener disconnected")
            finally:
                self.ready.clear()
                if conn is not None:
                    await conn.close(timeout=self.timeout)
            await asyncio.sleep(1)

    async def serve(self, ws: WebSocket, origin: str) -> None:
        if ws.headers.get("origin") not in (None, origin):
            await ws.close(code=1008)
            return
        queue: asyncio.Queue[AlertEvent | None] = asyncio.Queue(maxsize=256)
        self.subscribers.add(queue)
        try:
            await ws.accept()
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), 15)
                    if event is None:
                        await ws.close(code=1013)
                        return
                    await ws.send_text(event.model_dump_json())
                except TimeoutError:
                    await ws.send_text(Heartbeat(ts=datetime.now(UTC)).model_dump_json())
        except WebSocketDisconnect:
            return
        finally:
            self.subscribers.discard(queue)


async def stop_task(task: asyncio.Task[None]) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
