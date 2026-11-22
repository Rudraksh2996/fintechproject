#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
# Exercise nginx over the Compose network using the gateway's locked HTTP/WS clients.
docker compose exec -T backend python - <<'PY'
import asyncio
import json
import os

import httpx
from websockets.asyncio.client import connect

async def main():
    root = "http://frontend:8080"
    async with httpx.AsyncClient(base_url=root,timeout=20) as http:
        async def get(path):
            response = await http.get("/api/v1/" + path)
            response.raise_for_status()
            return response.json()
        health = await get("health")
        assert health["status"] == "ok" and all(health[k] for k in ("postgres","neo4j","model_loaded"))
        assert (await get("system/info"))["model_version"]
        assert (await http.get("/workbench/_stcore/health")).text.strip() == "ok"
        alerts = (await get("insider/alerts?limit=2"))["items"]
        detail = await get(f"insider/alerts/{alerts[0]['id']}")
        assert detail["members"] and detail["score_breakdown"]
        assert await get("insider/radar") and await get(f"insider/companies/{detail['ticker']}/transactions")
        assert sum(c["is_active"] for c in await get("insider/configs")) == 1
        missing = await http.get("/api/v1/insider/alerts/-1")
        assert missing.status_code == 404 and missing.headers["content-type"] == "application/problem+json"
        ring = (await get("mule/rings?limit=1"))[0]["community"]
        graph = await get(f"mule/rings/{ring}/graph")
        assert graph["links"] and graph["nodes"] and await get(f"mule/timeline?ring_id={ring}")
        account = graph["nodes"][0]["account_id"]
        assert (await get(f"mule/accounts/{account}"))["observed_transfers"] > 0
        assert isinstance(await get(f"mule/accounts/{account}/trail?k=2"), list)
        assert (await get("mule/graph/overview?max_nodes=8"))["nodes"]
        if health["demo_mode"]:
            assert isinstance(await get(f"mule/ground-truth/{ring}"),list)
            assert (await http.post("/api/v1/insider/ingest")).status_code == 409
        metrics = await get("mule/model/metrics")
        assert metrics["gnn"]["summary"]["pr_auc"]["mean"] >= .75
        assert set(metrics["cold_start"]["pr_auc"]) == {"1","3","5","10"}
        print("Postgres, Neo4j, model, Streamlit, insider and mule API checks passed.")
    async def channel(name):
        async with connect(f"ws://frontend:8080/ws/{name}",origin=os.environ.get("ORIGIN","http://localhost:8080")) as ws:
            async with asyncio.timeout(35):
                while True:
                    event = json.loads(await ws.recv())
                    assert event["version"] == 1
                    if event["type"] == "heartbeat":
                        assert event["ts"]
                        return
    await asyncio.gather(channel("alerts"),channel("mule"))
    print("Both nginx WebSocket upgrades and versioned heartbeats passed.")
asyncio.run(main())
PY
