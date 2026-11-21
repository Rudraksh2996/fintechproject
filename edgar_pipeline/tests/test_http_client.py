import asyncio
import time
from pathlib import Path

import httpx
import pytest
from edgar_pipeline.http_client import AccessPaused, SecClient, TokenBucket

from edgar_pipeline import http_client

UA = "Test Organization test@example.org"
URL = "https://www.sec.gov/Archives/test"


def test_identity(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        SecClient("missing-contact", tmp_path)


def test_global_rate_and_disk_cache(tmp_path: Path) -> None:
    starts: list[float] = []

    def handler(req: httpx.Request) -> httpx.Response:
        starts.append(time.monotonic())
        assert req.headers["User-Agent"] == UA
        assert req.headers["Accept-Encoding"] == "gzip, deflate"
        return httpx.Response(200, content=b"cached")

    async def run() -> None:
        clients = [SecClient(UA, tmp_path, 100, httpx.MockTransport(handler)) for _ in range(2)]
        try:
            await asyncio.gather(*(clients[i % 2].get(URL + str(i)) for i in range(21)))
            assert await clients[1].get(URL + "0") == b"cached"
            assert len(starts) == 21
            assert starts[-1] - starts[0] >= 2
            assert all(starts[i + 10] - starts[i] >= 1 for i in range(11))
        finally:
            for client in clients:
                await client.aclose()

    asyncio.run(run())


def test_retry_and_cooldown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_client, "_BUCKET", TokenBucket())
    starts: list[float] = []
    statuses = iter([429, 503, 200, 403])

    def handler(req: httpx.Request) -> httpx.Response:
        starts.append(time.monotonic())
        return httpx.Response(next(statuses), headers={"Retry-After": "1"})

    async def run() -> None:
        client = SecClient(UA, tmp_path, transport=httpx.MockTransport(handler))
        try:
            await client.get(URL)
            assert starts[1] - starts[0] >= 1
            assert starts[2] - starts[1] >= 1
            with pytest.raises(AccessPaused):
                await client.get(URL + "2")
            with pytest.raises(AccessPaused):
                await client.get(URL + "3")
            assert len(starts) == 4
        finally:
            await client.aclose()

    asyncio.run(run())
