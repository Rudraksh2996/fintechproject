"""Integration checks for versioned configuration and asynchronous detection."""

from time import monotonic, sleep

from app.main import create_app
from fastapi.testclient import TestClient


def test_config_and_detection_job() -> None:
    prefix = "/api/v1/insider"
    with TestClient(create_app()) as client:
        current = next(c for c in client.get(prefix + "/configs").json() if c["is_active"])
        saved = client.post(prefix + "/configs", json={"name": "Gateway integration"})
        assert saved.status_code == 201 and not saved.json()["is_active"]
        config_id = saved.json()["id"]
        try:
            assert client.post(f"{prefix}/configs/{config_id}/activate").json()["is_active"]
            assert (
                client.post(prefix + "/configs", json={"name": "Invalid", "w_b": 1}).status_code
                == 422
            )
            assert client.post(prefix + "/configs/-1/activate").status_code == 404
            assert client.post(prefix + "/ingest").status_code == 409
            assert client.get(prefix + "/jobs/-1").status_code == 404
            submitted = client.post(prefix + "/detect")
            assert submitted.status_code == 202
            until = monotonic() + 10
            while monotonic() < until:
                job = client.get(f"{prefix}/jobs/{submitted.json()['id']}").json()
                if job["status"] != "running":
                    break
                sleep(0.1)
            assert job["status"] == "completed" and "ZXQ00" in job["parameters"]["alerts"]
        finally:
            assert client.post(f"{prefix}/configs/{current['id']}/activate").status_code == 200
