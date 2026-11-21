"""Fair-access SEC transport with a shared, capacity-one token bucket."""

import asyncio
import hashlib
import logging
import math
import os
import re
import tempfile
import threading
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)


class SecError(Exception):
    """Failure fetching or caching an SEC resource."""


class AccessPaused(SecError):
    """A 403 paused outgoing requests."""


class TransientError(SecError):
    """An SEC request may succeed after a delay."""


class TokenBucket:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.next_token = 0.0
        self.paused_until = 0.0

    def defer(self, seconds: float, *, forbidden: bool = False) -> None:
        with self.lock:
            until = time.monotonic() + seconds
            self.next_token = max(self.next_token, until)
            if forbidden:
                self.paused_until = max(self.paused_until, until)

    async def acquire(self, rate: float) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                if self.paused_until > now:
                    raise AccessPaused("SEC fair-access cooldown is active")
                delay = self.next_token - now
                if delay <= 0:
                    self.next_token = now + 1 / min(rate, 10)
                    return
            await asyncio.sleep(delay)


_BUCKET = TokenBucket()


def retry_delay(value: str) -> float:
    if value.isdecimal():
        return float(value)
    try:
        return max(0.0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return 0


def _store(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        temp = Path(f.name)
        try:
            f.write(data)
            f.close()
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


class SecClient:
    def __init__(
        self,
        user_agent: str,
        cache: Path,
        rate: float = 8,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not re.fullmatch(r"[^\r\n]+\s+[^\s@]+@[^\s@]+\.[^\s@]+", user_agent) or any(
            ord(c) < 32 or ord(c) > 126 for c in user_agent
        ):
            raise ValueError("SEC_USER_AGENT requires an organization and contact email")
        if not math.isfinite(rate) or rate <= 0:
            raise ValueError("SEC request rate must be positive and finite")
        self.rate = min(10.0, rate)
        self.cache = cache
        self.http = httpx.AsyncClient(
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            transport=transport,
            timeout=30,
        )

    async def aclose(self) -> None:
        await self.http.aclose()

    async def get(self, url: str, *, max_age: float | None = None) -> bytes:
        target = httpx.URL(url)
        if target.scheme != "https" or target.host not in {"www.sec.gov", "data.sec.gov"}:
            raise SecError("Expected an HTTPS SEC resource")
        path = self.cache / hashlib.sha256(url.encode()).hexdigest()
        try:
            if path.exists() and (max_age is None or time.time() - path.stat().st_mtime < max_age):
                return await asyncio.to_thread(path.read_bytes)
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type((TransientError, httpx.TimeoutException)),
                stop=stop_after_attempt(5),
                wait=wait_random_exponential(multiplier=0.5, max=16),
                reraise=True,
            ):
                with attempt:
                    await _BUCKET.acquire(self.rate)
                    response = await self.http.get(url)
                    delay = retry_delay(response.headers.get("Retry-After", ""))
                    if response.status_code == 403:
                        _BUCKET.defer(max(delay, 600), forbidden=True)
                        logging.getLogger(__name__).error(
                            "SEC returned 403; pausing for fair access"
                        )
                        raise AccessPaused("SEC returned 403")
                    if response.status_code == 429 or response.status_code >= 500:
                        _BUCKET.defer(delay)
                        raise TransientError(f"SEC returned {response.status_code}")
                    response.raise_for_status()
                    await asyncio.to_thread(_store, path, response.content)
                    return response.content
        except (OSError, httpx.HTTPError) as exc:
            raise SecError(f"SEC fetch failed for {url}: {exc}") from exc
        raise SecError("SEC retry loop ended without a response")
