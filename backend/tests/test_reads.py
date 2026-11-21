"""Section 5 reads against the seeded relational and graph data stores."""

from app.main import create_app
from fastapi.testclient import TestClient


def test_section_five_reads() -> None:
    with TestClient(create_app(), base_url="http://testserver/api/v1/") as c:
        assert c.get("system/info").json()["demo_mode"]
        ring = c.get("mule/rings?limit=1").json()[0]["community"]
        assert c.get(f"mule/ground-truth/{ring}").status_code == 200
        assert c.get(f"mule/timeline?ring_id={ring}").json()
        assert c.get(f"mule/rings/{ring}/graph").json()["links"]
        graph = c.get("mule/graph/overview?max_nodes=5").json()
        assert graph["truncated"] and len(graph["nodes"]) <= 5
        account = graph["nodes"][0]["account_id"]
        assert c.get(f"mule/accounts/{account}").json()["features"]
        assert c.get(f"mule/accounts/{account}/trail").status_code == 200
        assert c.get("insider/companies/ZXQ00/transactions").json()
        for path, status in [
            ("insider/alerts/-1", 404),
            ("mule/rings/-1/graph", 404),
            ("mule/accounts/-1", 404),
            ("mule/accounts/-1/trail", 404),
            ("mule/timeline?ring_id=-1", 404),
            ("mule/ground-truth/-1", 404),
            ("mule/graph/overview?t0=2&t1=1", 422),
            ("insider/radar?from=2025-01-01&to=2024-01-01", 422),
            ("insider/companies/ZXQ00/transactions?from=2025-01-01&to=2024-01-01", 422),
        ]:
            response = c.get(path)
            assert response.headers["content-type"] == "application/problem+json"
            assert response.status_code == response.json()["status"] == status
