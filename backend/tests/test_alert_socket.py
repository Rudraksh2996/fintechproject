"""End-to-end LISTEN/NOTIFY over a real TCP WebSocket and an independent DB session."""

import json
import socket
import subprocess
import sys
from collections.abc import Iterator
from time import monotonic, sleep

import httpx
import pytest
from websockets.sync.client import connect


@pytest.fixture
def gateway_url() -> Iterator[str]:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:create_app",
                "--factory",
                "--fd",
                str(sock.fileno()),
                "--log-level",
                "warning",
            ],
            pass_fds=(sock.fileno(),),
        )
        base = f"http://127.0.0.1:{port}"
        try:
            deadline = monotonic() + 30
            while monotonic() < deadline:
                if proc.poll() is not None:
                    pytest.fail("Gateway exited during startup")
                try:
                    if httpx.get(base + "/api/v1/health", timeout=1).is_success:
                        break
                except httpx.TransportError:
                    sleep(0.1)
            else:
                pytest.fail("Gateway did not become ready")
            yield base
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def test_committed_alert_reaches_tcp_client(gateway_url: str) -> None:
    with httpx.Client(base_url=gateway_url + "/api/v1/insider/") as api:
        current = next(c for c in api.get("configs").json() if c["is_active"])
        config = api.post("configs", json={"name": "Socket integration"}).json()
        try:
            api.post(f"configs/{config['id']}/activate").raise_for_status()
            with connect(gateway_url.replace("http://", "ws://") + "/ws/alerts") as ws:
                api.post("detect").raise_for_status()
                event = json.loads(ws.recv(timeout=10))
                assert event["type"] == "cluster_alert" and event["version"] == 1
                row = event["payload"]
                assert row["config_id"] == config["id"]
                assert (
                    api.get(f"alerts/{row['id']}").json()["score_breakdown"]
                    == row["score_breakdown"]
                )
        finally:
            api.post(f"configs/{current['id']}/activate").raise_for_status()
