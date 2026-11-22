"""Live gateway tests. Use a disposable graph and a populated demo PostgreSQL database."""

import os
from uuid import uuid4

import pytest
from app.main import create_app
from fastapi.testclient import TestClient


def test_system_and_insider_reads() -> None:
    with TestClient(create_app()) as client:
        health = client.get("/api/v1/health")
        assert health.json()["model_loaded"] and health.json()["status"] == "ok"
        assert health.headers["X-Request-ID"]
        feed = client.get("/api/v1/insider/alerts", params={"limit": 2}).json()
        assert len(feed["items"]) == 2 and feed["next_cursor"] is not None
        detail = client.get(f"/api/v1/insider/alerts/{feed['items'][0]['id']}").json()
        assert detail["members"] and detail["score_breakdown"]
        assert (
            client.get("/api/v1/insider/alerts/-1").headers["content-type"]
            == "application/problem+json"
        )
        assert client.get("/api/v1/insider/radar").json()
        assert (
            client.get("/api/v1/mule/model/metrics").json()["gnn"]["summary"]["pr_auc"]["mean"]
            >= 0.75
        )


def test_new_transfer_emits_and_replay_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    # Gate 4 must supply its disposable Neo4j instance for write tests.
    monkeypatch.setenv("NEO4J_URI", os.environ["GATE4_TEST_NEO4J_URI"])
    monkeypatch.setenv("NEO4J_AUTH", os.environ["GATE4_TEST_NEO4J_AUTH"])
    monkeypatch.setenv("RISK_ALERT_THRESHOLD", "1e-20")
    base = uuid4().int % (2**50) + 10000
    accounts = [
        {
            "account_id": i,
            "type": "retail",
            "created_at": 1,
            "home_country": "US",
            "device_id": f"test-d{i}",
            "ip": f"test-i{i}",
        }
        for i in (base, base + 1)
    ]
    payload = {
        "txn_id": base,
        "src": base,
        "dst": base + 1,
        "ts": 1705000000,
        "amount": 240,
        "channel": "transfer",
        "new_accounts": accounts,
    }
    with TestClient(create_app()) as client, client.websocket_connect("/ws/mule") as socket:
        r = client.post("/api/v1/mule/transactions", json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["replayed"] is False
        assert {r["account_id"] for r in body["scores"]} == {base, base + 1}
        event = socket.receive_json()
        assert event["type"] == "account_scored" and event["payload"]["account_id"] in {
            base,
            base + 1,
        }
        ring_event = socket.receive_json()
        if ring_event["type"] == "account_scored":
            ring_event = socket.receive_json()
        assert ring_event["type"] == "ring_detected"
        live_ring = ring_event["payload"]["community"]
        assert client.get(f"/api/v1/mule/rings/{live_ring}/graph").json()["links"]
        assert client.get(f"/api/v1/mule/accounts/{base}").json()["observed_transfers"] == 1
        again = client.post("/api/v1/mule/transactions", json=payload).json()
        assert again["replayed"] and again["scores"] == body["scores"]
        conflict = client.post("/api/v1/mule/transactions", json={**payload, "amount": 241})
        assert (
            conflict.status_code == 409
            and conflict.headers["content-type"] == "application/problem+json"
        )
        assert any(r["community"] == live_ring for r in client.get("/api/v1/mule/rings").json())
        assert client.get("/api/v1/mule/rings?typology=structuring").json() == []
        assert client.get(f"/api/v1/mule/ground-truth/{live_ring}").json() == []
        assert client.get(f"/api/v1/mule/timeline?ring_id={live_ring}").json()
        unknown = client.get("/api/v1/mule/rings/-1/graph")
        assert unknown.status_code == 404 and unknown.json()["detail"] == "Unknown candidate ring"
        subsequent = client.post(
            "/api/v1/mule/transactions", json={**payload, "txn_id": base + 1, "new_accounts": []}
        )
        assert subsequent.status_code == 200, subsequent.text
        assert subsequent.json()["detected_rings"] == []
        updated = client.get(f"/api/v1/mule/accounts/{base}").json()
        assert updated["community"] == live_ring and updated["observed_transfers"] == 2
